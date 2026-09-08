"""
message_bus.py
--------------
Phase 5 — Multi-agent communication.

Per Constitution architecture diagram: "Message Bus (Redis queue) —
agent-to-agent comms, optional." Per Principle #2 (Zero-cost by default),
this ships as a pure in-memory queue so the whole system still runs with
ZERO extra infra (no Redis server required) — but the interface
(`send`, `inbox`, `mark_read`) is deliberately identical to what a Redis
-backed version would expose, so swapping the backing store later means
only touching this file, not any caller.

Not thread-pool-safe beyond Python's GIL + a simple lock — fine for a
single-process demo. A Redis upgrade would be needed for true
multi-process/distributed use, which the Constitution marks as optional.
"""

import time
import uuid
import threading
from collections import defaultdict
from typing import List, Dict, Optional


class MessageBus:
    def __init__(self):
        self._lock = threading.Lock()
        self._inboxes: Dict[str, List[dict]] = defaultdict(list)

    def send(self, from_agent_id: str, to_agent_id: str, content: str) -> dict:
        message = {
            "id": str(uuid.uuid4()),
            "from_agent_id": from_agent_id,
            "to_agent_id": to_agent_id,
            "content": content,
            "timestamp": time.time(),
            "read": False,
        }
        with self._lock:
            self._inboxes[to_agent_id].append(message)
        return message

    def inbox(self, agent_id: str, unread_only: bool = False) -> List[dict]:
        with self._lock:
            messages = list(self._inboxes.get(agent_id, []))
        if unread_only:
            messages = [m for m in messages if not m["read"]]
        # Most recent first, matching /logs convention.
        return sorted(messages, key=lambda m: m["timestamp"], reverse=True)

    def mark_read(self, agent_id: str, message_id: Optional[str] = None) -> int:
        """Mark one message (by id) or all messages in an inbox as read.
        Returns the count of messages marked."""
        count = 0
        with self._lock:
            for m in self._inboxes.get(agent_id, []):
                if message_id is None or m["id"] == message_id:
                    if not m["read"]:
                        m["read"] = True
                        count += 1
        return count

    def unread_count(self, agent_id: str) -> int:
        with self._lock:
            return sum(1 for m in self._inboxes.get(agent_id, []) if not m["read"])


# Single shared bus instance for the whole app.
bus = MessageBus()
