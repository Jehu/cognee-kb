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
            fetched_at="2026-07-11T00:00:00Z",
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

    assert result.evidence == []
    assert result.gaps == []


@pytest.mark.asyncio
async def test_collection_scope_uses_native_nodes_and_verified_membership(tmp_path, monkeypatch):
    store = SourceStore(tmp_path / "sources.db")
    allowed = SourceRecord(
        id="allowed",
        type="snippet",
        url=None,
        video_id=None,
        locator=None,
        fetched_at="2026-01-01T00:00:00Z",
        vault="privat",
        raw_md_path="raw/a.md",
        title="A",
    )
    stale = SourceRecord(
        id="stale",
        type="snippet",
        url=None,
        video_id=None,
        locator=None,
        fetched_at="2026-01-01T00:00:00Z",
        vault="privat",
        raw_md_path="raw/s.md",
        title="S",
    )
    store.insert(allowed)
    store.insert(stale)
    collection = store.create_collection("privat", "Projekt")
    store.initialize_collections(
        allowed.id, [collection.id], cognee_dataset_id=None, cognee_data_id=None
    )
    store.initialize_collections(
        stale.id, [collection.id], cognee_dataset_id=None, cognee_data_id=None
    )
    store.replace_desired_collections(stale.id, [])  # Entfernung gilt sofort
    retrieve = AsyncMock(
        return_value=[
            EvidenceChunk(evidence_id="old", rank=8, text="stale", source_ids=["stale"]),
            EvidenceChunk(evidence_id="ok", rank=9, text="allowed", source_ids=["allowed"]),
            EvidenceChunk(evidence_id="none", rank=10, text="unknown", source_ids=["missing"]),
        ]
    )
    monkeypatch.setattr(query_service.cognee_io, "retrieve", retrieve)
    result = await query_service.search(
        get_instance("local"), "?", ["privat"], store, collection_ids=[collection.id]
    )
    assert [(e.evidence_id, e.rank) for e in result.evidence] == [("ok", 1)]
    retrieve.assert_awaited_once_with(
        get_instance("local"),
        "?",
        datasets=["privat"],
        node_names=[collection.node_set_key],
        top_k=100,
    )


@pytest.mark.asyncio
async def test_scope_drops_whole_chunk_with_mixed_provenance(tmp_path, monkeypatch):
    store = SourceStore(tmp_path / "sources.db")
    store.insert(
        SourceRecord(
            id="allowed",
            type="snippet",
            url=None,
            video_id=None,
            locator=None,
            fetched_at="2026-07-11T00:00:00Z",
            vault="privat",
            raw_md_path="raw/allowed.md",
            title="Allowed",
        )
    )
    monkeypatch.setattr(
        query_service.cognee_io,
        "retrieve",
        AsyncMock(
            return_value=[
                EvidenceChunk(
                    evidence_id="mixed",
                    rank=1,
                    text="gemischt",
                    source_ids=["allowed", "foreign"],
                ),
                EvidenceChunk(
                    evidence_id="safe",
                    rank=2,
                    text="sicher",
                    source_ids=["allowed"],
                ),
            ]
        ),
    )

    result = await query_service.search(get_instance("local"), "?", ["privat"], store)

    assert [(item.evidence_id, item.rank, item.source_ids) for item in result.evidence] == [
        ("safe", 1, ["allowed"])
    ]
    assert [gap.kind for gap in result.gaps] == ["unresolved_source"]


@pytest.mark.asyncio
async def test_invalid_collection_never_reaches_cognee(tmp_path, monkeypatch):
    retrieve = AsyncMock()
    monkeypatch.setattr(query_service.cognee_io, "retrieve", retrieve)
    with pytest.raises(query_service.QueryScopeError):
        await query_service.search(
            get_instance("local"),
            "?",
            ["privat"],
            SourceStore(tmp_path / "sources.db"),
            collection_ids=["bad"],
        )
    retrieve.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("collection_ids", [None, []])
async def test_collection_free_multi_vault_search_uses_union_allowlist(
    tmp_path, monkeypatch, collection_ids
):
    store = SourceStore(tmp_path / "sources.db")
    for source_id, vault in (("ki", "business-ki"), ("mwe", "business-mwe")):
        store.insert(
            SourceRecord(
                id=source_id,
                type="snippet",
                url=None,
                video_id=None,
                locator=None,
                fetched_at="2026-07-11T00:00:00Z",
                vault=vault,
                raw_md_path=f"raw/{vault}/{source_id}.md",
                title=source_id,
            )
        )
    retrieve = AsyncMock(
        return_value=[
            EvidenceChunk(evidence_id="ki", rank=1, text="KI", source_ids=["ki"]),
            EvidenceChunk(evidence_id="mwe", rank=2, text="MWE", source_ids=["mwe"]),
        ]
    )
    monkeypatch.setattr(query_service.cognee_io, "retrieve", retrieve)

    result = await query_service.search(
        get_instance("cloud"),
        "?",
        ["business-ki", "business-mwe"],
        store,
        collection_ids=collection_ids,
    )

    assert [item.evidence_id for item in result.evidence] == ["ki", "mwe"]
    retrieve.assert_awaited_once_with(
        get_instance("cloud"),
        "?",
        datasets=["business-ki", "business-mwe"],
        node_names=None,
        top_k=100,
    )


@pytest.mark.asyncio
async def test_collection_scope_rejects_multiple_vaults_before_retrieval(tmp_path, monkeypatch):
    retrieve = AsyncMock()
    monkeypatch.setattr(query_service.cognee_io, "retrieve", retrieve)
    with pytest.raises(query_service.QueryScopeError, match="genau einen Vault"):
        await query_service.search(
            get_instance("cloud"),
            "?",
            ["business-ki", "business-mwe"],
            SourceStore(tmp_path / "sources.db"),
            collection_ids=["c1"],
        )
    retrieve.assert_not_awaited()


@pytest.mark.asyncio
async def test_answer_reports_synthesis_failure_with_evidence(tmp_path, monkeypatch):
    store = SourceStore(tmp_path / "sources.db")
    store.insert(
        SourceRecord(
            id="sid",
            type="snippet",
            url=None,
            video_id=None,
            locator=None,
            fetched_at="2026-01-01T00:00:00Z",
            vault="privat",
            raw_md_path="raw/x.md",
            title="X",
        )
    )
    evidence = [EvidenceChunk(evidence_id="e1", rank=1, text="Beleg", source_ids=["sid"])]
    monkeypatch.setattr(query_service.cognee_io, "retrieve", AsyncMock(return_value=evidence))
    monkeypatch.setattr(
        query_service.cognee_io,
        "synthesize_evidence",
        AsyncMock(side_effect=RuntimeError("LLM down")),
    )

    result = await query_service.answer(get_instance("local"), "Frage?", ["privat"], store)

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
