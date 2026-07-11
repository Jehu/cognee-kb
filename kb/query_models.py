"""Gemeinsame, transport-neutrale Verträge für Suche und Antworten."""

from typing import Literal

from pydantic import BaseModel, Field


class EvidenceChunk(BaseModel):
    evidence_id: str
    rank: int = Field(ge=1)
    text: str
    source_ids: list[str] = Field(default_factory=list)


class Citation(BaseModel):
    claim_index: int = Field(ge=0)
    evidence_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)


class GapSignal(BaseModel):
    kind: Literal[
        "no_evidence",
        "stale_evidence",
        "evidence_unavailable",
        "unresolved_source",
        "uncited_answer_text",
    ]
    detail: str


class QueryTrace(BaseModel):
    retrieval_ms: float | None = None
    synthesis_ms: float | None = None
    warnings: list[str] = Field(default_factory=list)


class QueryResult(BaseModel):
    answer: str | None = None
    evidence: list[EvidenceChunk] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    gaps: list[GapSignal] = Field(default_factory=list)
    trace: QueryTrace | None = None
