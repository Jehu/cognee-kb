from datetime import UTC, datetime, timedelta

from kb.gap_analysis import analyze_gaps
from kb.query_models import Citation, EvidenceChunk, QueryResult
from kb.sources import SourceRecord, SourceStore


def _record(source_id: str, fetched_at: str) -> SourceRecord:
    return SourceRecord(
        id=source_id,
        type="snippet",
        url=None,
        video_id=None,
        locator=None,
        fetched_at=fetched_at,
        vault="privat",
        raw_md_path=f"raw/privat/{source_id}.md",
        title="Test",
    )


def test_analyze_gaps_marks_stale_only_evidence(tmp_path):
    store = SourceStore(tmp_path / "sources.db")
    old = datetime.now(UTC) - timedelta(days=181)
    store.insert(_record("sid1", old.isoformat()))
    result = QueryResult(
        answer="A",
        evidence=[EvidenceChunk(evidence_id="e1", rank=1, text="B", source_ids=["sid1"])],
        citations=[Citation(claim_index=0, evidence_ids=["e1"], source_ids=["sid1"])],
    )

    analyzed = analyze_gaps(result, store, stale_days=180)

    assert [gap.kind for gap in analyzed.gaps] == ["stale_evidence"]


def test_analyze_gaps_marks_unresolved_source(tmp_path):
    store = SourceStore(tmp_path / "sources.db")
    result = QueryResult(
        evidence=[EvidenceChunk(evidence_id="e1", rank=1, text="B", source_ids=["missing"])]
    )

    analyzed = analyze_gaps(result, store)

    assert [gap.kind for gap in analyzed.gaps] == ["unresolved_source"]
