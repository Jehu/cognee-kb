"""Deterministische Wissenslücken aus Quellenmetadaten ableiten."""

from datetime import UTC, datetime, timedelta

from kb.query_models import GapSignal, QueryResult
from kb.sources import SourceStore


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def analyze_gaps(
    result: QueryResult,
    store: SourceStore,
    *,
    stale_days: int = 180,
    now: datetime | None = None,
) -> QueryResult:
    """Ergänzt ausschließlich aus Daten ableitbare Gap-Signale."""
    gaps = list(result.gaps)
    source_ids = list(
        dict.fromkeys(sid for evidence in result.evidence for sid in evidence.source_ids)
    )
    resolved = []
    for source_id in source_ids:
        record = store.get(source_id)
        if record is None:
            if not any(gap.kind == "unresolved_source" and source_id in gap.detail for gap in gaps):
                gaps.append(
                    GapSignal(
                        kind="unresolved_source",
                        detail=f"Quellen-ID nicht im Vault auflösbar: {source_id}",
                    )
                )
            continue
        timestamp = _parse_timestamp(record.fetched_at)
        if timestamp is not None:
            resolved.append(timestamp)

    reference = (now or datetime.now(UTC)).astimezone(UTC)
    if resolved and max(resolved) < reference - timedelta(days=stale_days):
        newest = max(resolved).date().isoformat()
        gaps.append(
            GapSignal(
                kind="stale_evidence",
                detail=f"Neueste aufgelöste Evidenz ist vom {newest}.",
            )
        )
    return result.model_copy(update={"gaps": gaps})
