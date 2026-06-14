import asyncio
import hashlib
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


async def process_one_async(instance: Instance | None, q: JobQueue,
                            store: SourceStore) -> bool:
    """Verarbeitet genau einen Job. True = es gab Arbeit, False = Queue leer."""
    job = q.claim_next()
    if job is None:
        return False
    try:
        vault = get_vault(job.vault)
        # _fetch ist blockierendes I/O (HTTP, Datei) — nicht den Loop blockieren
        doc = await asyncio.to_thread(_fetch, job.kind, job.payload)
        # Dedup: identischer Body im selben Vault wird nicht erneut ingestet
        # (cognee dedupt intern per Hash, unsere raw-/Source-Schicht bisher nicht
        # — sonst doppelte Quellen-Chips). mark_done, nicht failed: kein Fehler.
        content_hash = hashlib.sha256(doc.body.encode("utf-8")).hexdigest()
        if store.find_by_hash(content_hash, vault.name) is not None:
            print(f"[worker] job {job.id}: Duplikat (gleicher Inhalt in "
                  f"{vault.name}) — übersprungen", file=sys.stderr)
            q.mark_done(job.id)
            return True
        record = SourceRecord.new(
            type=job.kind, url=doc.url, video_id=doc.video_id,
            locator=doc.locator, vault=vault.name, raw_md_path="",
            title=doc.title, content_hash=content_hash)
        path, record = rawstore.write_raw(vault.raw_dir, doc.title, doc.body, record)
        store.insert(record)
        # Stufe 1.5: node_set fällt per Default auf record.id zurück, damit jedes
        # Dokument eine deterministische belongs_to_set-Kante trägt (Vorbereitung
        # für späteren CYPHER-Herkunfts-Fallback). Ändert den Stufe-1-Pfad nicht.
        node_set = job.payload.get("node_set") or record.id
        await cognee_io.ingest(
            instance, path, vault.dataset,
            node_sets=node_set if isinstance(node_set, list) else [node_set])
        q.mark_done(job.id)
    except Exception as e:  # noqa: BLE001 — Worker darf nie sterben
        # Fängt nur Job-Fehler: asyncio.CancelledError ist BaseException und
        # läuft hier durch — die Loop-Cancellation bleibt damit intakt.
        print(f"[worker] job {job.id} failed: {type(e).__name__}: {e}",
              file=sys.stderr)
        q.mark_failed(job.id, f"{type(e).__name__}: {e}")
    return True


def process_one(instance: Instance | None, q: JobQueue, store: SourceStore,
                loop: asyncio.AbstractEventLoop | None = None) -> bool:
    """Dünner sync-Wrapper um process_one_async — Signatur bleibt CLI-kompatibel."""
    coro = process_one_async(instance, q, store)
    if loop is not None:
        return loop.run_until_complete(coro)
    return asyncio.run(coro)


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


async def run_forever_async(instance: Instance, q: JobQueue, store: SourceStore,
                            poll_seconds: float = 5.0) -> None:
    """Worker-Schleife für den Instance Service (Phase 2).

    KEIN Env-Load und KEIN recover_stale — beides macht der Service beim Start.
    Läuft auf dem Loop des Aufrufers (damit cognee seine loop-gebundenen
    Ressourcen über alle Jobs hinweg wiederverwenden kann) und ist sauber per
    asyncio.CancelledError abbrechbar: process_one_async schluckt die
    Cancellation nicht, await asyncio.sleep reicht sie ebenfalls durch.
    """
    while True:
        if not await process_one_async(instance, q, store):
            await asyncio.sleep(poll_seconds)
