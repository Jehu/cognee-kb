from unittest.mock import AsyncMock, patch

from kb.config import Vault
from kb.queue import JobQueue
from kb.sources import SourceStore
from kb.worker import process_one


def make_vault(tmp_path) -> Vault:
    return Vault(name="privat", instance="privat", dataset="privat",
                 raw_dir=tmp_path / "raw")


def test_process_one_snippet_full_chain(tmp_path):
    q = JobQueue(tmp_path / "q.db")
    store = SourceStore(tmp_path / "s.db")
    jid = q.enqueue("privat", "snippet", {"text": "Wichtiger Gedanke.", "title": "Notiz"})
    ingest_mock = AsyncMock()
    with patch("kb.worker.get_vault", return_value=make_vault(tmp_path)), \
         patch("kb.cognee_io.ingest", ingest_mock):
        worked = process_one(instance=None, q=q, store=store)
    assert worked is True
    # Rohdatei existiert und enthält Frontmatter + Text
    files = list((tmp_path / "raw").glob("*.md"))
    assert len(files) == 1
    assert "Wichtiger Gedanke." in files[0].read_text()
    # Source-Record zeigt auf die Datei
    row = store.conn.execute(
        "SELECT raw_md_path, vault, type FROM sources").fetchone()
    assert row is not None
    assert row[0] == str(files[0])
    assert row[1] == "privat"
    assert row[2] == "snippet"
    # Ingest mit korrekten Argumenten aufgerufen
    ingest_mock.assert_awaited_once_with(None, files[0], "privat", node_sets=[])
    # Job ist done
    assert q.status(jid) == "done"
    assert q.claim_next() is None


def test_process_one_marks_failed_on_fetch_error(tmp_path):
    q = JobQueue(tmp_path / "q.db")
    store = SourceStore(tmp_path / "s.db")
    jid = q.enqueue("privat", "web", {"url": "https://example.com/down"})
    with patch("kb.worker.get_vault", return_value=make_vault(tmp_path)), \
         patch("kb.fetch_web.fetch", side_effect=RuntimeError("offline")):
        worked = process_one(instance=None, q=q, store=store)
    assert worked is True
    assert q.status(jid) == "failed"


def test_process_one_returns_false_on_empty_queue(tmp_path):
    q = JobQueue(tmp_path / "q.db")
    store = SourceStore(tmp_path / "s.db")
    assert process_one(instance=None, q=q, store=store) is False
