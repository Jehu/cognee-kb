import httpx
import pytest
from fastapi.testclient import TestClient

from kb import gateway
from kb.queue import JobQueue
from kb.sources import SourceRecord, SourceStore

TOKEN = "test-token-123"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("KB_API_TOKEN", TOKEN)
    monkeypatch.setattr("kb.gateway.queue_path", lambda inst: tmp_path / f"{inst}.db")
    return TestClient(gateway.create_app())


# --- Fake-httpx für den Query-Proxy (respx ist nicht installiert) ---


class _FakeResponse:
    status_code = 200

    def json(self):
        return {"answer": "42", "citations": [], "gaps": []}


def _fake_async_client(response=None, exc=None, calls=None):
    """Baut einen httpx.AsyncClient-Ersatz, der post/get abfängt."""

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def post(self, url, json=None, headers=None):
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
    r = client.get("/api/vaults", headers={"Authorization": "Bearer falsch"})
    assert r.status_code == 401


def test_security_headers_present(client):
    # Defense-in-depth für den localStorage-Token: jede Antwort trägt CSP +
    # Hardening-Header (auch die StaticFiles-Auslieferung der PWA).
    r = client.get("/api/vaults", headers=AUTH)
    assert r.status_code == 200
    assert "script-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Referrer-Policy"] == "no-referrer"
    assert r.headers["X-Frame-Options"] == "DENY"


def test_response_carries_request_id(client):
    # Jede Antwort trägt eine Korrelations-ID; eine mitgesendete wird übernommen.
    r = client.get("/api/vaults", headers=AUTH)
    assert r.headers.get("X-Request-ID")
    r2 = client.get("/api/vaults", headers={**AUTH, "X-Request-ID": "fixed-id-123"})
    assert r2.headers["X-Request-ID"] == "fixed-id-123"


def test_health_needs_no_token(client, monkeypatch):
    # Unauthentifiziert: Gateway lebt, aber KEINE Instanz-/Wall-Namen (Privacy).
    monkeypatch.setattr(
        gateway.httpx, "AsyncClient", _fake_async_client(exc=httpx.ConnectError("zu"))
    )
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["gateway"] == "ok"
    assert "instances" not in body


