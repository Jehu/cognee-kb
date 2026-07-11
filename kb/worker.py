import asyncio
import hashlib
import logging
import time
from pathlib import Path
from typing import Any

from kb import cognee_io, fetch_pdf, fetch_web, fetch_youtube, rawstore
from kb.config import Instance, get_vault
from kb.fetch_youtube import FetchedDoc
from kb.logging_setup import setup_logging
from kb.queue import JobQueue
from kb.sources import SourceRecord, SourceStore

logger = logging.getLogger("kb.worker")


def _fetch(kind: str, payload: dict[str, Any]) -> FetchedDoc:
    if kind == "youtube":
        return fetch_youtube.fetch(payload["url"], payload["video_id"])
    if kind == "web":
        return fetch_web.fetch(payload["url"])
    if kind == "pdf":
        # URL (Guard-geschützt) oder lokaler Dateipfad.
        if "url" in payload:
            return fetch_pdf.fetch(payload["url"])
        return fetch_pdf.from_path(payload["path"])
    if kind == "snippet":
        return FetchedDoc(title=payload.get("title", "Snippet"), body=payload["text"])
    if kind == "file":
        p = Path(payload["path"])
        return FetchedDoc(title=p.stem, body=p.read_text(), locator=str(p))
    raise ValueError(f"Unbekannter Job-Typ: {kind}")


async def process_one_async(instance: Instance, q: JobQueue, store: SourceStore) -> bool:
    """Verarbeitet genau einen Job. True = es gab Arbeit, False = Queue leer."""
    job = q.claim_next()
    if job is None:
        return False
    record_id = None  # für Cleanup bei Ingest-Fehlern (siehe except-Block)
    raw_path = None
    try:
        vault = get_vault(job.vault)
        if job.kind == "collection_reindex":
            source_id = str(job.payload["source_id"])
            revision = int(job.payload["revision"])
            source = store.get(source_id)
            if source is None or source.vault != vault.name:
                raise ValueError("Quelle existiert nicht im Vault")
            sync = store.get_collection_sync(source_id)
            if sync.collection_revision != revision:
                q.mark_done(job.id)
                return True
            dataset_id, data_id = store.cognee_ids(source_id)
            if not dataset_id or not data_id:
                raise RuntimeError("Cognee-IDs der Quelle fehlen")
            desired_keys = store.collection_node_set_keys(source_id)
            indexed_keys = store.collection_node_set_keys(source_id, desired=False)
            provenance = store.provenance_node_sets(source_id)
            await cognee_io.delete_source(
                instance, dataset_id, data_id, provenance_node_set=provenance[0]
            )
            try:
                ingest_result = await cognee_io.ingest(
                    instance,
                    Path(source.raw_md_path),
                    vault.dataset,
                    node_sets=[*provenance, *desired_keys],
                )
            except Exception as primary_error:
                # Nach erfolgreichem Delete ist der bestätigte Index sonst nur
                # noch in SQLite vorhanden. Best-effort die vorige Projektion
                # wiederherstellen; der gewünschte Stand bleibt dennoch failed.
                try:
                    rollback_result = await cognee_io.ingest(
                        instance,
                        Path(source.raw_md_path),
                        vault.dataset,
                        node_sets=[*provenance, *indexed_keys],
                    )
                    if isinstance(rollback_result, tuple) and len(rollback_result) == 2:
                        rollback_dataset_id, rollback_data_id = rollback_result
                        store.set_cognee_ids(
                            source_id,
                            rollback_dataset_id or dataset_id,
                            rollback_data_id or data_id,
                        )
                except Exception as rollback_error:
                    raise RuntimeError(
                        f"{type(primary_error).__name__}: {primary_error}; "
                        f"rollback failed: {type(rollback_error).__name__}: {rollback_error}"
                    ) from primary_error
                raise
            new_dataset_id, new_data_id = (
                ingest_result
                if isinstance(ingest_result, tuple) and len(ingest_result) == 2
                else (None, None)
            )
            # Eine zwischenzeitlich neuere Revision darf diesen Stand nicht publizieren.
            if store.complete_collection_reindex(source_id, revision):
                store.set_cognee_ids(
                    source_id, new_dataset_id or dataset_id, new_data_id or data_id
                )
            q.mark_done(job.id)
            return True
        # _fetch ist blockierendes I/O (HTTP, Datei) — nicht den Loop blockieren
        doc = await asyncio.to_thread(_fetch, job.kind, job.payload)
        # Dedup: identischer Body im selben Vault wird nicht erneut ingestet
        # (cognee dedupt intern per Hash, unsere raw-/Source-Schicht bisher nicht
        # — sonst doppelte Quellen-Chips). mark_done, nicht failed: kein Fehler.
        content_hash = hashlib.sha256(doc.body.encode("utf-8")).hexdigest()
        if store.find_by_hash(content_hash, vault.name) is not None:
            logger.info(
                "job=%s vault=%s kind=%s request_id=%s dedup=skip (identischer Body)",
                job.id,
                vault.name,
                job.kind,
                job.payload.get("request_id"),
            )
            q.mark_done(job.id)
            return True
        record = SourceRecord.new(
            type=job.kind,
            url=doc.url,
            video_id=doc.video_id,
            locator=doc.locator,
            vault=vault.name,
            raw_md_path="",
            title=doc.title,
            content_hash=content_hash,
        )
        path, record = rawstore.write_raw(vault.raw_dir, doc.title, doc.body, record)
        raw_path = path
        store.insert(record)
        record_id = record.id
        # Stufe 1.5: node_set fällt per Default auf record.id zurück, damit jedes
        # Dokument eine deterministische belongs_to_set-Kante trägt (Vorbereitung
        # für späteren CYPHER-Herkunfts-Fallback). Ändert den Stufe-1-Pfad nicht.
        collection_ids = job.payload.get("collection_ids", [])
        store.validate_collection_ids(vault.name, collection_ids)
        collection_keys = [
            store.get_collection(vault.name, collection_id).node_set_key
            for collection_id in collection_ids
        ]
        node_set = job.payload.get("node_set") or record.id
        provenance = node_set if isinstance(node_set, list) else [node_set]
        ingest_result = await cognee_io.ingest(
            instance,
            path,
            vault.dataset,
            node_sets=[*provenance, *collection_keys],
        )
        dataset_id, data_id = (
            ingest_result
            if isinstance(ingest_result, tuple) and len(ingest_result) == 2
            else (None, None)
        )
        store.initialize_collections(
            record.id,
            collection_ids,
            cognee_dataset_id=dataset_id,
            cognee_data_id=data_id,
            provenance_node_sets=provenance,
        )
        q.mark_done(job.id)
    except Exception as e:  # noqa: BLE001 — Worker darf nie sterben
        # Fängt nur Job-Fehler: asyncio.CancelledError ist BaseException und
        # läuft hier durch — die Loop-Cancellation bleibt damit intakt.
        # Cleanup: Source-Record + Rohdatei wurden VOR cognee angelegt. Ohne
        # Cleanup würde der Dedup-Check (find_by_hash ohne Status-Filter) diesen
        # Inhalt beim nächsten Versuch überspringen — stummer Datenverlust.
        if job.kind == "collection_reindex":
            source_id = str(job.payload.get("source_id", ""))
            revision = int(job.payload.get("revision", -1))
            store.fail_collection_reindex(source_id, revision, f"{type(e).__name__}: {e}")
        elif record_id is not None:
            store.delete(record_id)
        if raw_path is not None:
            try:
                raw_path.unlink()
            except OSError:
                pass
        logger.error(
            "job=%s vault=%s kind=%s request_id=%s failed=%s: %s",
            job.id,
            job.vault,
            job.kind,
            job.payload.get("request_id"),
            type(e).__name__,
            e,
        )
        q.mark_failed(job.id, f"{type(e).__name__}: {e}")
    return True


