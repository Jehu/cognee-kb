import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from kb.config import Vault
from kb.queue import JobQueue
from kb.sources import SourceStore
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
