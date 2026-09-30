import asyncio
import hashlib
import logging
import uuid
from pathlib import Path
from unittest.mock import ANY, AsyncMock, patch

import pytest

from kb.config import Vault
from kb.fetch_youtube import FetchedDoc
from kb.queue import JobQueue
from kb.sources import SourceRecord, SourceStore
from kb.uploads import reconcile_orphans, upload_dir
from kb.worker import process_one, process_one_async, run_forever_async


def make_vault(tmp_path) -> Vault:
    return Vault(name="privat", instance="local", dataset="privat", raw_dir=tmp_path / "raw")


def test_process_one_snippet_full_chain(tmp_path):
    q = JobQueue(tmp_path / "q.db")
    store = SourceStore(tmp_path / "s.db")
    jid = q.enqueue("privat", "snippet", {"text": "Wichtiger Gedanke.", "title": "Notiz"})
    ingest_mock = AsyncMock()
    with (
        patch("kb.worker.get_vault", return_value=make_vault(tmp_path)),
        patch("kb.cognee_io.ingest", ingest_mock),
    ):
        worked = process_one(instance=None, q=q, store=store)
    assert worked is True
    # Rohdatei existiert und enthält Frontmatter + Text
    files = list((tmp_path / "raw").glob("*.md"))
    assert len(files) == 1
    assert "Wichtiger Gedanke." in files[0].read_text()
    # Source-Record zeigt auf die Datei
    row = store.conn.execute("SELECT raw_md_path, vault, type FROM sources").fetchone()
    assert row is not None
    assert row[0] == str(files[0])
    assert row[1] == "privat"
    assert row[2] == "snippet"
    # Ingest mit korrekten Argumenten aufgerufen (node_set == record.id per Stufe 1.5)
    record_id = store.conn.execute("SELECT id FROM sources").fetchone()[0]
    ingest_mock.assert_awaited_once_with(None, files[0], "privat", node_sets=[record_id])
    # Job ist done
    assert q.status(jid) == "done"
    assert q.claim_next() is None


def test_process_one_marks_failed_on_fetch_error(tmp_path):
    q = JobQueue(tmp_path / "q.db")
    store = SourceStore(tmp_path / "s.db")
    jid = q.enqueue("privat", "web", {"url": "https://example.com/down"})
    with (
        patch("kb.worker.get_vault", return_value=make_vault(tmp_path)),
        patch("kb.fetch_web.fetch", side_effect=RuntimeError("offline")),
    ):
        worked = process_one(instance=None, q=q, store=store)
    assert worked is True
    assert q.status(jid) == "failed"


def test_process_one_reuses_given_loop(tmp_path):
    q = JobQueue(tmp_path / "q.db")
    store = SourceStore(tmp_path / "s.db")
    j1 = q.enqueue("privat", "snippet", {"text": "Erster.", "title": "Eins"})
    j2 = q.enqueue("privat", "snippet", {"text": "Zweiter.", "title": "Zwei"})
    ingest_mock = AsyncMock()
    loop = asyncio.new_event_loop()
    try:
        with (
            patch("kb.worker.get_vault", return_value=make_vault(tmp_path)),
            patch("kb.cognee_io.ingest", ingest_mock),
        ):
            assert process_one(instance=None, q=q, store=store, loop=loop) is True
            assert process_one(instance=None, q=q, store=store, loop=loop) is True
    finally:
        loop.close()
    # Beide Jobs liefen ohne Fehler auf EINEM Loop
    assert q.status(j1) == "done"
    assert q.status(j2) == "done"
    assert ingest_mock.await_count == 2


def test_process_one_returns_false_on_empty_queue(tmp_path):
    q = JobQueue(tmp_path / "q.db")
    store = SourceStore(tmp_path / "s.db")
    assert process_one(instance=None, q=q, store=store) is False


