from kb.query_models import (
    Citation,
    EvidenceChunk,
    GapSignal,
    QueryRequest,
    QueryResult,
    QueryTrace,
)


def test_query_request_preserves_collection_scope_semantics() -> None:
    assert QueryRequest(question="?", datasets=["privat"]).collection_ids is None
    assert QueryRequest(question="?", datasets=["privat"], collection_ids=[]).collection_ids == []
    assert QueryRequest(
        question="?", datasets=["privat"], collection_ids=["c1", "c2"]
    ).collection_ids == ["c1", "c2"]


def test_query_result_serializes_structured_evidence() -> None:
    result = QueryResult(
        answer="Antwort",
        evidence=[
            EvidenceChunk(
                evidence_id="e1",
                rank=1,
                text="Beleg",
                source_ids=["source-1"],
            )
        ],
        citations=[Citation(claim_index=0, evidence_ids=["e1"], source_ids=["source-1"])],
        gaps=[GapSignal(kind="stale_evidence", detail="Letzter Beleg von 2025-01-01")],
        trace=QueryTrace(retrieval_ms=12.5, synthesis_ms=8.0, warnings=[]),
    )

    payload = result.model_dump()

    assert payload["answer"] == "Antwort"
    assert payload["evidence"][0]["evidence_id"] == "e1"
    assert payload["citations"][0]["source_ids"] == ["source-1"]
    assert payload["gaps"][0]["kind"] == "stale_evidence"


def test_query_result_defaults_to_empty_collections() -> None:
    result = QueryResult()

    assert result.answer is None
    assert result.evidence == []
    assert result.citations == []
    assert result.gaps == []
    assert result.trace is None
