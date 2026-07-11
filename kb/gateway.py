"""Öffentliches Gateway: Auth, Enqueue, Query-Proxy, PWA-Auslieferung.

Läuft als eigener Prozess OHNE cognee-Import — Ingest geht direkt in die
SQLite-Queue (WAL), Queries werden per HTTP an den Instance Service geproxyt.
"""

import os
import secrets
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from kb.classify import build_payload
from kb.config import (
    INSTANCES,
    ROOT,
    VAULTS,
    UnknownVaultError,
    Vault,
    get_vault,
    queue_path,
    sources_path,
)
from kb.logging_setup import setup_logging
from kb.query_proxy import QueryProxyError, proxy_query, proxy_search
from kb.queue import JobQueue
from kb.sources import (
    CollectionConflictError,
    CollectionRecord,
    CollectionValidationError,
    SourceStore,
)

HEALTH_TIMEOUT = 2.0


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
    collection_ids: list[str] = Field(default_factory=list, max_length=10)

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


class CollectionLabelBody(BaseModel):
    label: str


class CollectionAssignmentBody(BaseModel):
    collection_ids: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("collection_ids")
    @classmethod
    def _unique_ids(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("collection_ids müssen eindeutig sein")
        return value


def _collection_view(store: SourceStore, collection: CollectionRecord) -> dict[str, object]:
    """Öffentliche Darstellung ohne den internen Cognee-NodeSet-Schlüssel."""
    source_count = store.conn.execute(
        "SELECT COUNT(*) FROM source_desired_collections WHERE collection_id=?",
        (collection.id,),
    ).fetchone()[0]
    return {
        "id": collection.id,
        "label": collection.label,
        "state": collection.state,
        "source_count": source_count,
        "created_at": collection.created_at,
        "updated_at": collection.updated_at,
    }


def _assignment_view(collection: CollectionRecord) -> dict[str, str]:
    return {"id": collection.id, "label": collection.label, "state": collection.state}


def _collection_not_found() -> HTTPException:
    # Cross-Vault und unbekannt absichtlich gleich behandeln: keine ID-Existenz leaken.
    return HTTPException(404, "Unbekannte Collection")


def create_app() -> FastAPI:
    setup_logging()
    app = FastAPI(title="kb-gateway")
    api = APIRouter(prefix="/api", dependencies=[Depends(require_token)])

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Pro Request eine Korrelations-ID (Gateway → Instance /query → Logs).
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        # Defense-in-depth: das Bearer-Token liegt im PWA-localStorage. Ein
        # künftiges innerHTML/set:html würde ohne CSP sofort den Token
        # exfiltrieren — CSP macht daraus einen containerten Bruch.
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["Content-Security-Policy"] = (
            "default-src 'self';"
            "connect-src 'self';"
            "script-src 'self';"
            "style-src 'self' 'unsafe-inline';"
            "img-src 'self' data:;"
            "object-src 'none';"
            "base-uri 'none';"
            "frame-ancestors 'none';"
            "manifest-src 'self';"
            "worker-src 'self';"
            "form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @api.post("/ingest", status_code=202)
    def ingest(request: Request, body: IngestBody) -> dict[str, object]:
        v = _resolve_vault(body.vault)
        # Kein Datei-Pfad-Zweig wie im CLI — HTTP-Clients liefern keine lokalen Pfade.
        kind, payload = build_payload(body.content)
        if body.node_set:
            payload["node_set"] = body.node_set
        if body.collection_ids:
            store = SourceStore(sources_path(v.instance))
            try:
                store.validate_collection_ids(v.name, body.collection_ids)
            except CollectionValidationError as exc:
                raise HTTPException(422, str(exc)) from None
            payload["collection_ids"] = body.collection_ids
        payload["request_id"] = request.state.request_id  # für Worker-Log-Korrelation
        # JobQueue pro Request — sqlite3-Verbindungen sind thread-gebunden.
        q = JobQueue(queue_path(v.instance))
        jid = q.enqueue(v.name, kind, payload)
        return {"job_id": jid, "vault": v.name, "kind": kind}

    @api.post("/query")
    async def query(request: Request, body: QueryBody) -> dict[str, object]:
        v = _resolve_vault(body.vault)
        try:
            data = await proxy_query(
                v.instance, body.question, [v.dataset], request_id=request.state.request_id
            )
        except QueryProxyError as e:
            raise HTTPException(502, str(e)) from None
        return {"vault": v.name, **data}

    @api.post("/search")
    async def search(request: Request, body: QueryBody) -> dict[str, object]:
        v = _resolve_vault(body.vault)
        try:
            data = await proxy_search(
                v.instance, body.question, [v.dataset], request_id=request.state.request_id
            )
        except QueryProxyError as e:
            raise HTTPException(502, str(e)) from None
        return {"vault": v.name, **data}

    @api.get("/source/{vault}/{source_id}/raw")
    def source_raw(vault: str, source_id: str) -> FileResponse:
        v = _resolve_vault(vault)
        # SourceStore pro Request — wie JobQueue bei /ingest: sqlite3-Connections
        # sind thread-gebunden, uvicorn fährt den sync-Handler im Thread-Pool.
        store = SourceStore(sources_path(v.instance))
        rec = store.get(source_id)
        # Vault-Scope: Quelle MUSS zum angefragten Vault gehören — sonst Cross-Vault-Leak
        # (Vaults einer Instanz teilen sich die sources.db).
        if rec is None or rec.vault != v.name:
            raise HTTPException(404, "Unbekannte Quelle")
        # Confinement gegen Pfad-Traversal: raw_md_path kommt als Freitext aus
        # der DB und darf nie außerhalb von raw_dir zeigen — sonst genügt ein
        # Schreiber (oder DB-Edit), der von slugify abweicht, für einen
        # authentifizierten Arbitrary-File-Read (.env.gateway, cognee-Daten, …).
        raw_dir = v.raw_dir.resolve()
        p = Path(rec.raw_md_path).resolve()
        if raw_dir != p.parent and raw_dir not in p.parents:
            raise HTTPException(404, "Unbekannte Quelle")
        if not p.is_file():
            raise HTTPException(404, "Rohdatei nicht gefunden")
        return FileResponse(p, media_type="text/markdown")

    @api.get("/jobs/{vault}/{job_id}")
    def job_info(vault: str, job_id: int) -> dict[str, object]:
        v = _resolve_vault(vault)
        q = JobQueue(queue_path(v.instance))
        info = q.info(job_id)
        # Vault-Check: Vaults einer Instanz teilen sich die queue.db —
        # ohne Prüfung würden fremde Job-Fehlertexte leaken.
        if info is None or info["vault"] != v.name:
            raise HTTPException(404, f"Unbekannter Job: {job_id}")
        return {k: info[k] for k in ("id", "status", "kind", "error", "created_at")}

    @api.get("/vaults")
    def vaults() -> list[dict[str, str]]:
        return [{"name": v.name, "instance": v.instance} for v in VAULTS.values()]

    @api.get("/node-sets/{vault}")
    def node_sets(vault: str) -> dict[str, object]:
        v = _resolve_vault(vault)
        q = JobQueue(queue_path(v.instance))
        return {"vault": v.name, "node_sets": q.node_sets(v.name)}

    @api.get("/collections/{vault}")
    def collections(vault: str, include_archived: bool = False) -> dict[str, object]:
        v = _resolve_vault(vault)
        store = SourceStore(sources_path(v.instance))
        records = store.list_collections(v.name, include_archived=include_archived)
        return {
            "vault": v.name,
            "collections": [_collection_view(store, record) for record in records],
        }

    @api.post("/collections/{vault}", status_code=201)
    def create_collection(vault: str, body: CollectionLabelBody) -> dict[str, object]:
        v = _resolve_vault(vault)
        store = SourceStore(sources_path(v.instance))
        try:
            record = store.create_collection(v.name, body.label)
        except CollectionConflictError as exc:
            raise HTTPException(409, str(exc)) from None
        except CollectionValidationError as exc:
            raise HTTPException(422, str(exc)) from None
        return _collection_view(store, record)

    @api.patch("/collections/{vault}/{collection_id}")
    def rename_collection(
        vault: str, collection_id: str, body: CollectionLabelBody
    ) -> dict[str, object]:
        v = _resolve_vault(vault)
        store = SourceStore(sources_path(v.instance))
        try:
            record = store.rename_collection(v.name, collection_id, body.label)
        except CollectionConflictError as exc:
            raise HTTPException(409, str(exc)) from None
        except CollectionValidationError as exc:
            if "gehört nicht" in str(exc):
                raise _collection_not_found() from None
            raise HTTPException(422, str(exc)) from None
        return _collection_view(store, record)

    def _change_collection_state(
        vault: str, collection_id: str, *, restore: bool
    ) -> dict[str, object]:
        v = _resolve_vault(vault)
        store = SourceStore(sources_path(v.instance))
        try:
            record = (
                store.restore_collection(v.name, collection_id)
                if restore
                else store.archive_collection(v.name, collection_id)
            )
        except CollectionValidationError as exc:
            if "gehört nicht" in str(exc):
                raise _collection_not_found() from None
            raise HTTPException(422, str(exc)) from None
        return _collection_view(store, record)

    @api.post("/collections/{vault}/{collection_id}/archive")
    def archive_collection(vault: str, collection_id: str) -> dict[str, object]:
        return _change_collection_state(vault, collection_id, restore=False)

    @api.post("/collections/{vault}/{collection_id}/restore")
    def restore_collection(vault: str, collection_id: str) -> dict[str, object]:
        return _change_collection_state(vault, collection_id, restore=True)

    @api.get("/sources/{vault}")
    def sources(vault: str) -> dict[str, object]:
        # Quellen-Liste eines Vaults für die Management-Ansicht (neueste zuerst).
        # SourceStore pro Request (sqlite3 thread-gebunden). raw_md_path bewusst
        # nicht ausgeliefert (intern); der Raw-Download läuft ohnehin über
        # /source/{vault}/{source_id}/raw.
        v = _resolve_vault(vault)
        store = SourceStore(sources_path(v.instance))
        recs = store.list_by_vault(v.name)
        return {
            "vault": v.name,
            "sources": [
                {
                    "source_id": r.id,
                    "type": r.type,
                    "url": r.url,
                    "title": r.title,
                    "fetched_at": r.fetched_at,
                }
                for r in recs
            ],
        }

    @api.get("/sources/{vault}/{source_id}/collections")
    def source_collections(vault: str, source_id: str) -> dict[str, object]:
        v = _resolve_vault(vault)
        store = SourceStore(sources_path(v.instance))
        source = store.get(source_id)
        if source is None or source.vault != v.name:
            raise HTTPException(404, "Unbekannte Quelle")
        sync = store.get_collection_sync(source_id)
        desired = [
            store.get_collection(v.name, collection_id)
            for collection_id in store.desired_collection_ids(source_id)
        ]
        indexed = [
            store.get_collection(v.name, collection_id)
            for collection_id in store.indexed_collection_ids(source_id)
        ]
        return {
            "vault": v.name,
            "source_id": source_id,
            "desired_collections": [_assignment_view(record) for record in desired],
            "indexed_collections": [_assignment_view(record) for record in indexed],
            "collection_revision": sync.collection_revision,
            "indexed_collection_revision": sync.indexed_collection_revision,
            "sync_status": sync.collection_sync_status,
            "sync_error": sync.collection_sync_error,
            "sync_updated_at": sync.collection_sync_updated_at,
        }

    @api.put("/sources/{vault}/{source_id}/collections", status_code=202)
    def reassign_source_collections(
        vault: str, source_id: str, body: CollectionAssignmentBody
    ) -> dict[str, object]:
        v = _resolve_vault(vault)
        store = SourceStore(sources_path(v.instance))
        source = store.get(source_id)
        if source is None or source.vault != v.name:
            raise HTTPException(404, "Unbekannte Quelle")
        try:
            sync = store.replace_desired_collections(source_id, body.collection_ids)
            queue = JobQueue(queue_path(v.instance))
            store.dispatch_reindex_events(queue)
        except CollectionValidationError as exc:
            raise HTTPException(422, str(exc)) from None
        return {
            "source_id": source_id,
            "collection_revision": sync.collection_revision,
            "sync_status": sync.collection_sync_status,
        }

    app.include_router(api)

    @app.get("/api/health")  # bewusst ohne Token-Pflicht (Monitoring)
    async def health(authorization: str | None = Header(default=None)) -> dict[str, object]:
        # Instanz-/Wall-Namen sind ein Privacy-Signal — unauthentifiziert gibt es
        # nur ein Gateway-OK; die detaillierte Instanz-Map nur mit gültigem Token.
        expected = os.environ.get("KB_API_TOKEN")
        provided = (authorization or "").removeprefix("Bearer ")
        if not (expected and secrets.compare_digest(provided, expected)):
            return {"gateway": "ok"}
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