@pytest.mark.asyncio
async def test_process_one_async_snippet_full_chain(tmp_path):
    q = JobQueue(tmp_path / "q.db")
    store = SourceStore(tmp_path / "s.db")
    jid = q.enqueue("privat", "snippet", {"text": "Asynchroner Gedanke.", "title": "Async"})
    ingest_mock = AsyncMock()
    with (
        patch("kb.worker.get_vault", return_value=make_vault(tmp_path)),
        patch("kb.cognee_io.ingest", ingest_mock),
    ):
        worked = await process_one_async(instance=None, q=q, store=store)
    assert worked is True
    files = list((tmp_path / "raw").glob("*.md"))
    assert len(files) == 1
    assert "Asynchroner Gedanke." in files[0].read_text()
    record_id = store.conn.execute("SELECT id FROM sources").fetchone()[0]
    ingest_mock.assert_awaited_once_with(None, files[0], "privat", node_sets=[record_id])
    assert q.status(jid) == "done"


@pytest.mark.asyncio
async def test_process_one_async_marks_failed_on_fetch_error(tmp_path):
    q = JobQueue(tmp_path / "q.db")
    store = SourceStore(tmp_path / "s.db")
    jid = q.enqueue("privat", "web", {"url": "https://example.com/down"})
    with (
        patch("kb.worker.get_vault", return_value=make_vault(tmp_path)),
        patch("kb.fetch_web.fetch", side_effect=RuntimeError("offline")),
    ):
        worked = await process_one_async(instance=None, q=q, store=store)
    assert worked is True
    assert q.status(jid) == "failed"


@pytest.mark.asyncio
async def test_process_one_async_returns_false_on_empty_queue(tmp_path):
    q = JobQueue(tmp_path / "q.db")
    store = SourceStore(tmp_path / "s.db")
    assert await process_one_async(instance=None, q=q, store=store) is False


@pytest.mark.asyncio
async def test_run_forever_async_processes_jobs_and_stops_on_cancel(tmp_path):
    q = JobQueue(tmp_path / "q.db")
    store = SourceStore(tmp_path / "s.db")
    jid = q.enqueue("privat", "snippet", {"text": "Service-Job.", "title": "Service"})
    ingest_mock = AsyncMock()
    with (
        patch("kb.worker.get_vault", return_value=make_vault(tmp_path)),
        patch("kb.cognee_io.ingest", ingest_mock),
    ):
        task = asyncio.create_task(
            run_forever_async(instance=None, q=q, store=store, poll_seconds=0.01)
        )
        # Warten, bis der Job verarbeitet ist (Schleife idlet danach im sleep)
        for _ in range(100):
            if q.status(jid) == "done":
                break
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert q.status(jid) == "done"
    ingest_mock.assert_awaited_once()
    assert task.cancelled()


@pytest.mark.asyncio
async def test_run_forever_async_cancel_on_empty_queue(tmp_path):
    # Cancel muss auch im Idle-Sleep sauber durchschlagen
    q = JobQueue(tmp_path / "q.db")
    store = SourceStore(tmp_path / "s.db")
    task = asyncio.create_task(run_forever_async(instance=None, q=q, store=store, poll_seconds=5.0))
    await asyncio.sleep(0.05)  # Schleife läuft an und hängt im sleep
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()


@pytest.mark.asyncio
async def test_process_one_skips_duplicate_body(tmp_path):
    # Gleicher Body im selben Vault -> zweiter Ingest wird übersprungen (mark_done).
    q = JobQueue(tmp_path / "q.db")
    store = SourceStore(tmp_path / "s.db")
    j1 = q.enqueue("privat", "snippet", {"text": "Gleicher Inhalt.", "title": "A"})
    j2 = q.enqueue("privat", "snippet", {"text": "Gleicher Inhalt.", "title": "B"})
    ingest_mock = AsyncMock()
    with (
        patch("kb.worker.get_vault", return_value=make_vault(tmp_path)),
        patch("kb.cognee_io.ingest", ingest_mock),
    ):
        assert await process_one_async(instance=None, q=q, store=store) is True
        assert await process_one_async(instance=None, q=q, store=store) is True
    # Beide Jobs done, aber nur EINE Quelle/raw-Datei und nur EIN cognify.
    assert q.status(j1) == "done" and q.status(j2) == "done"
    assert store.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1
    assert len(list((tmp_path / "raw").glob("*.md"))) == 1
    assert ingest_mock.await_count == 1


