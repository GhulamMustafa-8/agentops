"""
main.py
-------
AgentOps — FastAPI core.

Cumulative scope through Phase 6 (see Project Constitution roadmap):
  Phase 1: Agent registry (create/list/get/delete) + run endpoint
  Phase 2: SQLite-backed run logging + /logs, /stats
  Phase 3: Guardrails (token cap, rate limit, lifetime cap) -> HTTP 429
  Phase 4: Static dashboard at /dashboard (+ /dashboard/summary)
  Phase 5: Agent-to-agent messaging (/messages/*) + auto-forward on run
  Phase 6: Auto-recovery — retries + fallback agent routing
"""

import uuid
import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Optional

from core.registry import registry
from core.logger import logger
from core.guardrails import enforcer, GuardrailViolation, GuardrailConfig
from core.message_bus import bus
from core.recovery import run_with_recovery

app = FastAPI(
    title="AgentOps",
    description="A production-grade orchestration framework for deploying, "
                 "monitoring, and managing multiple AI agents safely.",
    version="0.1.0",
)


# ---------- Request/Response Schemas ----------

class CreateAgentRequest(BaseModel):
    name: str = Field(..., example="Researcher")
    role: str = Field(..., example="You are a meticulous research assistant.")
    model: Optional[str] = Field(None, example="llama3.2")
    base_url: Optional[str] = Field(
        None, description="Override the default backend URL for this agent "
                           "(useful for pointing different agents at different backends)."
    )
    backend: Optional[str] = Field(
        None, description="LLM backend for this agent: 'ollama' (local, default) or "
                           "'groq' (free hosted API, needs GROQ_API_KEY env var set)."
    )


class RunTaskRequest(BaseModel):
    task: str = Field(..., example="Summarize the theory of relativity in 3 bullet points.")
    forward_to: Optional[str] = Field(
        None, description="Agent id to automatically send this run's result to, once it completes."
    )
    auto_run_forward: bool = Field(
        False, description="If true AND forward_to is set, immediately run the forwarded "
                            "agent on the received result too (chains Agent A -> Agent B)."
    )
    max_retries: int = Field(
        0, ge=0, le=5, description="Retry this agent up to N more times on failure before giving up "
                                    "(or falling back, if fallback_agent_id is set)."
    )
    fallback_agent_id: Optional[str] = Field(
        None, description="If set, and the primary agent still fails after all retries, "
                           "the task is automatically routed to this agent instead."
    )


class SendMessageRequest(BaseModel):
    from_agent_id: str
    to_agent_id: str
    content: str


# ---------- Routes ----------

@app.get("/")
def health_check():
    return {
        "status": "ok",
        "service": "AgentOps",
        "phase": "8 - complete (all phases done)",
        "agents_registered": registry.count(),
    }


@app.post("/agents")
def create_agent(req: CreateAgentRequest):
    agent = registry.create_agent(
        name=req.name, role=req.role, model=req.model, base_url=req.base_url, backend=req.backend
    )
    return agent.to_dict()


@app.get("/agents")
def list_agents():
    return {"agents": registry.list_agents(), "count": registry.count()}


@app.get("/agents/{agent_id}")
def get_agent(agent_id: str):
    agent = registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")
    return agent.to_dict()


