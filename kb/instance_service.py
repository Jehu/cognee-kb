"""Prozess-eigener Service einer Instanz: Worker-Loop + /query im SELBEN Event-Loop.

Cognee cachet loop-gebundene Ressourcen — der Worker läuft deshalb als
asyncio-Background-Task im Loop der FastAPI-App (kein Thread, kein neuer Loop).
Bindet nur an 127.0.0.1, kein Token (siehe Phase-2-Plan).
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException

from kb import cognee_io, guard, query_service, worker
from kb.config import get_instance
from kb.logging_setup import setup_logging
from kb.query_models import QueryRequest
from kb.queue import JobQueue
from kb.sources import SourceRecord, SourceStore

logger = logging.getLogger("kb.instance")


def _source_payload(record: SourceRecord) -> dict[str, object]:
    return {
        "source_id": record.id,
        "type": record.type,
        "url": record.url,
        "locator": record.locator,
        "raw_md_path": record.raw_md_path,
        "title": record.title,
    }


def _resolve_sources(
    store: SourceStore, source_ids: set[str], allowed_vaults: set[str]
) -> list[dict[str, object]]:
    sources = []
    for source_id in source_ids:
        record = store.get(source_id)
        if record is not None and record.vault in allowed_vaults:
            sources.append(_source_payload(record))
    return sources


def _log_worker_death(task: asyncio.Task[None]) -> None:
    """Macht einen unerwartet gestorbenen Worker-Task im Log sichtbar."""
    if task.cancelled():
        return  # regulärer Shutdown
    exc = task.exception()
    if exc is not None:
        logger.error("Worker-Task gestorben: %s: %s", type(exc).__name__, exc)


def create_app(instance_name: str) -> FastAPI:
    setup_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        inst = get_instance(instance_name)
        cognee_io.load_instance_env(inst)
        guard.assert_instance_env(inst)  # Fehler propagiert — Start bricht ab
        q = JobQueue(inst.var_dir / "queue.db")
        store = SourceStore(inst.var_dir / "sources.db")
        q.recover_stale()  # genau ein Worker pro Instanz — gefahrlos
        store.dispatch_reindex_events(q)  # Outbox-Crash-Lücken vor Workerstart schließen
        # Selber Event-Loop wie die Request-Handler — kein Thread, kein neuer Loop.
        task = asyncio.create_task(worker.run_forever_async(inst, q, store))
        task.add_done_callback(_log_worker_death)
        app.state.inst = inst
        app.state.q = q
        app.state.store = store
        app.state.worker_task = task
        app.state.shutting_down = False
        try:
            yield
        finally:
            app.state.shutting_down = True
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001 — Tod bereits via Callback geloggt
                pass
            # SQLite-Connections sauber schließen (WAL-Checkpoint), nachdem der
            # Worker-Task beendet ist — nur aufräumen, was wirklich existiert.
            for attr in ("q", "store"):
                obj = getattr(app.state, attr, None)
                if obj is not None:
                    obj.close()

    app = FastAPI(title=f"kb-instance-{instance_name}", lifespan=lifespan)

    # Endpoints bewusst async def: sie laufen damit im Lifespan-Thread des
    # Event-Loops — dieselbe sqlite3-Connection ist so threadsicher nutzbar.

    @app.post("/query")
    async def query(
        body: QueryRequest, x_request_id: str | None = Header(default=None, alias="X-Request-ID")
    ) -> dict[str, object]:
        logger.info(
            "query instance=%s datasets=%s request_id=%s",
            instance_name,
            body.datasets,
            x_request_id,
        )
        try:
            kwargs = {"datasets": body.datasets, "store": app.state.store}
            if body.collection_ids is not None:
                kwargs["collection_ids"] = body.collection_ids
            result = await query_service.answer(app.state.inst, body.question, **kwargs)
        except query_service.QueryScopeError as exc:
            raise HTTPException(422, str(exc)) from None
        source_ids = {sid for citation in result.citations for sid in citation.source_ids}
        sources = _resolve_sources(app.state.store, source_ids, set(body.datasets))
        return {**result.model_dump(), "sources": sources}

    @app.post("/search")
    async def search(
        body: QueryRequest, x_request_id: str | None = Header(default=None, alias="X-Request-ID")
    ) -> dict[str, object]:
        logger.info(
            "search instance=%s datasets=%s request_id=%s",
            instance_name,
            body.datasets,
            x_request_id,
        )
        try:
            kwargs = {"datasets": body.datasets, "store": app.state.store}
            if body.collection_ids is not None:
                kwargs["collection_ids"] = body.collection_ids
            result = await query_service.search(app.state.inst, body.question, **kwargs)
        except query_service.QueryScopeError as exc:
            raise HTTPException(422, str(exc)) from None
        source_ids = {sid for item in result.evidence for sid in item.source_ids}
        sources = _resolve_sources(app.state.store, source_ids, set(body.datasets))
        return {**result.model_dump(), "sources": sources}

    @app.get("/health")
    async def health() -> dict[str, object]:
        # "dead" = Worker-Task unerwartet beendet (nicht im Shutdown).
        dead = app.state.worker_task.done() and not app.state.shutting_down
        return {
            "instance": app.state.inst.name,
            "queue": app.state.q.counts(),
            "worker": "dead" if dead else "ok",
        }

    return app