@pytest.mark.asyncio
async def test_process_one_cleans_up_on_ingest_failure_then_reingests(tmp_path):
    # Scheitert cognify NACH dem Anlegen von Source-Record + Rohdatei, muss der
    # Worker beides aufräumen — sonst vergiftet der Dedup-Check (find_by_hash
    # ohne Status-Filter) diesen Inhalt dauerhaft: ein erneuter Ingest würde
    # still als Duplikat übersprungen (stummer Datenverlust).
    import hashlib

    q = JobQueue(tmp_path / "q.db")
    store = SourceStore(tmp_path / "s.db")
    text = "Wichtiger Inhalt, der beim ersten Versuch scheitert."
    j1 = q.enqueue("privat", "snippet", {"text": text, "title": "Notiz"})

    failing = AsyncMock(side_effect=RuntimeError("ollama down"))
    with (
        patch("kb.worker.get_vault", return_value=make_vault(tmp_path)),
        patch("kb.cognee_io.ingest", failing),
    ):
        worked = await process_one_async(instance=None, q=q, store=store)
    assert worked is True
    assert q.status(j1) == "failed"
    # Kein Ghost-Record, keine verwaiste Rohdatei.
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert store.find_by_hash(h, "privat") is None
    assert store.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0
    assert len(list((tmp_path / "raw").glob("*.md"))) == 0

    # Erneuter Ingest desselben Inhalts läuft wirklich neu (kein Dedup-Skip).
    j2 = q.enqueue("privat", "snippet", {"text": text, "title": "Notiz"})
    succeeding = AsyncMock()
    with (
        patch("kb.worker.get_vault", return_value=make_vault(tmp_path)),
        patch("kb.cognee_io.ingest", succeeding),
    ):
        worked = await process_one_async(instance=None, q=q, store=store)
    assert worked is True
    assert q.status(j2) == "done"
    succeeding.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_job_logs_job_id_vault_and_request_id(tmp_path, caplog):
    # Strukturiertes Logging: eine gescheiterte Job-Variable enthält job id,
    # Vault und (falls im Payload) die request_id — zur Korrelation über 3 Prozesse.
    q = JobQueue(tmp_path / "q.db")
    store = SourceStore(tmp_path / "s.db")
    jid = q.enqueue("privat", "web", {"url": "https://example.com/x", "request_id": "rid-9"})
    with (
        patch("kb.worker.get_vault", return_value=make_vault(tmp_path)),
        patch("kb.fetch_web.fetch", side_effect=RuntimeError("offline")),
        caplog.at_level(logging.ERROR, logger="kb.worker"),
    ):
        await process_one_async(None, q=q, store=store)
    assert q.status(jid) == "failed"
    msg = next(r.getMessage() for r in caplog.records if r.name == "kb.worker")
    assert f"job={jid}" in msg
    assert "vault=privat" in msg
    assert "request_id=rid-9" in msg


@pytest.mark.asyncio
async def test_initial_ingest_projects_and_publishes_collection_membership(tmp_path):
    q = JobQueue(tmp_path / "q.db")
    store = SourceStore(tmp_path / "s.db")
    one = store.create_collection("privat", "Eins")
    two = store.create_collection("privat", "Zwei")
    jid = q.enqueue("privat", "snippet", {"text": "Inhalt", "collection_ids": [one.id, two.id]})
    ingest_mock = AsyncMock(return_value=("dataset-1", "data-1"))
    with (
        patch("kb.worker.get_vault", return_value=make_vault(tmp_path)),
        patch("kb.cognee_io.ingest", ingest_mock),
    ):
        await process_one_async(None, q=q, store=store)

    source_id = store.conn.execute("SELECT id FROM sources").fetchone()[0]
    ingest_mock.assert_awaited_once_with(
        None, ANY, "privat", node_sets=[source_id, one.node_set_key, two.node_set_key]
    )
    assert store.desired_collection_ids(source_id) == [one.id, two.id]
    assert store.indexed_collection_ids(source_id) == [one.id, two.id]
    assert store.get_collection_sync(source_id).collection_sync_status == "synced"
    assert store.cognee_ids(source_id) == ("dataset-1", "data-1")
    assert q.status(jid) == "done"


