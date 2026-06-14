import sqlite3

from kb.sources import SourceRecord, SourceStore


def make_record(**over):
    base = dict(
        type="youtube", url="https://youtu.be/abc12345678", video_id="abc12345678",
        locator=None, vault="privat", raw_md_path="raw/privat/x.md",
    )
    base.update(over)
    return SourceRecord.new(**base)


def test_new_record_gets_id_and_fetched_at():
    r = make_record()
    assert len(r.id) == 36          # uuid4
    assert r.fetched_at.endswith("Z")


def test_roundtrip(tmp_path):
    store = SourceStore(tmp_path / "sources.db")
    r = make_record()
    store.insert(r)
    got = store.get(r.id)
    assert got == r


def test_roundtrip_with_title(tmp_path):
    store = SourceStore(tmp_path / "sources.db")
    r = make_record(title="Mein Titel")
    store.insert(r)
    got = store.get(r.id)
    assert got == r
    assert got.title == "Mein Titel"


def test_migration_adds_title_column(tmp_path):
    """Alte DB ohne title-Spalte wird durch SourceStore.__init__ migriert."""
    db_path = tmp_path / "old.db"
    # Altes Schema ohne title anlegen
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sources (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            url TEXT,
            video_id TEXT,
            locator TEXT,
            fetched_at TEXT NOT NULL,
            vault TEXT NOT NULL,
            raw_md_path TEXT NOT NULL
        );
    """)
    conn.close()
    # SourceStore öffnet und migriert
    store = SourceStore(db_path)
    r = make_record(title="Nach Migration")
    store.insert(r)
    got = store.get(r.id)
    assert got.title == "Nach Migration"


def test_frontmatter_renders_all_fields():
    r = make_record(locator="00:12:30")
    fm = r.frontmatter()
    assert fm.startswith("---\n") and fm.rstrip().endswith("---")
    for needle in ("source_id:", "type: youtube", "video_id: abc12345678",
                   "locator: '00:12:30'", "vault: privat"):
        assert needle in fm


def test_content_hash_roundtrip(tmp_path):
    store = SourceStore(tmp_path / "sources.db")
    r = make_record(content_hash="deadbeef")
    store.insert(r)
    assert store.get(r.id).content_hash == "deadbeef"


def test_find_by_hash_is_vault_scoped(tmp_path):
    store = SourceStore(tmp_path / "sources.db")
    r = make_record(content_hash="h1", vault="privat")
    store.insert(r)
    assert store.find_by_hash("h1", "privat").id == r.id
    assert store.find_by_hash("h1", "business-ki") is None   # anderer Vault -> kein Treffer
    assert store.find_by_hash("unbekannt", "privat") is None


def test_migration_adds_content_hash_column(tmp_path):
    """Alte DB ohne title/content_hash wird durch SourceStore.__init__ migriert."""
    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sources (
            id TEXT PRIMARY KEY, type TEXT NOT NULL, url TEXT, video_id TEXT,
            locator TEXT, fetched_at TEXT NOT NULL, vault TEXT NOT NULL,
            raw_md_path TEXT NOT NULL
        );
    """)
    conn.close()
    store = SourceStore(db_path)  # migriert title + content_hash
    r = make_record(content_hash="xyz")
    store.insert(r)
    assert store.get(r.id).content_hash == "xyz"
