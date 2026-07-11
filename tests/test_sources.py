import sqlite3
import threading

import pytest

from kb.sources import CollectionConflictError, CollectionValidationError, SourceRecord, SourceStore


def make_record(**over):
    base = dict(
        type="youtube",
        url="https://youtu.be/abc12345678",
        video_id="abc12345678",
        locator=None,
        vault="privat",
        raw_md_path="raw/privat/x.md",
    )
    base.update(over)
    return SourceRecord.new(**base)


def test_new_record_gets_id_and_fetched_at():
    r = make_record()
    assert len(r.id) == 36  # uuid4
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
    for needle in (
        "source_id:",
        "type: youtube",
        "video_id: abc12345678",
        "locator: '00:12:30'",
        "vault: privat",
    ):
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
    assert store.find_by_hash("h1", "business-ki") is None  # anderer Vault -> kein Treffer
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


def test_collection_labels_are_normalized_and_vault_scoped(tmp_path):
    store = SourceStore(tmp_path / "sources.db")
    first = store.create_collection("privat", "  Projekt\u00a0 A  ")
    assert first.label == "Projekt A"
    assert first.node_set_key == f"collection:{first.id}"
    with pytest.raises(CollectionConflictError):
        store.create_collection("privat", "projekt a")
    assert store.create_collection("business-ki", "PROJEKT A").vault == "business-ki"


@pytest.mark.parametrize("label", ["", " ", "x" * 65, "Hallo\nWelt", "\x00"])
def test_collection_label_validation(tmp_path, label):
    store = SourceStore(tmp_path / "sources.db")
    with pytest.raises(CollectionValidationError):
        store.create_collection("privat", label)


def test_collection_lifecycle_preserves_identity_and_assignments(tmp_path):
    store = SourceStore(tmp_path / "sources.db")
    source = make_record()
    store.insert(source)
    collection = store.create_collection("privat", "Projekt A")
    store.replace_desired_collections(source.id, [collection.id])

    renamed = store.rename_collection("privat", collection.id, "Projekt B")
    assert renamed.id == collection.id
    assert store.desired_collection_ids(source.id) == [collection.id]
    store.archive_collection("privat", collection.id)
    assert store.list_collections("privat") == []
    assert store.list_collections("privat", include_archived=True)[0].state == "archived"
    assert store.desired_collection_ids(source.id) == [collection.id]
    store.restore_collection("privat", collection.id)
    assert store.list_collections("privat")[0].label == "Projekt B"
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute(
            "UPDATE collections SET node_set_key='collection:changed' WHERE id=?",
            (collection.id,),
        )


def test_assignment_is_atomic_and_creates_unique_revision_outbox(tmp_path):
    store = SourceStore(tmp_path / "sources.db")
    source = make_record()
    store.insert(source)
    a = store.create_collection("privat", "A")
    b = store.create_collection("privat", "B")

    state = store.replace_desired_collections(source.id, [b.id, a.id])
    assert (state.collection_revision, state.indexed_collection_revision) == (1, 0)
    assert state.collection_sync_status == "pending"
    assert store.desired_collection_ids(source.id) == [b.id, a.id]
    assert store.indexed_collection_ids(source.id) == []
    assert [(event.source_id, event.revision) for event in store.pending_reindex_events()] == [
        (source.id, 1)
    ]
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute(
            "INSERT INTO collection_reindex_outbox(source_id,revision,created_at) VALUES(?,?,?)",
            (source.id, 1, "now"),
        )


def test_assignments_reject_archived_cross_vault_too_many_and_direct_sql(tmp_path):
    store = SourceStore(tmp_path / "sources.db")
    source = make_record()
    store.insert(source)
    local = store.create_collection("privat", "Lokal")
    foreign = store.create_collection("business-ki", "Fremd")
    store.archive_collection("privat", local.id)
    with pytest.raises(CollectionValidationError):
        store.replace_desired_collections(source.id, [local.id])
    with pytest.raises(CollectionValidationError):
        store.replace_desired_collections(source.id, [foreign.id])
    many = [store.create_collection("privat", f"C{i}").id for i in range(11)]
    with pytest.raises(CollectionValidationError):
        store.replace_desired_collections(source.id, many)
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute(
            "INSERT INTO source_desired_collections"
            "(source_id,collection_id,display_order) VALUES(?,?,0)",
            (source.id, foreign.id),
        )
    with pytest.raises(sqlite3.IntegrityError):
        with store.conn:
            store.conn.executemany(
                "INSERT INTO source_desired_collections"
                "(source_id,collection_id,display_order) VALUES(?,?,?)",
                [(source.id, collection_id, index) for index, collection_id in enumerate(many)],
            )