@pytest.mark.asyncio
async def test_reindex_failure_preserves_indexed_membership_and_stale_job_cannot_publish(tmp_path):
    q = JobQueue(tmp_path / "q.db")
    store = SourceStore(tmp_path / "s.db")
    old = store.create_collection("privat", "Alt")
    new = store.create_collection("privat", "Neu")
    raw = tmp_path / "raw.md"
    raw.write_text("Inhalt")
    source = SourceRecord.new(
        type="snippet",
        url=None,
        video_id=None,
        locator=None,
        vault="privat",
        raw_md_path=str(raw),
    )
    store.insert(source)
    store.initialize_collections(source.id, [old.id], cognee_dataset_id="ds", cognee_data_id="data")
    rev1 = store.replace_desired_collections(source.id, [new.id]).collection_revision
    rev2 = store.replace_desired_collections(source.id, []).collection_revision
    q.enqueue_reindex("privat", source.id, rev1)
    delete_mock = AsyncMock(side_effect=RuntimeError("delete failed"))
    with (
        patch("kb.worker.get_vault", return_value=make_vault(tmp_path)),
        patch("kb.cognee_io.delete_source", delete_mock),
    ):
        await process_one_async(None, q=q, store=store)

    assert store.indexed_collection_ids(source.id) == [old.id]
    assert store.get_collection_sync(source.id).collection_revision == rev2
    assert store.get_collection_sync(source.id).collection_sync_status == "pending"


@pytest.mark.asyncio
async def test_reindex_deletes_source_data_and_publishes_current_revision(tmp_path):
    q = JobQueue(tmp_path / "q.db")
    store = SourceStore(tmp_path / "s.db")
    collection = store.create_collection("privat", "Neu")
    raw = tmp_path / "raw.md"
    raw.write_text("Inhalt")
    source = SourceRecord.new(
        type="snippet", url=None, video_id=None, locator=None, vault="privat", raw_md_path=str(raw)
    )
    store.insert(source)
    store.initialize_collections(
        source.id, [], cognee_dataset_id="ds-old", cognee_data_id="data-old"
    )
    revision = store.replace_desired_collections(source.id, [collection.id]).collection_revision
    jid = q.enqueue_reindex("privat", source.id, revision)
    delete_mock = AsyncMock()
    ingest_mock = AsyncMock(return_value=("ds-new", "data-new"))
    with (
        patch("kb.worker.get_vault", return_value=make_vault(tmp_path)),
        patch("kb.cognee_io.delete_source", delete_mock),
        patch("kb.cognee_io.ingest", ingest_mock),
    ):
        await process_one_async(None, q=q, store=store)

    delete_mock.assert_awaited_once_with(None, "ds-old", "data-old", provenance_node_set=source.id)
    ingest_mock.assert_awaited_once_with(
        None, raw, "privat", node_sets=[source.id, collection.node_set_key]
    )
    assert store.indexed_collection_ids(source.id) == [collection.id]
    assert store.cognee_ids(source.id) == ("ds-new", "data-new")
    assert store.get_collection_sync(source.id).collection_sync_status == "synced"
    assert q.status(jid) == "done"


