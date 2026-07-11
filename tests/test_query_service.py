from unittest.mock import AsyncMock

import pytest

from kb import query_service
from kb.config import get_instance
from kb.query_models import EvidenceChunk
from kb.sources import SourceRecord, SourceStore
from kb.synthesis import SynthesisClaim, SynthesisResponse


@pytest.mark.asyncio
async def test_answer_synthesizes_from_retrieved_evidence(tmp_path, monkeypatch):
    evidence = [EvidenceChunk(evidence_id="e1", rank=1, text="Beleg", source_ids=["sid1"])]
    retrieve = AsyncMock(return_value=evidence)
    synthesize = AsyncMock(
        return_value=SynthesisResponse(claims=[SynthesisClaim(text="Antwort", evidence_ids=["e1"])])
    )
    monkeypatch.setattr(query_service.cognee_io, "retrieve", retrieve)
    monkeypatch.setattr(query_service.cognee_io, "synthesize_evidence", synthesize)

    store = SourceStore(tmp_path / "sources.db")
    store.insert(
        SourceRecord(
            id="sid1",
            type="snippet",
            url=None,
            video_id=None,
            locator=None,
            fetched_at="2026-07-11T00:00:00Z",
            vault="privat",
            raw_md_path="raw/privat/sid1.md",
            title="Beleg",
        )
    )
    result = await query_service.answer(get_instance("local"), "Frage?", ["privat"], store)

    assert result.answer == "Antwort"
    assert result.citations[0].source_ids == ["sid1"]
    retrieve.assert_awaited_once()
    synthesize.assert_awaited_once_with(get_instance("local"), "Frage?", evidence)


@pytest.mark.asyncio
async def test_answer_reports_retrieval_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(
        query_service.cognee_io, "retrieve", AsyncMock(side_effect=RuntimeError("kaputt"))
    )

    result = await query_service.answer(
        get_instance("local"), "Frage?", ["privat"], SourceStore(tmp_path / "sources.db")
    )

    assert result.answer is None
    assert [gap.kind for gap in result.gaps] == ["evidence_unavailable"]


@pytest.mark.asyncio
async def test_search_strips_cross_vault_source_ids(tmp_path, monkeypatch):
    store = SourceStore(tmp_path / "sources.db")
    store.insert(
        SourceRecord(
            id="cloud-id",
            type="snippet",
            url=None,
            video_id=None,
            locator=None,
            fetched_at="2026-01-01T00:00:00Z",
            vault="business-ki",
            raw_md_path="raw/business-ki/x.md",
            title="Fremd",
        )
    )
    monkeypatch.setattr(
        query_service.cognee_io,
        "retrieve",
        AsyncMock(
            return_value=[
                EvidenceChunk(evidence_id="e1", rank=1, text="Beleg", source_ids=["cloud-id"])
            ]
        ),
    )

    result = await query_service.search(get_instance("local"), "?", ["privat"], store)

    assert result.evidence[0].source_ids == []
    assert [gap.kind for gap in result.gaps] == ["unresolved_source"]


@pytest.mark.asyncio
async def test_answer_reports_synthesis_failure_with_evidence(tmp_path, monkeypatch):
    evidence = [EvidenceChunk(evidence_id="e1", rank=1, text="Beleg", source_ids=[])]
    monkeypatch.setattr(query_service.cognee_io, "retrieve", AsyncMock(return_value=evidence))
    monkeypatch.setattr(
        query_service.cognee_io,
        "synthesize_evidence",
        AsyncMock(side_effect=RuntimeError("LLM down")),
    )

    result = await query_service.answer(
        get_instance("local"), "Frage?", ["privat"], SourceStore(tmp_path / "sources.db")
    )

    assert result.answer is None
    assert result.evidence == evidence
    assert [gap.kind for gap in result.gaps] == ["evidence_unavailable"]


def test_diagnostic_payload_redacts_content_by_default():
    from kb.query_models import QueryResult, QueryTrace

    result = QueryResult(
        evidence=[
            EvidenceChunk(evidence_id="e1", rank=1, text="Privater Inhalt", source_ids=["sid1"])
        ],
        trace=QueryTrace(retrieval_ms=12.0, warnings=[]),
    )

    redacted = query_service.diagnostic_payload(result)
    visible = query_service.diagnostic_payload(result, show_content=True)

    assert "text" not in redacted["evidence"][0]
    assert visible["evidence"][0]["text"] == "Privater Inhalt"