def test_revision_guarded_completion_and_stale_failure_are_safe(tmp_path):
    store = SourceStore(tmp_path / "sources.db")
    source = make_record()
    store.insert(source)
    a = store.create_collection("privat", "A")
    b = store.create_collection("privat", "B")
    store.replace_desired_collections(source.id, [a.id])
    store.replace_desired_collections(source.id, [b.id])

    assert store.complete_collection_reindex(source.id, 1) is False
    assert store.fail_collection_reindex(source.id, 1, "alt") is False
    state = store.get_collection_sync(source.id)
    assert state.collection_revision == 2
    assert state.indexed_collection_revision == 0
    assert state.collection_sync_status == "pending"
    assert store.complete_collection_reindex(source.id, 2) is True
    assert store.indexed_collection_ids(source.id) == [b.id]
    assert store.get_collection_sync(source.id).collection_sync_status == "synced"


def test_invalid_replacement_rolls_back_desired_state_revision_and_outbox(tmp_path):
    store = SourceStore(tmp_path / "sources.db")
    source = make_record()
    store.insert(source)
    local = store.create_collection("privat", "Lokal")
    foreign = store.create_collection("business-ki", "Fremd")
    store.replace_desired_collections(source.id, [local.id])
    before_events = store.pending_reindex_events()

    with pytest.raises(CollectionValidationError):
        store.replace_desired_collections(source.id, [foreign.id])

    assert store.desired_collection_ids(source.id) == [local.id]
    assert store.get_collection_sync(source.id).collection_revision == 1
    assert store.pending_reindex_events() == before_events


def test_stale_completion_does_not_clear_newer_failure(tmp_path):
    store = SourceStore(tmp_path / "sources.db")
    source = make_record()
    store.insert(source)
    collection = store.create_collection("privat", "A")
    store.replace_desired_collections(source.id, [collection.id])
    store.replace_desired_collections(source.id, [])
    assert store.fail_collection_reindex(source.id, 2, "cognee nicht erreichbar") is True

    assert store.complete_collection_reindex(source.id, 1) is False
    state = store.get_collection_sync(source.id)
    assert state.collection_sync_status == "failed"
    assert state.collection_sync_error == "cognee nicht erreichbar"
    assert state.indexed_collection_revision == 0


def test_active_collection_limit_is_enforced_on_create_and_restore(tmp_path):
    store = SourceStore(tmp_path / "sources.db")
    collections = [store.create_collection("privat", f"C{i}") for i in range(100)]
    with pytest.raises(CollectionValidationError):
        store.create_collection("privat", "Zu viel")
    store.archive_collection("privat", collections[0].id)
    replacement = store.create_collection("privat", "Ersatz")
    assert replacement.state == "active"
    with pytest.raises(CollectionValidationError):
        store.restore_collection("privat", collections[0].id)


def test_legacy_sources_start_synced_and_unassigned(tmp_path):
    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE sources (
            id TEXT PRIMARY KEY, type TEXT NOT NULL, url TEXT, video_id TEXT,
            locator TEXT, fetched_at TEXT NOT NULL, vault TEXT NOT NULL,
            raw_md_path TEXT NOT NULL
        );
        INSERT INTO sources VALUES
            ('legacy','web','https://example.com',NULL,NULL,'2020-01-01T00:00:00Z',
             'privat','raw/privat/legacy.md');
    """)
    conn.close()
    store = SourceStore(db_path)
    state = store.get_collection_sync("legacy")
    assert (state.collection_revision, state.indexed_collection_revision) == (0, 0)
    assert state.collection_sync_status == "synced"
    assert store.desired_collection_ids("legacy") == []
    assert store.pending_reindex_events() == []


def test_concurrent_normalized_label_creation_has_one_winner(tmp_path):
    db_path = tmp_path / "sources.db"
    SourceStore(db_path).close()
    barrier = threading.Barrier(2)
    results = []

    def create(label):
        store = SourceStore(db_path)
        barrier.wait()
        try:
            store.create_collection("privat", label)
            results.append("created")
        except CollectionConflictError:
            results.append("conflict")
        finally:
            store.close()

    threads = [
        threading.Thread(target=create, args=(label,)) for label in (" Projekt A ", "projekt a")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == ["conflict", "created"]
