import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from kb import cognee_io, guard, instance_service, query_service, worker
from kb.config import Instance
from kb.guard import EnvGuardError
from kb.query_models import Citation, EvidenceChunk, QueryResult
from kb.queue import JobQueue
from kb.sources import SourceRecord, SourceStore


def make_instance(tmp_path) -> Instance:
    return Instance(
        name="local",
        env_file=tmp_path / ".env.local",
        allowed_llm_providers=("ollama",),
        expected_embedding_provider="fastembed",
        var_dir=tmp_path,
        port=8801,
    )


async def _idle_worker(instance, q, store, poll_seconds=5.0):
    """Fake-Worker, der wie der echte 'ewig' läuft — Shutdown cancelt."""
    await asyncio.Event().wait()


@pytest.fixture
def inst(tmp_path, monkeypatch):
    """Instanz mit var_dir=tmp_path; Env-Load, Guard und Worker gemockt."""
    instance = make_instance(tmp_path)
    monkeypatch.setattr(instance_service, "get_instance", lambda name: instance)
    monkeypatch.setattr(cognee_io, "load_instance_env", lambda i: None)
    monkeypatch.setattr(guard, "assert_instance_env", lambda i: None)
    monkeypatch.setattr(worker, "run_forever_async", _idle_worker)
    return instance


# --- /health ---


def test_health_reports_queue_counts(inst, tmp_path):
    with TestClient(instance_service.create_app("local")) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {
            "instance": "local",
            "queue": {"pending": 0, "running": 0, "done": 0, "failed": 0},
            "worker": "ok",
        }
        # Job enqueuen (eigene Connection, WAL) → pending=1
        JobQueue(tmp_path / "queue.db").enqueue("privat", "snippet", {"text": "x"})
        r = client.get("/health")
        assert r.json()["queue"]["pending"] == 1


def test_health_reports_dead_worker(inst, monkeypatch, capsys):
    async def crashing_worker(instance, q, store, poll_seconds=5.0):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(worker, "run_forever_async", crashing_worker)
    with TestClient(instance_service.create_app("local")) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["worker"] == "dead"
    # Tod wurde auf stderr geloggt
    err = capsys.readouterr().err
    assert "Worker-Task gestorben" in err
    assert "RuntimeError: kaputt" in err


# --- /query ---


def test_search_returns_ranked_evidence_without_answer(inst, monkeypatch):
    retrieve_mock = AsyncMock(
        return_value=[
            EvidenceChunk(evidence_id="e1", rank=1, text="Beleg", source_ids=["unbekannt"])
        ]
    )
    monkeypatch.setattr(cognee_io, "retrieve", retrieve_mock)

    with TestClient(instance_service.create_app("local")) as client:
        r = client.post("/search", json={"question": "Was ist X?", "datasets": ["privat"]})

    assert r.status_code == 200
    assert r.json() == {
        "answer": None,
        "evidence": [
            {
                "evidence_id": "e1",
                "rank": 1,
                "text": "Beleg",
                "source_ids": [],
            }
        ],
        "citations": [],
        "gaps": [
            {
                "kind": "unresolved_source",
                "detail": "Quellen-ID nicht im angefragten Vault auflösbar: unbekannt",
            }
        ],
        "trace": {
            "retrieval_ms": r.json()["trace"]["retrieval_ms"],
            "synthesis_ms": None,
            "warnings": [],
        },
        "sources": [],
    }
    retrieve_mock.assert_awaited_once_with(inst, "Was ist X?", datasets=["privat"])


def test_query_calls_cognee_io(inst, monkeypatch):
    query_mock = AsyncMock(return_value=QueryResult(answer="Antwort!"))
    monkeypatch.setattr(query_service, "answer", query_mock)
    app = instance_service.create_app("local")
    with TestClient(app) as client:
        r = client.post("/query", json={"question": "Was ist X?", "datasets": ["privat"]})
    assert r.status_code == 200
    assert r.json()["answer"] == "Antwort!"
    assert r.json()["citations"] == []
    query_mock.assert_awaited_once_with(
        inst, "Was ist X?", datasets=["privat"], store=app.state.store
    )


