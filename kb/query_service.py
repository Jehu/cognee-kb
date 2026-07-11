"""Orchestriert Retrieval, Quellenauflösung und später die Synthese."""

import os
from time import perf_counter

from kb import cognee_io
from kb.config import Instance
from kb.gap_analysis import analyze_gaps
from kb.query_models import EvidenceChunk, GapSignal, QueryResult, QueryTrace
from kb.sources import SourceStore
from kb.synthesis import SynthesisResponse, compose_result


async def search(
    instance: Instance, question: str, datasets: list[str], store: SourceStore
) -> QueryResult:
    """Führt ausschließlich Retrieval aus; `store` markiert die Vertrauensgrenze."""
    started = perf_counter()
    evidence = await cognee_io.retrieve(instance, question, datasets=datasets)
    evidence, source_gaps = _filter_evidence_sources(evidence, store, set(datasets))
    result = QueryResult(
        answer=None,
        evidence=evidence,
        gaps=source_gaps,
        trace=QueryTrace(retrieval_ms=(perf_counter() - started) * 1000),
    )
    return analyze_gaps(result, store, stale_days=_stale_days())


async def answer(
    instance: Instance, question: str, datasets: list[str], store: SourceStore
) -> QueryResult:
    """Retrieval zuerst, danach genau eine Synthese aus diesen Belegen."""
    retrieval_started = perf_counter()
    try:
        evidence = await cognee_io.retrieve(instance, question, datasets=datasets)
    except Exception as exc:  # noqa: BLE001 — Teilfehler wird als Gap transportiert
        return QueryResult(
            gaps=[
                GapSignal(
                    kind="evidence_unavailable",
                    detail=f"Evidenzsuche fehlgeschlagen: {type(exc).__name__}",
                )
            ]
        )
    evidence, source_gaps = _filter_evidence_sources(evidence, store, set(datasets))
    if not evidence:
        return compose_result(response=SynthesisResponse(), evidence=[])
    retrieval_ms = (perf_counter() - retrieval_started) * 1000
    synthesis_started = perf_counter()
    try:
        response = await cognee_io.synthesize_evidence(instance, question, evidence)
    except Exception as exc:  # noqa: BLE001 — Evidenz bleibt trotz LLM-Ausfall nutzbar
        return QueryResult(
            evidence=evidence,
            gaps=source_gaps
            + [
                GapSignal(
                    kind="evidence_unavailable",
                    detail=f"Antwort-Synthese fehlgeschlagen: {type(exc).__name__}",
                )
            ],
            trace=QueryTrace(retrieval_ms=retrieval_ms),
        )
    composed = compose_result(response, evidence)
    result = composed.model_copy(
        update={
            "gaps": source_gaps + composed.gaps,
            "trace": QueryTrace(
                retrieval_ms=retrieval_ms,
                synthesis_ms=(perf_counter() - synthesis_started) * 1000,
            ),
        }
    )
    return analyze_gaps(result, store, stale_days=_stale_days())


def _filter_evidence_sources(
    evidence: list[EvidenceChunk], store: SourceStore, allowed_vaults: set[str]
) -> tuple[list[EvidenceChunk], list[GapSignal]]:
    filtered = []
    gaps = []
    for item in evidence:
        allowed_ids = []
        for source_id in item.source_ids:
            record = store.get(source_id)
            if record is not None and record.vault in allowed_vaults:
                allowed_ids.append(source_id)
            else:
                gaps.append(
                    GapSignal(
                        kind="unresolved_source",
                        detail=f"Quellen-ID nicht im angefragten Vault auflösbar: {source_id}",
                    )
                )
        filtered.append(item.model_copy(update={"source_ids": allowed_ids}))
    return filtered, gaps


def _stale_days() -> int:
    raw = os.environ.get("KB_STALE_DAYS", "180")
    try:
        value = int(raw)
    except ValueError:
        return 180
    return value if value > 0 else 180


def diagnostic_payload(result: QueryResult, *, show_content: bool = False) -> dict[str, object]:
    """Erzeugt eine Diagnose; Chunk-Inhalte sind standardmäßig entfernt."""
    payload = result.model_dump()
    if not show_content:
        for item in payload["evidence"]:
            item.pop("text", None)
    return payload
