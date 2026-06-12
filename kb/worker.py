import asyncio
import sys
import time
from pathlib import Path

from kb import cognee_io, fetch_web, fetch_youtube, rawstore
from kb.config import Instance, get_vault
from kb.fetch_youtube import FetchedDoc
from kb.queue import JobQueue
from kb.sources import SourceRecord, SourceStore


def _fetch(kind: str, payload: dict) -> FetchedDoc:
    if kind == "youtube":
        return fetch_youtube.fetch(payload["url"], payload["video_id"])
    if kind == "web":
        return fetch_web.fetch(payload["url"])
    if kind == "snippet":
        return FetchedDoc(title=payload.get("title", "Snippet"),
                          body=payload["text"])
    if kind == "file":
        p = Path(payload["path"])
        return FetchedDoc(title=p.stem, body=p.read_text(), locator=str(p))
    raise ValueError(f"Unbekannter Job-Typ: {kind}")


def process_one(instance: Instance | None, q: JobQueue, store: SourceStore,
                loop: asyncio.AbstractEventLoop | None = None) -> bool:
    """Verarbeitet genau einen Job. True = es gab Arbeit, False = Queue leer."""
    job = q.claim_next()
    if job is None:
        return False
    try:
        vault = get_vault(job.vault)
        doc = _fetch(job.kind, job.payload)
        record = SourceRecord.new(
            type=job.kind, url=doc.url, video_id=doc.video_id,
            locator=doc.locator, vault=vault.name, raw_md_path="")
        path, record = rawstore.write_raw(vault.raw_dir, doc.title, doc.body, record)
        store.insert(record)
        node_set = job.payload.get("node_set")
        coro = cognee_io.ingest(
            instance, path, vault.dataset,
            node_sets=node_set if isinstance(node_set, list)
            else ([node_set] if node_set else []))
        if loop is not None:
            loop.run_until_complete(coro)
        else:
            asyncio.run(coro)
        q.mark_done(job.id)
    except Exception as e:  # noqa: BLE001 — Worker darf nie sterben
        print(f"[worker] job {job.id} failed: {type(e).__name__}: {e}",
              file=sys.stderr)
        q.mark_failed(job.id, f"{type(e).__name__}: {e}")
    return True


def run_forever(instance: Instance, q: JobQueue, store: SourceStore,
                poll_seconds: float = 5.0) -> None:
    cognee_io.load_instance_env(instance)
    q.recover_stale()  # genau ein Worker pro Instanz — verwaiste Jobs gefahrlos zurücksetzen
    # EIN Loop für alle Jobs — cognee cachet loop-gebundene Ressourcen
    # (siehe _answer_all in cli.py), frischer Loop pro Job riskiert
    # 'attached to a different loop'-Fehler.
    loop = asyncio.new_event_loop()
    try:
        while True:
            if not process_one(instance, q, store, loop=loop):
                time.sleep(poll_seconds)
    finally:
        loop.close()
