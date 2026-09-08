"""
guardrails.py
-------------
Phase 3 — Guardrails.

Per Constitution Principle #2 (Zero-cost by default) and the Phase 3 goal
("cost/token tracking, rate limiting, max-runs-per-agent caps"), this
module enforces limits BEFORE a task reaches the LLM, so a runaway loop
or misbehaving client can't blow up local resources or (if a paid
backend is ever swapped in later) run up a bill.

Three independent checks, all configurable via `GuardrailConfig`:
  1. max_tokens_per_task   — reject oversized single tasks
  2. max_runs_per_agent    — lifetime cap per agent
  3. max_runs_per_minute   — sliding-window rate limit per agent

Token counting uses tiktoken if it's installed (accurate), otherwise
falls back to a cheap character-based approximation — either way, no
network call and no paid API involved (Constitution Principle #2).
"""

import time
from collections import defaultdict, deque
from typing import Optional
from pydantic import BaseModel

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")
except Exception:
    # tiktoken not installed, or its encoding file couldn't be fetched
    # (e.g. no internet). Fall back gracefully — guardrails must never
    # crash the app just because an optional precision tool is missing.
    _ENC = None


def count_tokens(text: str) -> int:
    """Best-effort token count. Accurate via tiktoken if available,
    else ~4 chars/token approximation (a commonly used rule of thumb)."""
    if not text:
        return 0
    if _ENC:
        return len(_ENC.encode(text))
    return max(1, len(text) // 4)


class GuardrailConfig(BaseModel):
    max_tokens_per_task: Optional[int] = 2000
    max_runs_per_agent: Optional[int] = None       # None = unlimited lifetime runs
    max_runs_per_minute: Optional[int] = 10        # per-agent sliding window


class GuardrailViolation(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class GuardrailEnforcer:
    def __init__(self, config: Optional[GuardrailConfig] = None):
        self.config = config or GuardrailConfig()
        self._run_timestamps = defaultdict(deque)  # agent_id -> deque[float]
        self._total_runs = defaultdict(int)         # agent_id -> int

    def check(self, agent_id: str, task: str) -> int:
        """
        Raises GuardrailViolation if any limit would be breached.
        Returns the approximate token count of the task on success
        (so callers can surface it without re-computing).
        """
        now = time.time()

        # 1. Token cap — reject oversized tasks outright.
        tokens = count_tokens(task)
        if self.config.max_tokens_per_task and tokens > self.config.max_tokens_per_task:
            raise GuardrailViolation(
                f"Task rejected: ~{tokens} tokens exceeds max_tokens_per_task "
                f"({self.config.max_tokens_per_task})."
            )

        # 2. Lifetime cap per agent.
        if self.config.max_runs_per_agent and self._total_runs[agent_id] >= self.config.max_runs_per_agent:
            raise GuardrailViolation(
                f"Agent has reached its lifetime run cap "
                f"({self.config.max_runs_per_agent} runs). Create a new agent or raise the cap."
            )

        # 3. Rate limit — sliding 60s window per agent.
        window = self._run_timestamps[agent_id]
        while window and now - window[0] > 60:
            window.popleft()
        if self.config.max_runs_per_minute and len(window) >= self.config.max_runs_per_minute:
            raise GuardrailViolation(
                f"Rate limit exceeded: max {self.config.max_runs_per_minute} runs/minute per agent. "
                f"Try again shortly."
            )

        return tokens

    def record(self, agent_id: str):
        """Call AFTER a run is allowed through, to count it against the caps."""
        now = time.time()
        self._run_timestamps[agent_id].append(now)
        self._total_runs[agent_id] += 1

    def reset_agent(self, agent_id: str):
        """Clear an agent's guardrail history (e.g. when the agent is deleted)."""
        self._run_timestamps.pop(agent_id, None)
        self._total_runs.pop(agent_id, None)

    def usage(self, agent_id: str) -> dict:
        window = self._run_timestamps[agent_id]
        now = time.time()
        recent = sum(1 for t in window if now - t <= 60)
        return {
            "agent_id": agent_id,
            "total_runs": self._total_runs[agent_id],
            "runs_in_last_minute": recent,
            "limits": self.config.model_dump(),
        }


# Single shared enforcer instance for the whole app.
enforcer = GuardrailEnforcer()
