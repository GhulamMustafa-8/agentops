"""
base_agent.py
--------------
BaseAgent: the atomic unit AgentOps orchestrates.

Per Constitution Principle #4 (Fail-safe): an agent's run() method must
NEVER let an exception propagate uncaught - it always returns a structured
result dict, even on failure, so the Registry/API layer stays alive no
matter what a single agent does internally.
"""

import uuid
import time
from core.llm_client import LLMClient, LLMClientError


class BaseAgent:
    def __init__(self, name: str, role: str, model: str = None, base_url: str = None, backend: str = None):
        self.id = str(uuid.uuid4())
        self.name = name
        self.role = role  # e.g. "You are a helpful research assistant."
        self.llm = LLMClient(model=model, base_url=base_url, backend=backend)
        self.created_at = time.time()

    def run(self, task: str) -> dict:
        """
        Execute a single task through this agent's LLM.

        Returns a normalized result dict — always, regardless of success
        or failure:
            {
                "agent_id": str,
                "task": str,
                "status": "success" | "error",
                "result": str | None,
                "error": str | None,
                "duration_ms": int,
            }
        """
        start = time.time()
        prompt = f"{self.role}\n\nTask: {task}"

        try:
            output = self.llm.generate(prompt)
            return {
                "agent_id": self.id,
                "task": task,
                "status": "success",
                "result": output["text"],
                "error": None,
                "duration_ms": output["duration_ms"],
            }
        except LLMClientError as e:
            # Known, expected failure mode (LLM backend down, timeout, etc.)
            duration_ms = int((time.time() - start) * 1000)
            return {
                "agent_id": self.id,
                "task": task,
                "status": "error",
                "result": None,
                "error": str(e),
                "duration_ms": duration_ms,
            }
        except Exception as e:
            # Catch-all: an agent must NEVER crash the API process.
            duration_ms = int((time.time() - start) * 1000)
            return {
                "agent_id": self.id,
                "task": task,
                "status": "error",
                "result": None,
                "error": f"Unexpected agent error: {e}",
                "duration_ms": duration_ms,
            }

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "model": self.llm.model,
            "base_url": self.llm.base_url,
            "backend": self.llm.backend,
            "created_at": self.created_at,
        }