def test_health_instances_map_requires_token(client, monkeypatch):
    # Mit Token: die Instanz-Map kommt zurück (Wall-Namen + Liveness).
    monkeypatch.setattr(
        gateway.httpx, "AsyncClient", _fake_async_client(exc=httpx.ConnectError("zu"))
    )
    r = client.get("/api/health", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["gateway"] == "ok"
    assert set(body["instances"].values()) == {"down"}


# --- Ingest ---


def test_ingest_enqueues_youtube(client, tmp_path):
    r = client.post(
        "/api/ingest",
        headers=AUTH,
        json={"vault": "privat", "content": "https://youtu.be/dQw4w9WgXcQ", "node_set": "musik"},
    )
    assert r.status_code == 202
    body = r.json()
    assert body["vault"] == "privat"
    assert body["kind"] == "youtube"
    # Job liegt wirklich in der Queue der Instanz
    info = JobQueue(tmp_path / "local.db").info(body["job_id"])
    assert info is not None
    assert info["status"] == "pending"
    assert info["kind"] == "youtube"


def test_ingest_plain_text_stays_snippet(client):
    r = client.post(
        "/api/ingest", headers=AUTH, json={"vault": "business-ki", "content": "Nur ein Gedanke."}
    )
    assert r.status_code == 202
    assert r.json()["kind"] == "snippet"


def test_ingest_unknown_vault(client):
    r = client.post("/api/ingest", headers=AUTH, json={"vault": "geheim", "content": "x"})
    assert r.status_code == 404


def test_ingest_blank_content_rejected(client):
    # Leerer bzw. Nur-Whitespace-Content → Validierungsfehler
    for content in ("", "   \n\t "):
        r = client.post("/api/ingest", headers=AUTH, json={"vault": "privat", "content": content})
        assert r.status_code == 422


# --- Vaults + Jobs ---


def test_vaults_lists_config(client):
    r = client.get("/api/vaults", headers=AUTH)
    assert r.status_code == 200
    names = {v["name"]: v["instance"] for v in r.json()}
    assert names["privat"] == "local"
    assert names["business-ki"] == "cloud"


def test_node_sets_lists_existing_sets_for_vault(client):
    client.post(
        "/api/ingest",
        headers=AUTH,
        json={"vault": "privat", "content": "Notiz A", "node_set": "projekt-a"},
    )
    client.post(
        "/api/ingest",
        headers=AUTH,
        json={"vault": "privat", "content": "Notiz B", "node_set": "projekt-b"},
    )
    client.post(
        "/api/ingest",
        headers=AUTH,
        json={"vault": "business-ki", "content": "Notiz C", "node_set": "fremd"},
    )

    r = client.get("/api/node-sets/privat", headers=AUTH)

    assert r.status_code == 200
    assert r.json() == {"vault": "privat", "node_sets": ["projekt-a", "projekt-b"]}


def test_node_sets_requires_known_vault(client):
    r = client.get("/api/node-sets/geheim", headers=AUTH)
    assert r.status_code == 404


def test_job_info_after_enqueue(client):
    jid = client.post(
        "/api/ingest", headers=AUTH, json={"vault": "privat", "content": "Notiz"}
    ).json()["job_id"]
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
    jid = client.post(
        "/api/ingest", headers=AUTH, json={"vault": "business-ki", "content": "Notiz"}
    ).json()["job_id"]
    r = client.get(f"/api/jobs/business-mwe/{jid}", headers=AUTH)
    assert r.status_code == 404
    # Über den richtigen Vault weiterhin sichtbar
    assert client.get(f"/api/jobs/business-ki/{jid}", headers=AUTH).status_code == 200


# --- Query-Proxy ---


def test_query_proxies_to_instance(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        gateway.httpx, "AsyncClient", _fake_async_client(response=_FakeResponse(), calls=calls)
    )
    r = client.post(
        "/api/query", headers=AUTH, json={"vault": "business-mwe", "question": "Was ist X?"}
    )
    assert r.status_code == 200
    assert r.json() == {
        "vault": "business-mwe",
        "answer": "42",
        "citations": [],
        "gaps": [],
    }
    # Richtige Instanz (cloud → 8802) + Dataset des Vaults
    url, payload = calls[0]
    assert url == "http://127.0.0.1:8802/query"
    assert payload == {"question": "Was ist X?", "datasets": ["business-mwe"]}


def test_query_instance_down_returns_502(client, monkeypatch):
    monkeypatch.setattr(
        gateway.httpx, "AsyncClient", _fake_async_client(exc=httpx.ConnectError("zu"))
    )
    r = client.post("/api/query", headers=AUTH, json={"vault": "privat", "question": "Hallo?"})
    assert r.status_code == 502
    assert "nicht erreichbar" in r.json()["detail"]


def test_query_read_error_returns_502(client, monkeypatch):
    # TransportError-Subklassen jenseits von ConnectError/Timeout
    monkeypatch.setattr(
        gateway.httpx, "AsyncClient", _fake_async_client(exc=httpx.ReadError("abgebrochen"))
    )
    r = client.post("/api/query", headers=AUTH, json={"vault": "privat", "question": "Hallo?"})
    assert r.status_code == 502


def test_query_unknown_vault(client):
    r = client.post("/api/query", headers=AUTH, json={"vault": "geheim", "question": "x"})
    assert r.status_code == 404


def test_search_proxies_retrieval_without_answer(client, monkeypatch):
    async def fake_proxy(instance, question, datasets, request_id=None):
        assert instance == "cloud"
        assert datasets == ["business-mwe"]
        return {
            "answer": None,
            "evidence": [{"evidence_id": "e1", "rank": 1}],
            "sources": [],
        }

    monkeypatch.setattr("kb.gateway.proxy_search", fake_proxy)
    r = client.post(
        "/api/search",
        headers=AUTH,
        json={"vault": "business-mwe", "question": "Belege?"},
    )

    assert r.status_code == 200
    assert r.json()["evidence"] == [{"evidence_id": "e1", "rank": 1}]


# --- Raw-Source-Endpoint ---


@pytest.fixture
def source_client(tmp_path, monkeypatch):
    """Client mit gepatchtem sources_path und raw_dir (business-mwe → cloud-Instanz)."""
    monkeypatch.setenv("KB_API_TOKEN", TOKEN)
    monkeypatch.setattr("kb.gateway.queue_path", lambda inst: tmp_path / f"{inst}.db")
    monkeypatch.setattr("kb.gateway.sources_path", lambda inst: tmp_path / f"{inst}_sources.db")
    # raw_dir auf tmp umleiten, damit der Confinement-Check echte Pfade nutzt.
    from kb.config import Vault
    from kb.config import get_vault as _real_get_vault

    def _fake_get_vault(name):
        real = _real_get_vault(name)
        return Vault(
            name=real.name,
            instance=real.instance,
            dataset=real.dataset,
            raw_dir=tmp_path / "raw" / name,
        )

    monkeypatch.setattr("kb.gateway.get_vault", _fake_get_vault)
    return TestClient(gateway.create_app())


def _insert_source_record(
    tmp_path, source_id: str, vault: str, raw_md_path: str, instance: str = "cloud"
) -> None:
    """Hilfsfunktion: Record in die gemockte sources.db einfügen."""
    store = SourceStore(tmp_path / f"{instance}_sources.db")
    rec = SourceRecord(
        id=source_id,
        type="snippet",
        url=None,
        video_id=None,
        locator=None,
        fetched_at="2026-01-01T00:00:00Z",
        vault=vault,
        raw_md_path=raw_md_path,
        title="Testquelle",
    )
    store.insert(rec)


def test_source_raw_returns_markdown(source_client, tmp_path):
    # Datei liegt UNTER raw_dir — Confinement lässt sie durch.
    raw_dir = tmp_path / "raw" / "business-mwe"
    raw_dir.mkdir(parents=True)
    md = raw_dir / "x.md"
    md.write_text("# Hallo\nInhalt hier.")
    _insert_source_record(tmp_path, "src1", "business-mwe", str(md))
    r = source_client.get("/api/source/business-mwe/src1/raw", headers=AUTH)
    assert r.status_code == 200
    assert "Inhalt hier" in r.text


def test_source_raw_requires_token(source_client, tmp_path):
    md = tmp_path / "x.md"
    md.write_text("geheim")
    _insert_source_record(tmp_path, "src2", "business-mwe", str(md))
    r = source_client.get("/api/source/business-mwe/src2/raw")
    assert r.status_code == 401


def test_source_raw_unknown_id_returns_404(source_client):
    r = source_client.get("/api/source/business-mwe/nichtexistent/raw", headers=AUTH)
    assert r.status_code == 404


def test_source_raw_cross_vault_blocked(source_client, tmp_path):
    # Record gehört zu "business-ki", Abruf über "business-mwe" → 404 (kein Leak)
    md = tmp_path / "y.md"
    md.write_text("vertraulich")
    _insert_source_record(tmp_path, "src3", "business-ki", str(md))
    r = source_client.get("/api/source/business-mwe/src3/raw", headers=AUTH)
    assert r.status_code == 404


def test_source_raw_missing_file_returns_404(source_client, tmp_path):
    # Record existiert, Pfad liegt unter raw_dir, aber die Datei fehlt auf Platte.
    raw_dir = tmp_path / "raw" / "business-mwe"
    raw_dir.mkdir(parents=True, exist_ok=True)
    _insert_source_record(tmp_path, "src4", "business-mwe", str(raw_dir / "weg.md"))
    r = source_client.get("/api/source/business-mwe/src4/raw", headers=AUTH)
    assert r.status_code == 404


def test_source_raw_rejects_path_outside_raw_dir(source_client, tmp_path):
    # Datei existiert, liegt aber AUSSERHALB von raw_dir -> Confinement -> 404
    # (beweist, dass der 404 vom Confinement kommt, nicht vom fehlenden File).
    outside = tmp_path / "secret.md"
    outside.write_text("soll nicht ausgeliefert werden")
    _insert_source_record(tmp_path, "src5", "business-mwe", str(outside))
    r = source_client.get("/api/source/business-mwe/src5/raw", headers=AUTH)
    assert r.status_code == 404


# --- Sources list (/api/sources/{vault}) ---


def _src(source_id, vault, title, type_="snippet", fetched_at="2026-06-01T00:00:00Z"):
    return SourceRecord(
        id=source_id,
        type=type_,
        url=None,
        video_id=None,
        locator=None,
        fetched_at=fetched_at,
        vault=vault,
        raw_md_path="raw/x.md",
        title=title,
    )


def test_sources_lists_only_requested_vault(client, tmp_path, monkeypatch):
    monkeypatch.setattr("kb.gateway.sources_path", lambda inst: tmp_path / f"{inst}_sources.db")
    store = SourceStore(tmp_path / "cloud_sources.db")
    store.insert(_src("s1", "business-mwe", "Notiz 1"))
    store.insert(_src("s2", "business-ki", "Fremder Vault"))  # anderer Vault
    r = client.get("/api/sources/business-mwe", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["vault"] == "business-mwe"
    assert [s["source_id"] for s in body["sources"]] == ["s1"]
    assert body["sources"][0]["title"] == "Notiz 1"
    # raw_md_path ist intern und wird bewusst nicht ausgeliefert.
    assert "raw_md_path" not in body["sources"][0]


def test_sources_requires_token(client, tmp_path, monkeypatch):
    monkeypatch.setattr("kb.gateway.sources_path", lambda inst: tmp_path / f"{inst}_sources.db")
    r = client.get("/api/sources/business-mwe")
    assert r.status_code == 401


def test_sources_unknown_vault(client):
    r = client.get("/api/sources/geheim", headers=AUTH)
    assert r.status_code == 404
