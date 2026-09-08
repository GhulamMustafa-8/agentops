"""
logger.py
---------
Phase 2 — Observability.

Per Constitution Principle #3 (Observable by design): every agent run is
logged — task, result, duration, status, errors. This module persists
that to SQLite (per the tech stack table: "Database (logs/state):
SQLite -> PostgreSQL optional upgrade"), so history survives process
restarts (unlike the in-memory AgentRegistry from Phase 1).

Kept as its own module, independent of BaseAgent/Registry, so it can be
swapped for Postgres later by only touching this file.
"""

import sqlite3
import time
import os
from typing import Optional, List, Dict
from contextlib import contextmanager

DB_PATH = os.getenv("AGENTOPS_DB_PATH", "agentops.db")


class AgentLogger:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id      TEXT PRIMARY KEY,
                    agent_id    TEXT NOT NULL,
                    agent_name  TEXT,
                    task        TEXT,
                    status      TEXT NOT NULL,
                    result      TEXT,
                    error       TEXT,
                    duration_ms INTEGER,
                    timestamp   REAL NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_agent_id ON runs(agent_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status)")

    def log_run(self, run_id: str, agent_id: str, agent_name: str, run_result: dict):
        """
        Persist one run. `run_result` is the dict returned by BaseAgent.run():
        {task, status, result, error, duration_ms}. Never raises — a logging
        failure must not take down the API (fail-safe extends to logging too).
        """
        try:
            with self._get_conn() as conn:
                conn.execute(
                    """INSERT INTO runs
                       (run_id, agent_id, agent_name, task, status, result, error, duration_ms, timestamp)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_id,
                        agent_id,
                        agent_name,
                        run_result.get("task"),
                        run_result.get("status"),
                        run_result.get("result"),
                        run_result.get("error"),
                        run_result.get("duration_ms"),
                        time.time(),
                    ),
                )
        except Exception as e:
            # Swallow logging errors — observability must never crash the run itself.
            print(f"[AgentLogger] WARNING: failed to persist run log: {e}")

    def get_logs(self, agent_id: Optional[str] = None, limit: int = 50, offset: int = 0) -> List[Dict]:
        with self._get_conn() as conn:
            if agent_id:
                rows = conn.execute(
                    "SELECT * FROM runs WHERE agent_id = ? ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                    (agent_id, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM runs ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
            return [dict(row) for row in rows]

    def get_last_run(self, agent_id: str) -> Optional[Dict]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE agent_id = ? ORDER BY timestamp DESC LIMIT 1",
                (agent_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_stats(self, agent_id: Optional[str] = None) -> Dict:
        with self._get_conn() as conn:
            where = "WHERE agent_id = ?" if agent_id else ""
            params = (agent_id,) if agent_id else ()

            total = conn.execute(f"SELECT COUNT(*) as c FROM runs {where}", params).fetchone()["c"]
            success = conn.execute(
                f"SELECT COUNT(*) as c FROM runs {where}{' AND' if where else 'WHERE'} status = 'success'",
                params,
            ).fetchone()["c"]
            errors = total - success
            avg_duration = conn.execute(
                f"SELECT AVG(duration_ms) as a FROM runs {where}", params
            ).fetchone()["a"]

            # Per-agent breakdown (only meaningful for the global/all-agents view)
            per_agent = []
            if not agent_id:
                rows = conn.execute("""
                    SELECT agent_id, agent_name,
                           COUNT(*) as total_runs,
                           SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as success_runs,
                           SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) as error_runs,
                           AVG(duration_ms) as avg_duration_ms
                    FROM runs
                    GROUP BY agent_id, agent_name
                """).fetchall()
                per_agent = [dict(row) for row in rows]

            return {
                "total_runs": total,
                "success_runs": success,
                "error_runs": errors,
                "success_rate": round(success / total, 3) if total else None,
                "avg_duration_ms": round(avg_duration, 1) if avg_duration else None,
                "per_agent": per_agent,
            }


# Single shared logger instance for the whole app.
logger = AgentLogger()
