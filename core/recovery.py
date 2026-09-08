"""
recovery.py
-----------
Phase 6 — Auto-recovery.

Per Constitution Principle #4 (Fail-safe) and the Phase 6 goal:
  - Retry wrapper around agent.run() with configurable max_retries
  - Fallback agent logic: if Agent A fails N times, route task to Agent B

This module knows nothing about FastAPI or logging — it's a pure
orchestration function that takes agents in, returns a result + full
attempt history out. The caller (main.py) decides what to log/persist.
"""

import time
from typing import Optional, List
from agents.base_agent import BaseAgent


def run_with_recovery(
    agent: BaseAgent,
    task: str,
    max_retries: int = 0,
    fallback_agent: Optional[BaseAgent] = None,
    retry_delay_seconds: float = 0.0,
) -> dict:
    """
    Executes `task` on `agent`, retrying up to `max_retries` times on
    failure. If still failing after all retries and a `fallback_agent`
    is given, routes the task to the fallback agent as a last resort.

    Returns:
        {
            "final_result": <the last BaseAgent.run() dict, from whichever
                              agent ultimately produced it>,
            "attempts": [ { "attempt": int, "agent_id", "agent_name",
                             "is_fallback": bool, "result": <run dict> }, ... ],
            "used_fallback": bool,
            "retries_used": int,
        }

    Never raises — every attempt goes through BaseAgent.run(), which is
    itself fail-safe, so this function can't crash the caller either.
    """
    attempts: List[dict] = []
    result = None
    total_primary_attempts = max_retries + 1

    for attempt_num in range(1, total_primary_attempts + 1):
        result = agent.run(task)
        attempts.append({
            "attempt": attempt_num,
            "agent_id": agent.id,
            "agent_name": agent.name,
            "is_fallback": False,
            "result": result,
        })
        if result["status"] == "success":
            break
        if attempt_num < total_primary_attempts and retry_delay_seconds > 0:
            time.sleep(retry_delay_seconds)

    used_fallback = False
    if result["status"] != "success" and fallback_agent is not None:
        used_fallback = True
        result = fallback_agent.run(task)
        attempts.append({
            "attempt": len(attempts) + 1,
            "agent_id": fallback_agent.id,
            "agent_name": fallback_agent.name,
            "is_fallback": True,
            "result": result,
        })

    retries_used = sum(1 for a in attempts if not a["is_fallback"]) - 1
    retries_used = max(retries_used, 0)

    return {
        "final_result": result,
        "attempts": attempts,
        "used_fallback": used_fallback,
        "retries_used": retries_used,
    }
