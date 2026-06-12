import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from kb import cognee_io, guard, instance_service, worker
from kb.config import Instance
from kb.guard import EnvGuardError
from kb.queue import JobQueue


def make_instance(tmp_path) -> Instance:
    return Instance(name="privat", env_file=tmp_path / ".env.privat",
                    expected_llm_provider="ollama",
                    expected_embedding_provider="fastembed",
                    var_dir=tmp_path, port=8801)


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
    with TestClient(instance_service.create_app("privat")) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"instance": "privat", "queue": {
            "pending": 0, "running": 0, "done": 0, "failed": 0},
            "worker": "ok"}
        # Job enqueuen (eigene Connection, WAL) → pending=1
        JobQueue(tmp_path / "queue.db").enqueue(
            "privat", "snippet", {"text": "x"})
        r = client.get("/health")
        assert r.json()["queue"]["pending"] == 1


def test_health_reports_dead_worker(inst, monkeypatch, capsys):
    async def crashing_worker(instance, q, store, poll_seconds=5.0):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(worker, "run_forever_async", crashing_worker)
    with TestClient(instance_service.create_app("privat")) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["worker"] == "dead"
    # Tod wurde auf stderr geloggt
    err = capsys.readouterr().err
    assert "Worker-Task gestorben" in err
    assert "RuntimeError: kaputt" in err


# --- /query ---

def test_query_calls_cognee_io(inst, monkeypatch):
    query_mock = AsyncMock(return_value="Antwort!")
    monkeypatch.setattr(cognee_io, "query", query_mock)
    with TestClient(instance_service.create_app("privat")) as client:
        r = client.post("/query", json={
            "question": "Was ist X?", "datasets": ["privat"]})
    assert r.status_code == 200
    assert r.json() == {"answer": "Antwort!"}
    query_mock.assert_awaited_once_with(inst, "Was ist X?", datasets=["privat"])


# --- Lifespan ---

def test_guard_failure_aborts_startup(tmp_path, monkeypatch):
    instance = make_instance(tmp_path)
    monkeypatch.setattr(instance_service, "get_instance", lambda name: instance)
    monkeypatch.setattr(cognee_io, "load_instance_env", lambda i: None)

    def boom(i):
        raise EnvGuardError("falsches Env")

    monkeypatch.setattr(guard, "assert_instance_env", boom)
    with pytest.raises(EnvGuardError):
        with TestClient(instance_service.create_app("privat")):
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
    with TestClient(instance_service.create_app("privat")) as client:
        assert client.get("/health").status_code == 200
    # Shutdown hat den Background-Task gecancelt und sauber awaited
    assert state["started"] is True
    assert state["cancelled"] is True
    instance, q, store = state["args"]
    assert instance is inst
    assert q is not None and store is not None