@pytest.mark.asyncio
async def test_failed_reindex_rolls_back_prior_index_projection(tmp_path):
    q = JobQueue(tmp_path / "q.db")
    store = SourceStore(tmp_path / "s.db")
    old = store.create_collection("privat", "Alt")
    new = store.create_collection("privat", "Neu")
    raw = tmp_path / "raw.md"
    raw.write_text("Inhalt")
    source = SourceRecord.new(
        type="snippet", url=None, video_id=None, locator=None, vault="privat", raw_md_path=str(raw)
    )
    store.insert(source)
    store.initialize_collections(
        source.id, [old.id], cognee_dataset_id="ds-old", cognee_data_id="data-old"
    )
    revision = store.replace_desired_collections(source.id, [new.id]).collection_revision
    jid = q.enqueue_reindex("privat", source.id, revision)
    ingest_mock = AsyncMock(
        side_effect=[RuntimeError("cognify down"), ("ds-rollback", "data-rollback")]
    )
    with (
        patch("kb.worker.get_vault", return_value=make_vault(tmp_path)),
        patch("kb.cognee_io.delete_source", AsyncMock()),
        patch("kb.cognee_io.ingest", ingest_mock),
    ):
        await process_one_async(None, q=q, store=store)

    assert ingest_mock.await_args_list[0].kwargs["node_sets"] == [source.id, new.node_set_key]
    assert ingest_mock.await_args_list[1].kwargs["node_sets"] == [source.id, old.node_set_key]
    assert store.cognee_ids(source.id) == ("ds-rollback", "data-rollback")
    assert store.indexed_collection_ids(source.id) == [old.id]
    sync = store.get_collection_sync(source.id)
    assert sync.indexed_collection_revision == 0
    assert sync.collection_revision == revision
    assert sync.collection_sync_status == "failed"
    assert "cognify down" in sync.collection_sync_error
    assert q.status(jid) == "failed"


@pytest.mark.asyncio
async def test_failed_reindex_records_primary_and_rollback_failure(tmp_path):
    q = JobQueue(tmp_path / "q.db")
    store = SourceStore(tmp_path / "s.db")
    old = store.create_collection("privat", "Alt")
    new = store.create_collection("privat", "Neu")
    raw = tmp_path / "raw.md"
    raw.write_text("Inhalt")
    source = SourceRecord.new(
        type="snippet", url=None, video_id=None, locator=None, vault="privat", raw_md_path=str(raw)
    )
    store.insert(source)
    store.initialize_collections(
        source.id, [old.id], cognee_dataset_id="ds-old", cognee_data_id="data-old"
    )
    revision = store.replace_desired_collections(source.id, [new.id]).collection_revision
    jid = q.enqueue_reindex("privat", source.id, revision)
    ingest_mock = AsyncMock(
        side_effect=[RuntimeError("primary cognify error"), RuntimeError("rollback error")]
    )
    with (
        patch("kb.worker.get_vault", return_value=make_vault(tmp_path)),
        patch("kb.cognee_io.delete_source", AsyncMock()),
        patch("kb.cognee_io.ingest", ingest_mock),
    ):
        await process_one_async(None, q=q, store=store)

    sync = store.get_collection_sync(source.id)
    assert sync.collection_sync_status == "failed"
    assert "primary cognify error" in sync.collection_sync_error
    assert "rollback error" in sync.collection_sync_error
    assert store.indexed_collection_ids(source.id) == [old.id]
    assert store.cognee_ids(source.id) == ("ds-old", "data-old")
    assert q.status(jid) == "failed"


# --- Upload-Jobs: Konsum, Cleanup, Dedup, Fehler, Orphan-Reinigung ---


@pytest.fixture
def upload_vault(tmp_path, isolated_var) -> Vault:
    # Staging landet via isolated_var unter <tmp>/var/local/uploads/privat.
    return Vault(name="privat", instance="local", dataset="privat", raw_dir=tmp_path / "raw")


def stage_tmp_upload(vault: Vault, body: bytes, suffix: str = ".txt") -> str:
    """Legt eine Datei so ab, wie stage_upload sie hinterlassen würde."""
    root = upload_dir(vault)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    reference = f"{uuid.uuid4().hex}{suffix}"
    (root / reference).write_bytes(body)
    return reference


def _source_count(store: SourceStore) -> int:
    return store.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]


