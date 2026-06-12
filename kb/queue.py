import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

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
    payload: dict


class JobQueue:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    def enqueue(self, vault: str, kind: str, payload: dict) -> int:
        cur = self.conn.execute(
            "INSERT INTO jobs (vault, kind, payload) VALUES (?,?,?)",
            (vault, kind, json.dumps(payload)))
        self.conn.commit()
        return cur.lastrowid

    def claim_next(self) -> Job | None:
        row = self.conn.execute(
            "UPDATE jobs SET status='running' WHERE id = ("
            "  SELECT id FROM jobs WHERE status='pending' ORDER BY id LIMIT 1"
            ") RETURNING id, vault, kind, payload").fetchone()
        self.conn.commit()
        if row is None:
            return None
        return Job(row[0], row[1], row[2], json.loads(row[3]))

    def mark_done(self, job_id: int) -> None:
        self.conn.execute("UPDATE jobs SET status='done' WHERE id=?", (job_id,))
        self.conn.commit()

    def mark_failed(self, job_id: int, error: str) -> None:
        self.conn.execute(
            "UPDATE jobs SET status='failed', error=? WHERE id=?", (error, job_id))
        self.conn.commit()

    def recover_stale(self) -> int:
        """Setzt verwaiste 'running'-Jobs (z. B. nach Worker-Crash) auf 'pending' zurück."""
        cur = self.conn.execute(
            "UPDATE jobs SET status='pending', error=NULL WHERE status='running'")
        self.conn.commit()
        return cur.rowcount

    def status(self, job_id: int) -> str | None:
        row = self.conn.execute(
            "SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        return row[0] if row else None
