import asyncio
import sys

import httpx
import pytest

from kb import mcp_server
from kb.queue import JobQueue


def _tool_names(server) -> set[str]:
    return {t.name for t in asyncio.run(server.list_tools())}


async def _call(server, name, **kwargs) -> str:
    # FastMCP.call_tool gibt (content, structured) zurück — Text aus dem Content ziehen.
    result = await server.call_tool(name, kwargs)
    content = result[0] if isinstance(result, tuple) else result
    return content[0].text


# --- Tool-Registrierung pro Instanz ---

def test_local_tools():
    names = _tool_names(mcp_server.build_server("local"))
    assert names == {"search_privat", "ingest", "job_status"}
    assert "search_all" not in names  # nur ein Vault


def test_cloud_tools():
    names = _tool_names(mcp_server.build_server("cloud"))
    assert names == {
        "search_allgemein", "search_business_ki", "search_business_mwe",
        "search_all", "ingest", "job_status"}


# --- Ingest ---

def test_ingest_foreign_vault_no_enqueue(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "queue_path", lambda inst: tmp_path / f"{inst}.db")
    server = mcp_server.build_server("local")
    # business-ki gehört nicht zur Instanz local
    msg = asyncio.run(_call(server, "ingest", vault="business-ki", content="x"))
    assert "gehört nicht" in msg
    # Nichts enqueued: Queue-DB darf nicht existieren
    assert not (tmp_path / "local.db").exists()


def test_ingest_valid_vault_enqueues(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "queue_path", lambda inst: tmp_path / f"{inst}.db")
    server = mcp_server.build_server("local")
    msg = asyncio.run(_call(
        server, "ingest", vault="privat",
        content="https://youtu.be/dQw4w9WgXcQ", node_set="musik"))
    assert "queued job" in msg
    jid = int(msg.split()[2])
    info = JobQueue(tmp_path / "local.db").info(jid)
    assert info is not None
    assert info["status"] == "pending"
    assert info["kind"] == "youtube"
    assert info["vault"] == "privat"


def test_ingest_plain_text_snippet(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "queue_path", lambda inst: tmp_path / f"{inst}.db")
    server = mcp_server.build_server("cloud")
    msg = asyncio.run(_call(
        server, "ingest", vault="business-ki", content="Nur ein Gedanke."))
    assert "(snippet)" in msg


# --- job_status ---

def test_job_status_foreign_vault(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "queue_path", lambda inst: tmp_path / f"{inst}.db")
    server = mcp_server.build_server("local")
    msg = asyncio.run(_call(server, "job_status", vault="business-ki", job_id=1))
    assert "gehört nicht" in msg


def test_job_status_after_enqueue(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "queue_path", lambda inst: tmp_path / f"{inst}.db")
    server = mcp_server.build_server("local")
    ingest_msg = asyncio.run(_call(server, "ingest", vault="privat", content="Notiz"))
    jid = int(ingest_msg.split()[2])
    msg = asyncio.run(_call(server, "job_status", vault="privat", job_id=jid))
    assert "pending" in msg


def test_job_status_unknown_job(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "queue_path", lambda inst: tmp_path / f"{inst}.db")
    server = mcp_server.build_server("local")
    msg = asyncio.run(_call(server, "job_status", vault="privat", job_id=9999))
    assert "Unbekannter Job" in msg


# --- Fake-httpx für search (respx ist nicht installiert) ---

class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = {"answer": "42"} if payload is None else payload
        self.text = str(self._payload)

    def json(self):
        if self._payload is _NO_JSON:
            raise ValueError("not json")
        return self._payload


_NO_JSON = object()


def _fake_async_client(response=None, exc=None, calls=None):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def post(self, url, json=None):
            if calls is not None:
                calls.append((url, json))
            if exc is not None:
                raise exc
            return response

    return FakeClient


# --- search-Proxy ---

def test_search_calls_correct_port_and_dataset(monkeypatch):
    calls = []
    monkeypatch.setattr(mcp_server.httpx, "AsyncClient",
                        _fake_async_client(response=_FakeResponse(), calls=calls))
    server = mcp_server.build_server("cloud")
    answer = asyncio.run(_call(server, "search_business_mwe", question="Was ist X?"))
    assert answer == "42"
    url, payload = calls[0]
    assert url == "http://127.0.0.1:8802/query"
    assert payload == {"question": "Was ist X?", "datasets": ["business-mwe"]}


def test_search_binds_correct_dataset_for_non_last_vault(monkeypatch):
    # business-ki ist NICHT der letzte Vault der Schleife — ein Late-Binding-Leak
    # würde alle Tools auf business-mwe zeigen lassen und hier auffliegen.
    calls = []
    monkeypatch.setattr(mcp_server.httpx, "AsyncClient",
                        _fake_async_client(response=_FakeResponse(), calls=calls))
    server = mcp_server.build_server("cloud")
    asyncio.run(_call(server, "search_business_ki", question="Was ist X?"))
    _, payload = calls[0]
    assert payload["datasets"] == ["business-ki"]


def test_search_200_without_answer_key_is_readable(monkeypatch):
    monkeypatch.setattr(mcp_server.httpx, "AsyncClient",
                        _fake_async_client(response=_FakeResponse(payload={"error": "boom"})))
    server = mcp_server.build_server("local")
    msg = asyncio.run(_call(server, "search_privat", question="Hallo?"))
    assert "keine Antwort" in msg
    assert "boom" in msg


def test_search_non_200_returns_status_message(monkeypatch):
    monkeypatch.setattr(mcp_server.httpx, "AsyncClient",
                        _fake_async_client(response=_FakeResponse(status_code=500)))
    server = mcp_server.build_server("local")
    msg = asyncio.run(_call(server, "search_privat", question="Hallo?"))
    assert "500" in msg


def test_search_all_uses_all_datasets(monkeypatch):
    calls = []
    monkeypatch.setattr(mcp_server.httpx, "AsyncClient",
                        _fake_async_client(response=_FakeResponse(), calls=calls))
    server = mcp_server.build_server("cloud")
    asyncio.run(_call(server, "search_all", question="Y?"))
    _, payload = calls[0]
    assert set(payload["datasets"]) == {"allgemein", "business-ki", "business-mwe"}


def test_search_instance_down_returns_readable_message(monkeypatch):
    monkeypatch.setattr(mcp_server.httpx, "AsyncClient",
                        _fake_async_client(exc=httpx.ConnectError("zu")))
    server = mcp_server.build_server("local")
    msg = asyncio.run(_call(server, "search_privat", question="Hallo?"))
    assert "nicht erreichbar" in msg
    assert "8801" in msg


# --- Privacy-Wand: kein cognee-Import ---

def test_import_does_not_pull_cognee():
    # mcp_server ist bereits importiert (oben) — cognee darf nicht mitgekommen sein.
    assert "cognee" not in sys.modules