@pytest.mark.asyncio
async def test_upload_job_consumes_txt_and_cleans_staged_file(tmp_path, upload_vault):
    vault = upload_vault
    reference = stage_tmp_upload(vault, b"Upload-Inhalt")
    q = JobQueue(tmp_path / "q.db")
    store = SourceStore(tmp_path / "s.db")
    jid = q.enqueue("privat", "upload", {"reference": reference, "filename": "notiz.txt"})
    ingest_mock = AsyncMock(return_value=("ds-1", "data-1"))

    with (
        patch("kb.worker.get_vault", return_value=vault),
        patch("kb.cognee_io.ingest", ingest_mock),
    ):
        assert await process_one_async(None, q=q, store=store)

    assert q.status(jid) == "done"
    # Staged-Datei nach der Verarbeitung entfernt.
    assert list(upload_dir(vault).iterdir()) == []
    # Quelle angelegt, Titel vom Dateinamen, Body im Rawstore.
    (record,) = store.conn.execute("SELECT id, title, type FROM sources").fetchall()
    assert record[1] == "notiz"
    assert record[2] == "file"
    raw_file = Path(next(iter((vault.raw_dir).glob("*.md"))))
    assert "Upload-Inhalt" in raw_file.read_text()
    ingest_mock.assert_awaited_once_with(
        None, ANY, "privat", node_sets=[record[0]]
    )


@pytest.mark.asyncio
async def test_upload_job_consumes_pdf_via_fetch_pdf(tmp_path, upload_vault):
    vault = upload_vault
    reference = stage_tmp_upload(vault, b"%PDF-fake", suffix=".pdf")
    q = JobQueue(tmp_path / "q.db")
    store = SourceStore(tmp_path / "s.db")
    jid = q.enqueue("privat", "upload", {"reference": reference, "filename": "bericht.pdf"})
    ingest_mock = AsyncMock(return_value=("ds-2", "data-2"))

    with (
        patch("kb.worker.get_vault", return_value=vault),
        patch("kb.fetch_pdf.from_path", return_value=FetchedDoc(title="Bericht", body="PDF-Text")),
        patch("kb.cognee_io.ingest", ingest_mock),
    ):
        assert await process_one_async(None, q=q, store=store)

    assert q.status(jid) == "done"
    assert list(upload_dir(vault).iterdir()) == []
    path_arg = ingest_mock.await_args.args[1]
    assert Path(path_arg).read_text().count("PDF-Text") == 1
    assert store.conn.execute("SELECT type FROM sources").fetchone()[0] == "pdf"


@pytest.mark.asyncio
async def test_upload_job_dedup_marks_done_without_ingest(tmp_path, upload_vault):
    vault = upload_vault
    reference = stage_tmp_upload(vault, b"doppelter Body")
    q = JobQueue(tmp_path / "q.db")
    store = SourceStore(tmp_path / "s.db")
    raw = tmp_path / "alt.md"
    raw.write_text("alt")
    store.insert(
        SourceRecord.new(
            type="snippet",
            url=None,
            video_id=None,
            locator=None,
            vault="privat",
            raw_md_path=str(raw),
            content_hash=hashlib.sha256("doppelter Body".encode()).hexdigest(),
        )
    )
    jid = q.enqueue("privat", "upload", {"reference": reference, "filename": "dup.txt"})
    ingest_mock = AsyncMock()

    with (
        patch("kb.worker.get_vault", return_value=vault),
        patch("kb.cognee_io.ingest", ingest_mock),
    ):
        assert await process_one_async(None, q=q, store=store)

    # Dedup ist kein Fehler: done, kein zweiter Ingest, keine zweite Quelle.
    assert q.status(jid) == "done"
    ingest_mock.assert_not_awaited()
    assert _source_count(store) == 1
    assert list(upload_dir(vault).iterdir()) == []


@pytest.mark.asyncio
async def test_upload_job_failure_marks_failed_and_cleans_staged_file(tmp_path, upload_vault):
    vault = upload_vault
    # Gültiger Referenz-Name, aber leerer Inhalt → Fetch schlägt fehl.
    reference = stage_tmp_upload(vault, b"")
    q = JobQueue(tmp_path / "q.db")
    store = SourceStore(tmp_path / "s.db")
    jid = q.enqueue("privat", "upload", {"reference": reference, "filename": "leer.txt"})

    with patch("kb.worker.get_vault", return_value=vault):
        assert await process_one_async(None, q=q, store=store)

    assert q.status(jid) == "failed"
    assert "leer" in q.info(jid)["error"]
    # Cleanup läuft auch im Fehlerfall (finally-Zweig).
    assert list(upload_dir(vault).iterdir()) == []
    assert _source_count(store) == 0


