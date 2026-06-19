import asyncio
import sys

import httpx
import pytest

from kb import mcp_server, query_proxy
from kb.config import INSTANCES, VAULTS, get_instance
from kb.queue import JobQueue

def _tool_names(server) -> set[str]:
    return {t.name for t in asyncio.run(server.list_tools())}


def _vaults_of(instance: str):
    # Registrierungs-Reihenfolge = kb.toml-Reihenfolge (VAULTS ist insertion-ordered).
    return [v for v in VAULTS.values() if v.instance == instance]


async def _call(server, name, **kwargs) -> str:
    # FastMCP.call_tool gibt (content, structured) zurück — Text aus dem Content ziehen.
    result = await server.call_tool(name, kwargs)
    content = result[0] if isinstance(result, tuple) else result
    return content[0].text


# --- Tool-Registrierung pro Instanz ---

def test_tool_name_sanitizes_hyphens():
    # MCP-Tool-Namen erlauben keine Bindestriche -> werden zu Unterstrichen.
    assert mcp_server._tool_name("business-ki") == "search_business_ki"
    assert mcp_server._tool_name("privat") == "search_privat"


def test_tools_registered_from_instance_vaults():
    # Vertrag (aus der Config abgeleitet, nicht hardcoded): pro Vault der Instanz
    # ein search_<vault>, dazu ingest + job_status, und search_all genau dann,
    # wenn die Instanz mehr als einen Vault hat.
    for inst_name in INSTANCES:
        inst_vaults = _vaults_of(inst_name)
        names = _tool_names(mcp_server.build_server(inst_name))
        expected = {mcp_server._tool_name(v.name) for v in inst_vaults} | {"ingest", "job_status"}
        if len(inst_vaults) > 1:
            expected.add("search_all")
        assert names == expected, inst_name
        assert ("search_all" in names) == (len(inst_vaults) > 1)


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


def test_ingest_snippet_uses_build_payload_title(tmp_path, monkeypatch):
    # Snippet-Titel via snippet_title() (wie Gateway/CLI), NICHT content[:50]
    # — das wäre mitten im Wort/mehrzeilig und würde die Raw-H1 zerbrechen.
    import json

    from kb.classify import snippet_title

    monkeypatch.setattr(mcp_server, "queue_path", lambda inst: tmp_path / f"{inst}.db")
    server = mcp_server.build_server("cloud")
    content = ("# Mein Titel\n\n"
               "Eine Zeile mit mehreren Worten die laenger als fuenfzig Zeichen "
               "ist und so weiter und sofort.")
    msg = asyncio.run(_call(server, "ingest", vault="business-ki", content=content))
    jid = int(msg.split()[2])
    row = JobQueue(tmp_path / "cloud.db").conn.execute(
        "SELECT payload FROM jobs WHERE id=?", (jid,)).fetchone()
    payload = json.loads(row[0])
    assert payload["title"] == snippet_title(content)
    assert payload["title"] != content[:50]
    assert payload["title"] == "Mein Titel"


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
    # Port + Dataset aus der Config abgeleitet (irgendein Vault der cloud-Wall),
    # nicht hardcoded.
    cloud = get_instance("cloud")
    vault = _vaults_of("cloud")[0]
    calls = []
    monkeypatch.setattr(query_proxy.httpx, "AsyncClient",
                        _fake_async_client(response=_FakeResponse(), calls=calls))
    server = mcp_server.build_server("cloud")
    answer = asyncio.run(
        _call(server, mcp_server._tool_name(vault.name), question="Was ist X?"))
    assert answer == "42"
    url, payload = calls[0]
    assert url == f"http://127.0.0.1:{cloud.port}/query"
    assert payload == {"question": "Was ist X?", "datasets": [vault.dataset]}


def test_search_binds_correct_dataset_for_non_last_vault(monkeypatch):
    # Der ERSTE Vault ist (bei >1) nicht der letzte der Registrierungs-Schleife —
    # ein Late-Binding-Leak würde alle Tools auf den letzten Vault zeigen lassen
    # und hier auffliegen. Vault dynamisch, daher robust gegen Topologie-Änderungen.
    cloud_vaults = _vaults_of("cloud")
    if len(cloud_vaults) < 2:
        pytest.skip("cloud-Wall hat <2 Vaults — Late-Binding nicht testbar")
    first = cloud_vaults[0]
    calls = []
    monkeypatch.setattr(query_proxy.httpx, "AsyncClient",
                        _fake_async_client(response=_FakeResponse(), calls=calls))
    server = mcp_server.build_server("cloud")
    asyncio.run(_call(server, mcp_server._tool_name(first.name), question="Was ist X?"))
    _, payload = calls[0]
    assert payload["datasets"] == [first.dataset]


def test_search_200_without_answer_key_is_readable(monkeypatch):
    monkeypatch.setattr(query_proxy.httpx, "AsyncClient",
                        _fake_async_client(response=_FakeResponse(payload={"error": "boom"})))
    server = mcp_server.build_server("local")
    msg = asyncio.run(_call(server, "search_privat", question="Hallo?"))
    assert "keine Antwort" in msg
    assert "boom" in msg


def test_search_non_200_returns_status_message(monkeypatch):
    monkeypatch.setattr(query_proxy.httpx, "AsyncClient",
                        _fake_async_client(response=_FakeResponse(status_code=500)))
    server = mcp_server.build_server("local")
    msg = asyncio.run(_call(server, "search_privat", question="Hallo?"))
    assert "500" in msg


def test_search_all_uses_all_datasets(monkeypatch):
    if len(_vaults_of("cloud")) < 2:
        pytest.skip("cloud-Wall hat <2 Vaults — search_all existiert nicht")
    calls = []
    monkeypatch.setattr(query_proxy.httpx, "AsyncClient",
                        _fake_async_client(response=_FakeResponse(), calls=calls))
    server = mcp_server.build_server("cloud")
    asyncio.run(_call(server, "search_all", question="Y?"))
    _, payload = calls[0]
    assert set(payload["datasets"]) == {v.dataset for v in _vaults_of("cloud")}


def test_search_instance_down_returns_readable_message(monkeypatch):
    monkeypatch.setattr(query_proxy.httpx, "AsyncClient",
                        _fake_async_client(exc=httpx.ConnectError("zu")))
    server = mcp_server.build_server("local")
    msg = asyncio.run(_call(server, "search_privat", question="Hallo?"))
    assert "nicht erreichbar" in msg
    assert "8801" in msg


# --- Privacy-Wand: kein cognee-Import ---

def test_import_does_not_pull_cognee():
    # mcp_server ist bereits importiert (oben) — cognee darf nicht mitgekommen sein.
    assert "cognee" not in sys.modules