@app.delete("/agents/{agent_id}")
def delete_agent(agent_id: str):
    deleted = registry.delete_agent(agent_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")
    enforcer.reset_agent(agent_id)
    return {"status": "deleted", "agent_id": agent_id}


@app.post("/agents/{agent_id}/run")
def run_agent(agent_id: str, req: RunTaskRequest):
    agent = registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")

    # Phase 3: guardrails checked BEFORE the task ever reaches the LLM.
    try:
        approx_tokens = enforcer.check(agent_id, req.task)
    except GuardrailViolation as e:
        raise HTTPException(status_code=429, detail=e.reason)

    # Phase 6: fallback agent must exist up-front, before we spend any attempts.
    fallback_agent = None
    if req.fallback_agent_id:
        fallback_agent = registry.get_agent(req.fallback_agent_id)
        if not fallback_agent:
            raise HTTPException(
                status_code=404,
                detail=f"fallback_agent_id '{req.fallback_agent_id}' not found."
            )

    # run_with_recovery is fail-safe (delegates to BaseAgent.run() throughout),
    # and handles retries + fallback routing internally.
    recovery_outcome = run_with_recovery(
        agent=agent,
        task=req.task,
        max_retries=req.max_retries,
        fallback_agent=fallback_agent,
    )
    # Make a shallow copy — recovery_outcome["final_result"] is the SAME
    # object referenced inside attempts[-1]["result"]; mutating it in place
    # would create a circular reference (result["attempts"][-1]["result"] == result)
    # that crashes JSON serialization with a RecursionError.
    result = dict(recovery_outcome["final_result"])
    enforcer.record(agent_id)
    if recovery_outcome["used_fallback"]:
        enforcer.record(req.fallback_agent_id)

    # Phase 2: persist EVERY attempt (not just the final one) for full observability.
    for a in recovery_outcome["attempts"]:
        a_run_id = str(uuid.uuid4())
        logger.log_run(run_id=a_run_id, agent_id=a["agent_id"], agent_name=a["agent_name"], run_result=a["result"])
        a["run_id"] = a_run_id

    result["run_id"] = recovery_outcome["attempts"][-1]["run_id"]
    result["approx_input_tokens"] = approx_tokens
    result["retries_used"] = recovery_outcome["retries_used"]
    result["used_fallback"] = recovery_outcome["used_fallback"]
    result["attempts"] = recovery_outcome["attempts"]

    # Phase 5: optional auto-forward — Agent A's result flows to Agent B
    # without any manual step, per the Constitution's multi-agent-comms goal.
    if req.forward_to and result["status"] == "success":
        target_agent = registry.get_agent(req.forward_to)
        if not target_agent:
            raise HTTPException(
                status_code=404,
                detail=f"forward_to agent '{req.forward_to}' not found."
            )

        message = bus.send(
            from_agent_id=agent_id,
            to_agent_id=req.forward_to,
            content=result["result"],
        )
        result["forwarded_message"] = message

        if req.auto_run_forward:
            try:
                fwd_tokens = enforcer.check(req.forward_to, result["result"])
            except GuardrailViolation as e:
                result["forward_run"] = {"status": "blocked", "error": e.reason}
                return result

            forward_result = target_agent.run(result["result"])
            enforcer.record(req.forward_to)
            fwd_run_id = str(uuid.uuid4())
            logger.log_run(
                run_id=fwd_run_id,
                agent_id=target_agent.id,
                agent_name=target_agent.name,
                run_result=forward_result,
            )
            forward_result["run_id"] = fwd_run_id
            forward_result["approx_input_tokens"] = fwd_tokens
            bus.mark_read(req.forward_to, message["id"])
            result["forward_run"] = forward_result

    return result


@app.post("/messages/send")
def send_message(req: SendMessageRequest):
    if not registry.get_agent(req.from_agent_id):
        raise HTTPException(status_code=404, detail=f"Agent '{req.from_agent_id}' (sender) not found.")
    if not registry.get_agent(req.to_agent_id):
        raise HTTPException(status_code=404, detail=f"Agent '{req.to_agent_id}' (recipient) not found.")
    return bus.send(req.from_agent_id, req.to_agent_id, req.content)


@app.get("/messages/inbox/{agent_id}")
def get_inbox(agent_id: str, unread_only: bool = False):
    if not registry.get_agent(agent_id):
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")
    return {
        "agent_id": agent_id,
        "unread_count": bus.unread_count(agent_id),
        "messages": bus.inbox(agent_id, unread_only=unread_only),
    }


@app.post("/messages/inbox/{agent_id}/read")
def mark_inbox_read(agent_id: str, message_id: Optional[str] = None):
    if not registry.get_agent(agent_id):
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")
    marked = bus.mark_read(agent_id, message_id=message_id)
    return {"agent_id": agent_id, "marked_read": marked}


@app.get("/guardrails")
def get_guardrail_config():
    return enforcer.config.model_dump()


@app.put("/guardrails")
def update_guardrail_config(config: GuardrailConfig):
    enforcer.config = config
    return enforcer.config.model_dump()


@app.get("/guardrails/{agent_id}/usage")
def get_guardrail_usage(agent_id: str):
    if not registry.get_agent(agent_id):
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")
    return enforcer.usage(agent_id)


# ---------- Phase 4: Dashboard ----------

DASHBOARD_HTML_PATH = os.path.join(os.path.dirname(__file__), "dashboard", "index.html")


@app.get("/dashboard")
def serve_dashboard():
    """Serves the static HTML/JS dashboard (polls /dashboard/summary and /logs)."""
    return FileResponse(DASHBOARD_HTML_PATH)


@app.get("/dashboard/summary")
def dashboard_summary():
    """
    One combined payload for the dashboard's top cards + agents table,
    so the frontend doesn't need to stitch together /agents + /stats
    + per-agent last-run lookups itself on every poll.
    """
    agents = registry.list_agents()
    global_stats = logger.get_stats()

    per_agent_stats = {row["agent_id"]: row for row in global_stats["per_agent"]}

    enriched_agents = []
    for agent in agents:
        agent_id = agent["id"]
        stats = per_agent_stats.get(agent_id, {})
        last_run = logger.get_last_run(agent_id)
        total = stats.get("total_runs", 0)
        success = stats.get("success_runs", 0)
        enriched_agents.append({
            **agent,
            "total_runs": total,
            "success_rate": round(success / total, 3) if total else None,
            "last_run_status": last_run["status"] if last_run else None,
            "last_run_time": last_run["timestamp"] if last_run else None,
        })

    return {
        "agent_count": len(agents),
        "global_stats": global_stats,
        "agents": enriched_agents,
    }


@app.get("/logs")
def get_logs(agent_id: Optional[str] = None, limit: int = 50, offset: int = 0):
    return {"logs": logger.get_logs(agent_id=agent_id, limit=limit, offset=offset)}


@app.get("/stats")
def get_stats(agent_id: Optional[str] = None):
    return logger.get_stats(agent_id=agent_id)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
