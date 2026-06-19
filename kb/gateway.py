"""Öffentliches Gateway: Auth, Enqueue, Query-Proxy, PWA-Auslieferung.

Läuft als eigener Prozess OHNE cognee-Import — Ingest geht direkt in die
SQLite-Queue (WAL), Queries werden per HTTP an den Instance Service geproxyt.
"""

import os
import secrets
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from kb.classify import build_payload
from kb.config import (
    INSTANCES,
    ROOT,
    VAULTS,
    UnknownVaultError,
    Vault,
    get_instance,
    get_vault,
)
from kb.queue import JobQueue
from kb.sources import SourceStore

QUERY_TIMEOUT = 120.0   # GRAPH_COMPLETION kann dauern
HEALTH_TIMEOUT = 2.0


def queue_path(instance_name: str) -> Path:
    return get_instance(instance_name).var_dir / "queue.db"


def sources_path(instance_name: str) -> Path:
    return get_instance(instance_name).var_dir / "sources.db"


def require_token(authorization: str | None = Header(default=None)) -> None:
    # Token erst beim Request lesen — Tests setzen die Env via monkeypatch.
    expected = os.environ.get("KB_API_TOKEN")
    # compare_digest: timing-safe, verrät keine Übereinstimmungslänge.
    provided = (authorization or "").removeprefix("Bearer ")
    if not expected or not secrets.compare_digest(provided, expected):
        raise HTTPException(401, "Fehlendes oder ungültiges Token")


def _resolve_vault(name: str) -> Vault:
    try:
        return get_vault(name)
    except UnknownVaultError:
        raise HTTPException(404, f"Unbekannter Vault: {name}") from None


class IngestBody(BaseModel):
    vault: str
    content: str = Field(min_length=1)
    node_set: str | None = None

    @field_validator("content")
    @classmethod
    def _content_not_blank(cls, v: str) -> str:
        # Nur-Whitespace-Content abfangen — gestrippt weiterreichen.
        v = v.strip()
        if not v:
            raise ValueError("content darf nicht leer sein")
        return v


class QueryBody(BaseModel):
    vault: str
    question: str


def create_app() -> FastAPI:
    app = FastAPI(title="kb-gateway")
    api = APIRouter(prefix="/api", dependencies=[Depends(require_token)])

    @api.post("/ingest", status_code=202)
    def ingest(body: IngestBody) -> dict:
        v = _resolve_vault(body.vault)
        # Kein Datei-Pfad-Zweig wie im CLI — HTTP-Clients liefern keine lokalen Pfade.
        kind, payload = build_payload(body.content)
        if body.node_set:
            payload["node_set"] = body.node_set
        # JobQueue pro Request — sqlite3-Verbindungen sind thread-gebunden.
        q = JobQueue(queue_path(v.instance))
        jid = q.enqueue(v.name, kind, payload)
        return {"job_id": jid, "vault": v.name, "kind": kind}

    @api.post("/query")
    async def query(body: QueryBody) -> dict:
        v = _resolve_vault(body.vault)
        inst = get_instance(v.instance)
        try:
            async with httpx.AsyncClient(timeout=QUERY_TIMEOUT) as client:
                r = await client.post(
                    f"http://127.0.0.1:{inst.port}/query",
                    json={"question": body.question, "datasets": [v.dataset]})
        # TransportError deckt ConnectError, Timeouts, ReadError,
        # RemoteProtocolError etc. ab (geprüfte Subklassen-Hierarchie).
        except httpx.TransportError:
            raise HTTPException(
                502, f"Instance Service '{inst.name}' (Port {inst.port}) "
                     "nicht erreichbar — läuft `kb serve-instance`?") from None
        if r.status_code != 200:
            raise HTTPException(
                502, f"Instance Service '{inst.name}' antwortete mit {r.status_code}")
        body = r.json()
        return {"vault": v.name, "answer": body["answer"], "sources": body.get("sources", [])}

    @api.get("/source/{vault}/{source_id}/raw")
    def source_raw(vault: str, source_id: str):
        v = _resolve_vault(vault)
        # SourceStore pro Request — wie JobQueue bei /ingest: sqlite3-Connections
        # sind thread-gebunden, uvicorn fährt den sync-Handler im Thread-Pool.
        store = SourceStore(sources_path(v.instance))
        rec = store.get(source_id)
        # Vault-Scope: Quelle MUSS zum angefragten Vault gehören — sonst Cross-Vault-Leak
        # (Vaults einer Instanz teilen sich die sources.db).
        if rec is None or rec.vault != v.name:
            raise HTTPException(404, "Unbekannte Quelle")
        p = Path(rec.raw_md_path)
        if not p.is_file():
            raise HTTPException(404, "Rohdatei nicht gefunden")
        return FileResponse(p, media_type="text/markdown")

    @api.get("/jobs/{vault}/{job_id}")
    def job_info(vault: str, job_id: int) -> dict:
        v = _resolve_vault(vault)
        q = JobQueue(queue_path(v.instance))
        info = q.info(job_id)
        # Vault-Check: Vaults einer Instanz teilen sich die queue.db —
        # ohne Prüfung würden fremde Job-Fehlertexte leaken.
        if info is None or info["vault"] != v.name:
            raise HTTPException(404, f"Unbekannter Job: {job_id}")
        return {k: info[k] for k in ("id", "status", "kind", "error", "created_at")}

    @api.get("/vaults")
    def vaults() -> list[dict]:
        return [{"name": v.name, "instance": v.instance} for v in VAULTS.values()]

    @api.get("/node-sets/{vault}")
    def node_sets(vault: str) -> dict:
        v = _resolve_vault(vault)
        q = JobQueue(queue_path(v.instance))
        return {"vault": v.name, "node_sets": q.node_sets(v.name)}

    app.include_router(api)

    @app.get("/api/health")  # bewusst ohne Token (Monitoring)
    async def health() -> dict:
        instances = {}
        async with httpx.AsyncClient(timeout=HEALTH_TIMEOUT) as client:
            for name, inst in INSTANCES.items():
                try:
                    r = await client.get(f"http://127.0.0.1:{inst.port}/health")
                    instances[name] = "ok" if r.status_code == 200 else "down"
                except httpx.HTTPError:
                    instances[name] = "down"
        return {"gateway": "ok", "instances": instances}

    # PWA zuletzt mounten, damit /api-Routen Vorrang behalten.
    dist = ROOT / "web" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="pwa")

    return app
