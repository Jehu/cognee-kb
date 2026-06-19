"""Prozess-eigener Service einer Instanz: Worker-Loop + /query im SELBEN Event-Loop.

Cognee cachet loop-gebundene Ressourcen — der Worker läuft deshalb als
asyncio-Background-Task im Loop der FastAPI-App (kein Thread, kein neuer Loop).
Bindet nur an 127.0.0.1, kein Token (siehe Phase-2-Plan).
"""

import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from kb import cognee_io, guard, worker
from kb.config import get_instance
from kb.queue import JobQueue
from kb.sources import SourceStore


class QueryBody(BaseModel):
    question: str
    datasets: list[str]


def _log_worker_death(task: asyncio.Task[None]) -> None:
    """Macht einen unerwartet gestorbenen Worker-Task auf stderr sichtbar."""
    if task.cancelled():
        return  # regulärer Shutdown
    exc = task.exception()
    if exc is not None:
        print(f"[instance] Worker-Task gestorben: {type(exc).__name__}: {exc}", file=sys.stderr)


def create_app(instance_name: str) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        inst = get_instance(instance_name)
        cognee_io.load_instance_env(inst)
        guard.assert_instance_env(inst)  # Fehler propagiert — Start bricht ab
        q = JobQueue(inst.var_dir / "queue.db")
        store = SourceStore(inst.var_dir / "sources.db")
        q.recover_stale()  # genau ein Worker pro Instanz — gefahrlos
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

    app = FastAPI(title=f"kb-instance-{instance_name}", lifespan=lifespan)

    # Endpoints bewusst async def: sie laufen damit im Lifespan-Thread des
    # Event-Loops — dieselbe sqlite3-Connection ist so threadsicher nutzbar.

    @app.post("/query")
    async def query(body: QueryBody) -> dict[str, object]:
        answer, source_ids = await cognee_io.query_with_sources(
            app.state.inst, body.question, datasets=body.datasets
        )
        sources = []
        for sid in source_ids:
            rec = app.state.store.get(sid)
            if rec is None:
                continue
            sources.append(
                {
                    "source_id": rec.id,
                    "type": rec.type,
                    "url": rec.url,
                    "locator": rec.locator,
                    "raw_md_path": rec.raw_md_path,
                    "title": rec.title,
                }
            )
        return {"answer": answer, "sources": sources}

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