@pytest.mark.asyncio
async def test_upload_job_missing_staged_file_fails(tmp_path, upload_vault):
    vault = upload_vault
    q = JobQueue(tmp_path / "q.db")
    store = SourceStore(tmp_path / "s.db")
    jid = q.enqueue(
        "privat", "upload", {"reference": f"{uuid.uuid4().hex}.txt", "filename": "weg.txt"}
    )

    with patch("kb.worker.get_vault", return_value=vault):
        assert await process_one_async(None, q=q, store=store)

    assert q.status(jid) == "failed"
    assert "Staged Upload nicht gefunden" in q.info(jid)["error"]


@pytest.mark.asyncio
async def test_upload_job_invalid_filename_payload_fails(tmp_path, upload_vault):
    vault = upload_vault
    reference = stage_tmp_upload(vault, b"x")
    q = JobQueue(tmp_path / "q.db")
    store = SourceStore(tmp_path / "s.db")
    jid = q.enqueue("privat", "upload", {"reference": reference, "filename": 42})

    with patch("kb.worker.get_vault", return_value=vault):
        assert await process_one_async(None, q=q, store=store)

    assert q.status(jid) == "failed"
    assert "Ungültiger Upload-Dateiname" in q.info(jid)["error"]
    assert list(upload_dir(vault).iterdir()) == []


@pytest.mark.asyncio
async def test_worker_startup_reconciliation_keeps_active_and_removes_stale(tmp_path, upload_vault):
    """Spiegelt den Startup-Pfad aus run_forever: recover + reconcile_orphans."""
    import os
    import time as time_mod

    vault = upload_vault
    q = JobQueue(tmp_path / "q.db")
    active_ref = stage_tmp_upload(vault, b"aktiv")
    q.enqueue("privat", "upload", {"reference": active_ref, "filename": "a.txt"})
    done_ref = stage_tmp_upload(vault, b"fertig")  # Job done → Referenz nicht mehr aktiv
    done_jid = q.enqueue("privat", "upload", {"reference": done_ref, "filename": "b.txt"})
    q.mark_done(done_jid)
    stale_orphan = Path(upload_dir(vault)) / f"{uuid.uuid4().hex}.txt"
    stale_orphan.write_bytes(b"verwaist")
    done_path = Path(upload_dir(vault)) / done_ref
    old = time_mod.time() - 400  # auch die done-Referenz muss die Grace überschreiten
    os.utime(stale_orphan, (old, old))
    os.utime(done_path, (old, old))
    fresh_orphan = Path(upload_dir(vault)) / f"{uuid.uuid4().hex}.txt"
    fresh_orphan.write_bytes(b"frisch")

    removed = reconcile_orphans(vault, q.active_upload_references("privat"))

    assert removed == 2  # verwaiste Datei + Referenz des erledigten Jobs
    assert (Path(upload_dir(vault)) / active_ref).exists()
    assert not stale_orphan.exists()
    assert not (Path(upload_dir(vault)) / done_ref).exists()
    assert fresh_orphan.exists()


def test_active_upload_references_only_counts_pending_and_running(tmp_path, upload_vault):
    vault = upload_vault
    q = JobQueue(tmp_path / "q.db")
    pending_ref = f"{uuid.uuid4().hex}.txt"
    done_ref = f"{uuid.uuid4().hex}.txt"
    failed_ref = f"{uuid.uuid4().hex}.txt"
    q.enqueue("privat", "upload", {"reference": pending_ref, "filename": "p.txt"})
    done = q.enqueue("privat", "upload", {"reference": done_ref, "filename": "d.txt"})
    failed = q.enqueue("privat", "upload", {"reference": failed_ref, "filename": "f.txt"})
    q.mark_done(done)
    q.mark_failed(failed, "x")

    assert q.active_upload_references("privat") == {pending_ref}
    # Nur der eigene Vault zählt.
    assert q.active_upload_references("anderer") == set()