def process_one(
    instance: Instance,
    q: JobQueue,
    store: SourceStore,
    loop: asyncio.AbstractEventLoop | None = None,
) -> bool:
    """Dünner sync-Wrapper um process_one_async — Signatur bleibt CLI-kompatibel."""
    coro = process_one_async(instance, q, store)
    if loop is not None:
        return loop.run_until_complete(coro)
    return asyncio.run(coro)


def run_forever(
    instance: Instance, q: JobQueue, store: SourceStore, poll_seconds: float = 5.0
) -> None:
    setup_logging()
    cognee_io.load_instance_env(instance)
    q.recover_stale()  # genau ein Worker pro Instanz — verwaiste Jobs gefahrlos zurücksetzen
    store.dispatch_reindex_events(q)
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


async def run_forever_async(
    instance: Instance, q: JobQueue, store: SourceStore, poll_seconds: float = 5.0
) -> None:
    """Worker-Schleife für den Instance Service (Phase 2).

    KEIN Env-Load und KEIN recover_stale — beides macht der Service beim Start.
    Läuft auf dem Loop des Aufrufers (damit cognee seine loop-gebundenen
    Ressourcen über alle Jobs hinweg wiederverwenden kann) und ist sauber per
    asyncio.CancelledError abbrechbar: process_one_async schluckt die
    Cancellation nicht, await asyncio.sleep reicht sie ebenfalls durch.
    """
    setup_logging()
    while True:
        store.dispatch_reindex_events(q)
        if not await process_one_async(instance, q, store):
            await asyncio.sleep(poll_seconds)