def test_query_returns_sources(inst, tmp_path, monkeypatch):
    # source_ids enthalten "sid1" — ein passender Record liegt in der Store-DB.
    query_mock = AsyncMock(
        return_value=QueryResult(
            answer="A",
            citations=[Citation(claim_index=0, evidence_ids=["e1"], source_ids=["sid1"])],
        )
    )
    monkeypatch.setattr(query_service, "answer", query_mock)

    rec = SourceRecord(
        id="sid1",
        type="snippet",
        url=None,
        video_id=None,
        locator=None,
        fetched_at="2026-01-01T00:00:00Z",
        vault="privat",
        raw_md_path="raw/privat/x.md",
        title="Testtitel",
    )

    # Record über eine eigene Connection einfügen — SourceStore.conn ist
    # thread-gebunden; die App-interne Connection läuft im ASGI-Thread.
    SourceStore(tmp_path / "sources.db").insert(rec)

    with TestClient(instance_service.create_app("local")) as client:
        r = client.post("/query", json={"question": "Was?", "datasets": ["privat"]})

    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "A"
    assert body["sources"] == [
        {
            "source_id": "sid1",
            "type": "snippet",
            "url": None,
            "locator": None,
            "raw_md_path": "raw/privat/x.md",
            "title": "Testtitel",
        }
    ]


def test_query_skips_unknown_source_ids(inst, monkeypatch):
    # source_id ohne passenden DB-Record → wird übersprungen, kein Crash.
    query_mock = AsyncMock(
        return_value=QueryResult(
            answer="B",
            citations=[Citation(claim_index=0, evidence_ids=["e1"], source_ids=["unbekannt"])],
        )
    )
    monkeypatch.setattr(query_service, "answer", query_mock)
    with TestClient(instance_service.create_app("local")) as client:
        r = client.post("/query", json={"question": "?", "datasets": ["privat"]})
    assert r.status_code == 200
    assert r.json()["answer"] == "B"
    assert r.json()["sources"] == []


def test_query_does_not_resolve_source_from_other_vault(inst, tmp_path, monkeypatch):
    query_mock = AsyncMock(
        return_value=QueryResult(
            answer="B",
            citations=[Citation(claim_index=0, evidence_ids=["e1"], source_ids=["foreign"])],
        )
    )
    monkeypatch.setattr(query_service, "answer", query_mock)
    SourceStore(tmp_path / "sources.db").insert(
        SourceRecord(
            id="foreign",
            type="snippet",
            url=None,
            video_id=None,
            locator=None,
            fetched_at="2026-01-01T00:00:00Z",
            vault="business-ki",
            raw_md_path="raw/business-ki/x.md",
            title="Fremd",
        )
    )

    with TestClient(instance_service.create_app("local")) as client:
        r = client.post("/query", json={"question": "?", "datasets": ["privat"]})

    assert r.json()["sources"] == []


# --- Lifespan ---


def test_guard_failure_aborts_startup(tmp_path, monkeypatch):
    instance = make_instance(tmp_path)
    monkeypatch.setattr(instance_service, "get_instance", lambda name: instance)
    monkeypatch.setattr(cognee_io, "load_instance_env", lambda i: None)

    def boom(i):
        raise EnvGuardError("falsches Env")

    monkeypatch.setattr(guard, "assert_instance_env", boom)
    with pytest.raises(EnvGuardError):
        with TestClient(instance_service.create_app("local")):
            pass


def test_worker_task_started_and_cancelled_on_shutdown(inst, monkeypatch):
    state = {"started": False, "cancelled": False, "args": None}

    async def fake_run_forever(instance, q, store, poll_seconds=5.0):
        state["started"] = True
        state["args"] = (instance, q, store)
        try:
            await asyncio.Event().wait()  # wartet, bis der Shutdown cancelt
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise

    monkeypatch.setattr(worker, "run_forever_async", fake_run_forever)
    with TestClient(instance_service.create_app("local")) as client:
        assert client.get("/health").status_code == 200
    # Shutdown hat den Background-Task gecancelt und sauber awaited
    assert state["started"] is True
    assert state["cancelled"] is True
    instance, q, store = state["args"]
    assert instance is inst
    assert q is not None and store is not None


def test_lifespan_closes_sqlite_connections(inst):
    # Nach dem Shutdown müssen die SQLite-Connections des Instance Service
    # geschlossen sein (sonst u. U. uncheckpointierter WAL bei hohem Schreibdruck).
    import sqlite3

    app = instance_service.create_app("local")
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        q = app.state.q
        store = app.state.store
    # Nach dem `with`-Exit (Shutdown) sind die Connections zu:
    with pytest.raises(sqlite3.ProgrammingError):
        q.conn.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError):
        store.conn.execute("SELECT 1")
