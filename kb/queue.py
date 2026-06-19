import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vault TEXT NOT NULL,
    kind TEXT NOT NULL,           -- youtube | web | snippet | file
    payload TEXT NOT NULL,        -- JSON
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
"""


@dataclass(frozen=True)
class Job:
    id: int
    vault: str
    kind: str
    payload: dict[str, Any]


class JobQueue:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    def enqueue(self, vault: str, kind: str, payload: dict[str, Any]) -> int:
        cur = self.conn.execute(
            "INSERT INTO jobs (vault, kind, payload) VALUES (?,?,?)",
            (vault, kind, json.dumps(payload)),
        )
        self.conn.commit()
        assert cur.lastrowid is not None  # INSERT → immer eine ID
        return cur.lastrowid

    def claim_next(self) -> Job | None:
        row = self.conn.execute(
            "UPDATE jobs SET status='running' WHERE id = ("
            "  SELECT id FROM jobs WHERE status='pending' ORDER BY id LIMIT 1"
            ") RETURNING id, vault, kind, payload"
        ).fetchone()
        self.conn.commit()
        if row is None:
            return None
        return Job(row[0], row[1], row[2], json.loads(row[3]))

    def mark_done(self, job_id: int) -> None:
        self.conn.execute("UPDATE jobs SET status='done' WHERE id=?", (job_id,))
        self.conn.commit()

    def mark_failed(self, job_id: int, error: str) -> None:
        self.conn.execute("UPDATE jobs SET status='failed', error=? WHERE id=?", (error, job_id))
        self.conn.commit()

    def recover_stale(self) -> int:
        """Setzt verwaiste 'running'-Jobs (z. B. nach Worker-Crash) auf 'pending' zurück."""
        cur = self.conn.execute(
            "UPDATE jobs SET status='pending', error=NULL WHERE status='running'"
        )
        self.conn.commit()
        return cur.rowcount

    def info(self, job_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT id, vault, kind, status, error, created_at FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "vault": row[1],
            "kind": row[2],
            "status": row[3],
            "error": row[4],
            "created_at": row[5],
        }

    def status(self, job_id: int) -> str | None:
        row = self.conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        return row[0] if row else None

    def counts(self) -> dict[str, int]:
        """Job-Anzahl je Status; nicht vorkommende Stati = 0 (für /health)."""
        result = {s: 0 for s in ("pending", "running", "done", "failed")}
        for status, n in self.conn.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status"):
            result[status] = n
        return result

    def node_sets(self, vault: str) -> list[str]:
        """Explizit gesetzte node_set-Werte eines Vaults für UI-Vorschläge."""
        result: set[str] = set()
        for (payload_raw,) in self.conn.execute("SELECT payload FROM jobs WHERE vault=?", (vault,)):
            payload = json.loads(payload_raw)
            value = payload.get("node_set")
            if isinstance(value, str) and value.strip():
                result.add(value.strip())
            elif isinstance(value, list):
                result.update(v.strip() for v in value if isinstance(v, str) and v.strip())
        return sorted(result)
