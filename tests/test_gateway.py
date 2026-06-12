import httpx
import pytest
from fastapi.testclient import TestClient

from kb import gateway
from kb.queue import JobQueue

TOKEN = "test-token-123"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("KB_API_TOKEN", TOKEN)
    monkeypatch.setattr("kb.gateway.queue_path",
                        lambda inst: tmp_path / f"{inst}.db")
    return TestClient(gateway.create_app())


# --- Fake-httpx für den Query-Proxy (respx ist nicht installiert) ---

class _FakeResponse:
    status_code = 200

    def json(self):
        return {"answer": "42"}


def _fake_async_client(response=None, exc=None, calls=None):
    """Baut einen httpx.AsyncClient-Ersatz, der post/get abfängt."""
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

        async def get(self, url):
            if exc is not None:
                raise exc
            return response

    return FakeClient


# --- Auth ---

def test_requires_token(client):
    r = client.post("/api/ingest", json={"vault": "privat", "content": "x"})
    assert r.status_code == 401


def test_rejects_wrong_token(client):
    r = client.get("/api/vaults",
                   headers={"Authorization": "Bearer falsch"})
    assert r.status_code == 401


def test_health_needs_no_token(client, monkeypatch):
    monkeypatch.setattr(gateway.httpx, "AsyncClient",
                        _fake_async_client(exc=httpx.ConnectError("zu")))
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["gateway"] == "ok"
    assert set(body["instances"].values()) == {"down"}


# --- Ingest ---

def test_ingest_enqueues_youtube(client, tmp_path):
    r = client.post("/api/ingest", headers=AUTH, json={
        "vault": "privat",
        "content": "https://youtu.be/dQw4w9WgXcQ",
        "node_set": "musik"})
    assert r.status_code == 202
    body = r.json()
    assert body["vault"] == "privat"
    assert body["kind"] == "youtube"
    # Job liegt wirklich in der Queue der Instanz
    info = JobQueue(tmp_path / "privat.db").info(body["job_id"])
    assert info is not None
    assert info["status"] == "pending"
    assert info["kind"] == "youtube"


def test_ingest_plain_text_stays_snippet(client):
    r = client.post("/api/ingest", headers=AUTH, json={
        "vault": "business-ki", "content": "Nur ein Gedanke."})
    assert r.status_code == 202
    assert r.json()["kind"] == "snippet"


def test_ingest_unknown_vault(client):
    r = client.post("/api/ingest", headers=AUTH, json={
        "vault": "geheim", "content": "x"})
    assert r.status_code == 404


def test_ingest_blank_content_rejected(client):
    # Leerer bzw. Nur-Whitespace-Content → Validierungsfehler
    for content in ("", "   \n\t "):
        r = client.post("/api/ingest", headers=AUTH, json={
            "vault": "privat", "content": content})
        assert r.status_code == 422


# --- Vaults + Jobs ---

def test_vaults_lists_config(client):
    r = client.get("/api/vaults", headers=AUTH)
    assert r.status_code == 200
    names = {v["name"]: v["instance"] for v in r.json()}
    assert names["privat"] == "privat"
    assert names["business-ki"] == "business"


def test_job_info_after_enqueue(client):
    jid = client.post("/api/ingest", headers=AUTH, json={
        "vault": "privat", "content": "Notiz"}).json()["job_id"]
    r = client.get(f"/api/jobs/privat/{jid}", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == jid
    assert body["status"] == "pending"
    assert body["kind"] == "snippet"
    assert body["error"] is None
    assert body["created_at"]


def test_job_info_unknown_job(client):
    r = client.get("/api/jobs/privat/9999", headers=AUTH)
    assert r.status_code == 404


def test_job_info_other_vault_is_404(client):
    # business-ki und business-mwe teilen eine queue.db — Job des einen
    # Vaults darf über den anderen NICHT abrufbar sein (Leak-Schutz).
    jid = client.post("/api/ingest", headers=AUTH, json={
        "vault": "business-ki", "content": "Notiz"}).json()["job_id"]
    r = client.get(f"/api/jobs/business-mwe/{jid}", headers=AUTH)
    assert r.status_code == 404
    # Über den richtigen Vault weiterhin sichtbar
    assert client.get(f"/api/jobs/business-ki/{jid}",
                      headers=AUTH).status_code == 200


# --- Query-Proxy ---

def test_query_proxies_to_instance(client, monkeypatch):
    calls = []
    monkeypatch.setattr(gateway.httpx, "AsyncClient",
                        _fake_async_client(response=_FakeResponse(), calls=calls))
    r = client.post("/api/query", headers=AUTH, json={
        "vault": "business-mwe", "question": "Was ist X?"})
    assert r.status_code == 200
    assert r.json() == {"vault": "business-mwe", "answer": "42"}
    # Richtige Instanz (business → 8802) + Dataset des Vaults
    url, payload = calls[0]
    assert url == "http://127.0.0.1:8802/query"
    assert payload == {"question": "Was ist X?", "datasets": ["business-mwe"]}


def test_query_instance_down_returns_502(client, monkeypatch):
    monkeypatch.setattr(gateway.httpx, "AsyncClient",
                        _fake_async_client(exc=httpx.ConnectError("zu")))
    r = client.post("/api/query", headers=AUTH, json={
        "vault": "privat", "question": "Hallo?"})
    assert r.status_code == 502
    assert "nicht erreichbar" in r.json()["detail"]


def test_query_read_error_returns_502(client, monkeypatch):
    # TransportError-Subklassen jenseits von ConnectError/Timeout
    monkeypatch.setattr(gateway.httpx, "AsyncClient",
                        _fake_async_client(exc=httpx.ReadError("abgebrochen")))
    r = client.post("/api/query", headers=AUTH, json={
        "vault": "privat", "question": "Hallo?"})
    assert r.status_code == 502


def test_query_unknown_vault(client):
    r = client.post("/api/query", headers=AUTH, json={
        "vault": "geheim", "question": "x"})
    assert r.status_code == 404
