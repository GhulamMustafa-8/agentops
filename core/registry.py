"""
registry.py
-----------
In-memory Agent Registry.

Phase 1 keeps this in-memory (a plain dict) to keep the skeleton simple.
Phase 2 will likely back this with SQLite so agents/logs survive restarts,
per the tech stack table in the Constitution. Kept as its own module now
so that swap is localized to this file later.
"""

from typing import Dict, List, Optional
from agents.base_agent import BaseAgent


class AgentRegistry:
    def __init__(self):
        self._agents: Dict[str, BaseAgent] = {}

    def create_agent(self, name: str, role: str, model: str = None, base_url: str = None, backend: str = None) -> BaseAgent:
        agent = BaseAgent(name=name, role=role, model=model, base_url=base_url, backend=backend)
        self._agents[agent.id] = agent
        return agent

    def list_agents(self) -> List[dict]:
        return [agent.to_dict() for agent in self._agents.values()]

    def get_agent(self, agent_id: str) -> Optional[BaseAgent]:
        return self._agents.get(agent_id)

    def delete_agent(self, agent_id: str) -> bool:
        if agent_id in self._agents:
            del self._agents[agent_id]
            return True
        return False

    def count(self) -> int:
        return len(self._agents)


# Single shared registry instance for the whole app (simple singleton
# pattern — fine for Phase 1's in-process, single-worker setup).
registry = AgentRegistry()
