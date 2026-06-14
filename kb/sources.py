import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml


class _QuotingDumper(yaml.SafeDumper):
    """Quotet Strings mit Doppelpunkten explizit — PyYAMLs Sexagesimal-Resolver
    verlangt eine führende [1-9], daher bliebe z. B. '00:12:30' unquoted und
    der Frontmatter-Roundtrip wäre mehrdeutig. Nicht zu safe_dump vereinfachen!"""


def _str_representer(dumper, data):
    if ':' in data:
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style="'")
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)


_QuotingDumper.add_representer(str, _str_representer)


SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    url TEXT,
    video_id TEXT,
    locator TEXT,
    fetched_at TEXT NOT NULL,
    vault TEXT NOT NULL,
    raw_md_path TEXT NOT NULL,
    title TEXT,
    content_hash TEXT
);
"""


@dataclass(frozen=True)
class SourceRecord:
    id: str
    type: str          # youtube | web | snippet | file
    url: str | None
    video_id: str | None
    locator: str | None
    fetched_at: str    # ISO-8601 UTC
    vault: str
    raw_md_path: str
    title: str | None = None         # Optional: frozen dataclass verlangt Default-Felder zuletzt
    content_hash: str | None = None  # sha256 des Bodys — für Ingest-Dedup pro Vault

    @classmethod
    def new(cls, **kwargs) -> "SourceRecord":
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return cls(id=str(uuid.uuid4()), fetched_at=now, **kwargs)

    def frontmatter(self) -> str:
        data = asdict(self)
        data["source_id"] = data.pop("id")
        body = yaml.dump(data, Dumper=_QuotingDumper, sort_keys=False, allow_unicode=True,
                         default_flow_style=False)
        return f"---\n{body}---\n"


class SourceStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        # Migration für Bestands-DBs: ALTER schlägt fehl, wenn die Spalte
        # bereits existiert (frische oder schon migrierte DB) — Fehler schlucken.
        for col in ("title", "content_hash"):
            try:
                self.conn.execute(f"ALTER TABLE sources ADD COLUMN {col} TEXT")
                self.conn.commit()
            except sqlite3.OperationalError:
                pass

    def insert(self, r: SourceRecord) -> None:
        # Explizite Spaltennamen notwendig: ALTER TABLE hängt title ans Ende,
        # Positions-INSERT würde nach Schema-Erweiterung falsch greifen.
        self.conn.execute(
            "INSERT INTO sources "
            "(id,type,url,video_id,locator,fetched_at,vault,raw_md_path,title,content_hash) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (r.id, r.type, r.url, r.video_id, r.locator, r.fetched_at,
             r.vault, r.raw_md_path, r.title, r.content_hash),
        )
        self.conn.commit()

    _COLS = "id,type,url,video_id,locator,fetched_at,vault,raw_md_path,title,content_hash"

    def get(self, source_id: str) -> SourceRecord | None:
        row = self.conn.execute(
            f"SELECT {self._COLS} FROM sources WHERE id=?", (source_id,)).fetchone()
        return SourceRecord(*row) if row else None

    def find_by_hash(self, content_hash: str, vault: str) -> SourceRecord | None:
        """Erste Quelle mit gleichem Body-Hash im selben Vault — für Ingest-Dedup."""
        row = self.conn.execute(
            f"SELECT {self._COLS} FROM sources WHERE content_hash=? AND vault=? LIMIT 1",
            (content_hash, vault)).fetchone()
        return SourceRecord(*row) if row else None
