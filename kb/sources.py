import json
import sqlite3
import unicodedata
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


class _QuotingDumper(yaml.SafeDumper):
    """Quotet Strings mit Doppelpunkten explizit — PyYAMLs Sexagesimal-Resolver
    verlangt eine führende [1-9], daher bliebe z. B. '00:12:30' unquoted und
    der Frontmatter-Roundtrip wäre mehrdeutig. Nicht zu safe_dump vereinfachen!"""


def _str_representer(dumper: _QuotingDumper, data: str) -> yaml.Node:
    if ":" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="'")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


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
    content_hash TEXT,
    collection_revision INTEGER NOT NULL DEFAULT 0,
    indexed_collection_revision INTEGER NOT NULL DEFAULT 0,
    collection_sync_status TEXT NOT NULL DEFAULT 'synced'
        CHECK (collection_sync_status IN ('pending','synced','failed')),
    collection_sync_error TEXT,
    collection_sync_updated_at TEXT,
    cognee_dataset_id TEXT,
    cognee_data_id TEXT,
    cognee_provenance_node_sets TEXT
);

CREATE TABLE IF NOT EXISTS collections (
    id TEXT PRIMARY KEY,
    vault TEXT NOT NULL,
    label TEXT NOT NULL,
    normalized_label TEXT NOT NULL,
    node_set_key TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active','archived')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(vault, normalized_label)
);

CREATE TABLE IF NOT EXISTS source_desired_collections (
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE RESTRICT,
    display_order INTEGER NOT NULL,
    PRIMARY KEY(source_id, collection_id),
    UNIQUE(source_id, display_order)
);

CREATE TABLE IF NOT EXISTS source_indexed_collections (
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE RESTRICT,
    display_order INTEGER NOT NULL,
    PRIMARY KEY(source_id, collection_id),
    UNIQUE(source_id, display_order)
);

CREATE TABLE IF NOT EXISTS collection_reindex_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    delivered_at TEXT,
    UNIQUE(source_id, revision)
);

CREATE TRIGGER IF NOT EXISTS desired_collection_same_vault
BEFORE INSERT ON source_desired_collections
WHEN (SELECT vault FROM sources WHERE id=NEW.source_id)
     != (SELECT vault FROM collections WHERE id=NEW.collection_id)
BEGIN SELECT RAISE(ABORT, 'source and collection vault differ'); END;

CREATE TRIGGER IF NOT EXISTS indexed_collection_same_vault
BEFORE INSERT ON source_indexed_collections
WHEN (SELECT vault FROM sources WHERE id=NEW.source_id)
     != (SELECT vault FROM collections WHERE id=NEW.collection_id)
BEGIN SELECT RAISE(ABORT, 'source and collection vault differ'); END;

CREATE TRIGGER IF NOT EXISTS max_active_collections_per_vault
BEFORE INSERT ON collections
WHEN NEW.state='active' AND
     (SELECT COUNT(*) FROM collections WHERE vault=NEW.vault AND state='active') >= 100
BEGIN SELECT RAISE(ABORT, 'maximum active collections reached'); END;

CREATE TRIGGER IF NOT EXISTS max_active_collections_on_restore
BEFORE UPDATE OF state ON collections
WHEN OLD.state='archived' AND NEW.state='active' AND
     (SELECT COUNT(*) FROM collections WHERE vault=NEW.vault AND state='active') >= 100
BEGIN SELECT RAISE(ABORT, 'maximum active collections reached'); END;

CREATE TRIGGER IF NOT EXISTS immutable_collection_identity
BEFORE UPDATE OF id, vault, node_set_key ON collections
WHEN NEW.id != OLD.id OR NEW.vault != OLD.vault OR NEW.node_set_key != OLD.node_set_key
BEGIN SELECT RAISE(ABORT, 'collection identity is immutable'); END;

CREATE TRIGGER IF NOT EXISTS max_desired_collections_per_source
BEFORE INSERT ON source_desired_collections
WHEN (SELECT COUNT(*) FROM source_desired_collections WHERE source_id=NEW.source_id) >= 10
BEGIN SELECT RAISE(ABORT, 'maximum source collections reached'); END;

CREATE TRIGGER IF NOT EXISTS max_indexed_collections_per_source
BEFORE INSERT ON source_indexed_collections
WHEN (SELECT COUNT(*) FROM source_indexed_collections WHERE source_id=NEW.source_id) >= 10
BEGIN SELECT RAISE(ABORT, 'maximum source collections reached'); END;
"""


class CollectionValidationError(ValueError):
    """Eine Collection-Anfrage verletzt eine fachliche Invariante."""


class CollectionConflictError(CollectionValidationError):
    """Ein normalisierter Collection-Name existiert im Vault bereits."""


@dataclass(frozen=True)
class CollectionRecord:
    id: str
    vault: str
    label: str
    normalized_label: str
    node_set_key: str
    state: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class CollectionSync:
    source_id: str
    collection_revision: int
    indexed_collection_revision: int
    collection_sync_status: str
    collection_sync_error: str | None
    collection_sync_updated_at: str | None


@dataclass(frozen=True)
class ReindexOutboxEvent:
    id: int
    source_id: str
    revision: int
    created_at: str
    delivered_at: str | None


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_collection_label(label: str) -> tuple[str, str]:
    if not isinstance(label, str) or any(unicodedata.category(char) == "Cc" for char in label):
        raise CollectionValidationError("Collection-Name enthält ungültige Steuerzeichen")
    display = " ".join(unicodedata.normalize("NFKC", label).split())
    if not 1 <= len(display) <= 64:
        raise CollectionValidationError("Collection-Name muss 1 bis 64 Zeichen lang sein")
    return display, display.casefold()


@dataclass(frozen=True)
class SourceRecord:
    id: str
    type: str  # youtube | web | snippet | file
    url: str | None
    video_id: str | None
    locator: str | None
    fetched_at: str  # ISO-8601 UTC
    vault: str
    raw_md_path: str
    title: str | None = None  # Optional: frozen dataclass verlangt Default-Felder zuletzt
    content_hash: str | None = None  # sha256 des Bodys — für Ingest-Dedup pro Vault

    @classmethod
    def new(cls, **kwargs: Any) -> "SourceRecord":
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        return cls(id=str(uuid.uuid4()), fetched_at=now, **kwargs)

    def frontmatter(self) -> str:
        data = asdict(self)
        data["source_id"] = data.pop("id")
        body = yaml.dump(
            data,
            Dumper=_QuotingDumper,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )
        return f"---\n{body}---\n"


class SourceStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA foreign_keys=ON")
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
        migrations = (
            ("collection_revision", "INTEGER NOT NULL DEFAULT 0"),
            ("indexed_collection_revision", "INTEGER NOT NULL DEFAULT 0"),
            ("collection_sync_status", "TEXT NOT NULL DEFAULT 'synced'"),
            ("collection_sync_error", "TEXT"),
            ("collection_sync_updated_at", "TEXT"),
            ("cognee_dataset_id", "TEXT"),
            ("cognee_data_id", "TEXT"),
            ("cognee_provenance_node_sets", "TEXT"),
        )
        for col, definition in migrations:
            try:
                self.conn.execute(f"ALTER TABLE sources ADD COLUMN {col} {definition}")
                self.conn.commit()
            except sqlite3.OperationalError:
                pass

    def close(self) -> None:
        """Schließt die Connection (sauberer Shutdown des Instance Service)."""
        self.conn.close()

    def insert(self, r: SourceRecord) -> None:
        # Explizite Spaltennamen notwendig: ALTER TABLE hängt title ans Ende,
        # Positions-INSERT würde nach Schema-Erweiterung falsch greifen.
        self.conn.execute(
            "INSERT INTO sources "
            "(id,type,url,video_id,locator,fetched_at,vault,raw_md_path,title,content_hash) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                r.id,
                r.type,
                r.url,
                r.video_id,
                r.locator,
                r.fetched_at,
                r.vault,
                r.raw_md_path,
                r.title,
                r.content_hash,
            ),
        )
        self.conn.commit()

    _COLS = "id,type,url,video_id,locator,fetched_at,vault,raw_md_path,title,content_hash"

    def get(self, source_id: str) -> SourceRecord | None:
        row = self.conn.execute(
            f"SELECT {self._COLS} FROM sources WHERE id=?", (source_id,)
        ).fetchone()
        return SourceRecord(*row) if row else None

    def find_by_hash(self, content_hash: str, vault: str) -> SourceRecord | None:
        """Erste Quelle mit gleichem Body-Hash im selben Vault — für Ingest-Dedup."""
        row = self.conn.execute(
            f"SELECT {self._COLS} FROM sources WHERE content_hash=? AND vault=? LIMIT 1",
            (content_hash, vault),
        ).fetchone()
        return SourceRecord(*row) if row else None

    def list_by_vault(self, vault: str, limit: int = 50, offset: int = 0) -> list[SourceRecord]:
        """Quellen eines Vaults, neueste zuerst (für die Management-Ansicht)."""
        rows = self.conn.execute(
            f"SELECT {self._COLS} FROM sources WHERE vault=? "
            "ORDER BY fetched_at DESC LIMIT ? OFFSET ?",
            (vault, limit, offset),
        ).fetchall()
        return [SourceRecord(*row) for row in rows]

    def delete(self, source_id: str) -> None:
        """Löscht einen Source-Record (Cleanup bei fehlgeschlagenem Ingest)."""
        self.conn.execute("DELETE FROM sources WHERE id=?", (source_id,))
        self.conn.commit()

    _COLLECTION_COLS = "id,vault,label,normalized_label,node_set_key,state,created_at,updated_at"

    def create_collection(self, vault: str, label: str) -> CollectionRecord:
        display, normalized = _normalize_collection_label(label)
        collection_id = str(uuid.uuid4())
        now = _now()
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO collections "
                    "(id,vault,label,normalized_label,node_set_key,state,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,'active',?,?)",
                    (
                        collection_id,
                        vault,
                        display,
                        normalized,
                        f"collection:{collection_id}",
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if "collections.vault, collections.normalized_label" in str(exc):
                raise CollectionConflictError("Collection-Name existiert bereits") from exc
            if "maximum active collections" in str(exc):
                raise CollectionValidationError(
                    "Ein Vault erlaubt höchstens 100 aktive Collections"
                ) from exc
            raise
        return self.get_collection(vault, collection_id)

    def get_collection(self, vault: str, collection_id: str) -> CollectionRecord:
        row = self.conn.execute(
            f"SELECT {self._COLLECTION_COLS} FROM collections WHERE id=? AND vault=?",
            (collection_id, vault),
        ).fetchone()
        if row is None:
            raise CollectionValidationError(
                "Collection gehört nicht zum Vault oder existiert nicht"
            )
        return CollectionRecord(*row)

    def list_collections(
        self, vault: str, *, include_archived: bool = False
    ) -> list[CollectionRecord]:
        state_filter = "" if include_archived else " AND state='active'"
        rows = self.conn.execute(
            f"SELECT {self._COLLECTION_COLS} FROM collections "
            f"WHERE vault=?{state_filter} ORDER BY label COLLATE NOCASE, id",
            (vault,),
        ).fetchall()
        return [CollectionRecord(*row) for row in rows]

    def rename_collection(self, vault: str, collection_id: str, label: str) -> CollectionRecord:
        self.get_collection(vault, collection_id)
        display, normalized = _normalize_collection_label(label)
        try:
            with self.conn:
                self.conn.execute(
                    "UPDATE collections SET label=?,normalized_label=?,updated_at=? "
                    "WHERE id=? AND vault=?",
                    (display, normalized, _now(), collection_id, vault),
                )
        except sqlite3.IntegrityError as exc:
            if "collections.vault, collections.normalized_label" in str(exc):
                raise CollectionConflictError("Collection-Name existiert bereits") from exc
            raise
        return self.get_collection(vault, collection_id)

    def _set_collection_state(self, vault: str, collection_id: str, state: str) -> CollectionRecord:
        self.get_collection(vault, collection_id)
        try:
            with self.conn:
                self.conn.execute(
                    "UPDATE collections SET state=?,updated_at=? WHERE id=? AND vault=?",
                    (state, _now(), collection_id, vault),
                )
        except sqlite3.IntegrityError as exc:
            if "maximum active collections" in str(exc):
                raise CollectionValidationError(
                    "Ein Vault erlaubt höchstens 100 aktive Collections"
                ) from exc
            raise
        return self.get_collection(vault, collection_id)

    def archive_collection(self, vault: str, collection_id: str) -> CollectionRecord:
        return self._set_collection_state(vault, collection_id, "archived")

    def restore_collection(self, vault: str, collection_id: str) -> CollectionRecord:
        return self._set_collection_state(vault, collection_id, "active")

    def _collection_ids(self, table: str, source_id: str) -> list[str]:
        rows = self.conn.execute(
            f"SELECT collection_id FROM {table} WHERE source_id=? ORDER BY display_order",
            (source_id,),
        ).fetchall()
        return [row[0] for row in rows]

    def desired_collection_ids(self, source_id: str) -> list[str]:
        return self._collection_ids("source_desired_collections", source_id)

    def indexed_collection_ids(self, source_id: str) -> list[str]:
        return self._collection_ids("source_indexed_collections", source_id)

    def collection_node_set_keys(self, source_id: str, *, desired: bool = True) -> list[str]:
        table = "source_desired_collections" if desired else "source_indexed_collections"
        rows = self.conn.execute(
            f"SELECT c.node_set_key FROM {table} a JOIN collections c "
            "ON c.id=a.collection_id WHERE a.source_id=? ORDER BY a.display_order",
            (source_id,),
        ).fetchall()
        return [row[0] for row in rows]

    def initialize_collections(
        self,
        source_id: str,
        collection_ids: list[str],
        *,
        cognee_dataset_id: str | None,
        cognee_data_id: str | None,
        provenance_node_sets: list[str] | None = None,
    ) -> None:
        """Publiziert initiale Membership erst nach erfolgreichem Cognify."""
        if len(collection_ids) > 10 or len(set(collection_ids)) != len(collection_ids):
            raise CollectionValidationError(
                "Eine Quelle erlaubt höchstens 10 eindeutige Collections"
            )
        source = self.get(source_id)
        if source is None:
            raise CollectionValidationError("Quelle existiert nicht")
        self.validate_collection_ids(source.vault, collection_ids)
        with self.conn:
            for table in ("source_desired_collections", "source_indexed_collections"):
                self.conn.executemany(
                    f"INSERT INTO {table}(source_id,collection_id,display_order) VALUES(?,?,?)",
                    [(source_id, cid, index) for index, cid in enumerate(collection_ids)],
                )
            self.conn.execute(
                "UPDATE sources SET cognee_dataset_id=?,cognee_data_id=?,"
                "cognee_provenance_node_sets=?,"
                "collection_sync_status='synced',collection_sync_updated_at=? WHERE id=?",
                (
                    cognee_dataset_id,
                    cognee_data_id,
                    json.dumps(provenance_node_sets or [source_id]),
                    _now(),
                    source_id,
                ),
            )

    def validate_collection_ids(self, vault: str, collection_ids: list[str]) -> None:
        if len(collection_ids) > 10 or len(set(collection_ids)) != len(collection_ids):
            raise CollectionValidationError(
                "Eine Quelle erlaubt höchstens 10 eindeutige Collections"
            )
        if not collection_ids:
            return
        placeholders = ",".join("?" for _ in collection_ids)
        rows = self.conn.execute(
            "SELECT id FROM collections WHERE vault=? AND state='active' "
            f"AND id IN ({placeholders})",
            (vault, *collection_ids),
        ).fetchall()
        if {row[0] for row in rows} != set(collection_ids):
            raise CollectionValidationError(
                "Collections müssen aktiv sein und zum Vault der Quelle gehören"
            )

    def retrieval_scope(
        self, vault: str, collection_ids: list[str] | None
    ) -> tuple[list[str], set[str]]:
        """Löst Query-Collections atomar in NodeSets und sichere Quellen auf."""
        if collection_ids:
            self.validate_collection_ids(vault, collection_ids)
            placeholders = ",".join("?" for _ in collection_ids)
            collections = self.conn.execute(
                "SELECT id,node_set_key FROM collections WHERE vault=? AND state='active' "
                f"AND id IN ({placeholders})",
                (vault, *collection_ids),
            ).fetchall()
            keys = {row[0]: row[1] for row in collections}
            rows = self.conn.execute(
                "SELECT DISTINCT s.id FROM sources s "
                "JOIN source_indexed_collections i ON i.source_id=s.id "
                "JOIN source_desired_collections d ON d.source_id=s.id "
                "AND d.collection_id=i.collection_id "
                f"WHERE s.vault=? AND i.collection_id IN ({placeholders})",
                (vault, *collection_ids),
            ).fetchall()
            return [keys[cid] for cid in collection_ids], {row[0] for row in rows}
        rows = self.conn.execute("SELECT id FROM sources WHERE vault=?", (vault,)).fetchall()
        return [], {row[0] for row in rows}

    def cognee_ids(self, source_id: str) -> tuple[str | None, str | None]:
        row = self.conn.execute(
            "SELECT cognee_dataset_id,cognee_data_id FROM sources WHERE id=?", (source_id,)
        ).fetchone()
        if row is None:
            raise CollectionValidationError("Quelle existiert nicht")
        return row[0], row[1]

    def provenance_node_sets(self, source_id: str) -> list[str]:
        row = self.conn.execute(
            "SELECT cognee_provenance_node_sets FROM sources WHERE id=?", (source_id,)
        ).fetchone()
        if row is None:
            raise CollectionValidationError("Quelle existiert nicht")
        if not row[0]:
            return [source_id]
        values = json.loads(row[0])
        return [value for value in values if isinstance(value, str)] or [source_id]

    def set_cognee_ids(self, source_id: str, dataset_id: str | None, data_id: str | None) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE sources SET cognee_dataset_id=?,cognee_data_id=? WHERE id=?",
                (dataset_id, data_id, source_id),
            )

    def get_collection_sync(self, source_id: str) -> CollectionSync:
        row = self.conn.execute(
            "SELECT id,collection_revision,indexed_collection_revision,"
            "collection_sync_status,collection_sync_error,collection_sync_updated_at "
            "FROM sources WHERE id=?",
            (source_id,),
        ).fetchone()
        if row is None:
            raise CollectionValidationError("Quelle existiert nicht")
        return CollectionSync(*row)

    def replace_desired_collections(
        self, source_id: str, collection_ids: list[str]
    ) -> CollectionSync:
        if len(collection_ids) > 10 or len(set(collection_ids)) != len(collection_ids):
            raise CollectionValidationError(
                "Eine Quelle erlaubt höchstens 10 eindeutige Collections"
            )
        now = _now()
        with self.conn:
            source = self.conn.execute(
                "SELECT vault,collection_revision FROM sources WHERE id=?", (source_id,)
            ).fetchone()
            if source is None:
                raise CollectionValidationError("Quelle existiert nicht")
            vault, revision = source
            self.validate_collection_ids(vault, collection_ids)
            new_revision = revision + 1
            self.conn.execute(
                "DELETE FROM source_desired_collections WHERE source_id=?", (source_id,)
            )
            self.conn.executemany(
                "INSERT INTO source_desired_collections "
                "(source_id,collection_id,display_order) VALUES(?,?,?)",
                [(source_id, cid, index) for index, cid in enumerate(collection_ids)],
            )
            self.conn.execute(
                "UPDATE sources SET collection_revision=?,collection_sync_status='pending',"
                "collection_sync_error=NULL,collection_sync_updated_at=? WHERE id=?",
                (new_revision, now, source_id),
            )
            self.conn.execute(
                "INSERT INTO collection_reindex_outbox(source_id,revision,created_at) "
                "VALUES(?,?,?)",
                (source_id, new_revision, now),
            )
        return self.get_collection_sync(source_id)

    def complete_collection_reindex(self, source_id: str, revision: int) -> bool:
        now = _now()
        with self.conn:
            current = self.conn.execute(
                "SELECT collection_revision FROM sources WHERE id=?", (source_id,)
            ).fetchone()
            if current is None or current[0] != revision:
                return False
            self.conn.execute(
                "DELETE FROM source_indexed_collections WHERE source_id=?", (source_id,)
            )
            self.conn.execute(
                "INSERT INTO source_indexed_collections(source_id,collection_id,display_order) "
                "SELECT source_id,collection_id,display_order FROM source_desired_collections "
                "WHERE source_id=?",
                (source_id,),
            )
            self.conn.execute(
                "UPDATE sources SET indexed_collection_revision=?,"
                "collection_sync_status='synced',collection_sync_error=NULL,"
                "collection_sync_updated_at=? WHERE id=? AND collection_revision=?",
                (revision, now, source_id, revision),
            )
        return True

    def fail_collection_reindex(self, source_id: str, revision: int, error: str) -> bool:
        with self.conn:
            cursor = self.conn.execute(
                "UPDATE sources SET collection_sync_status='failed',"
                "collection_sync_error=?,collection_sync_updated_at=? "
                "WHERE id=? AND collection_revision=?",
                (error, _now(), source_id, revision),
            )
        return cursor.rowcount == 1

    def pending_reindex_events(self) -> list[ReindexOutboxEvent]:
        rows = self.conn.execute(
            "SELECT id,source_id,revision,created_at,delivered_at "
            "FROM collection_reindex_outbox WHERE delivered_at IS NULL ORDER BY id"
        ).fetchall()
        return [ReindexOutboxEvent(*row) for row in rows]

    def mark_reindex_event_delivered(self, event_id: int) -> bool:
        with self.conn:
            cursor = self.conn.execute(
                "UPDATE collection_reindex_outbox SET delivered_at=? "
                "WHERE id=? AND delivered_at IS NULL",
                (_now(), event_id),
            )
        return cursor.rowcount == 1

    def dispatch_reindex_events(self, queue: Any) -> int:
        """Überträgt die Outbox idempotent in queue.db; Crash-Lücken bleiben retrybar."""
        delivered = 0
        for event in self.pending_reindex_events():
            source = self.get(event.source_id)
            if source is None:
                continue
            queue.enqueue_reindex(source.vault, event.source_id, event.revision)
            if self.mark_reindex_event_delivered(event.id):
                delivered += 1
        return delivered
