"""Validiert strukturierte, evidenzgebundene LLM-Antworten."""

from pydantic import BaseModel, Field

from kb.query_models import Citation, EvidenceChunk, GapSignal, QueryResult


class SynthesisClaim(BaseModel):
    text: str
    evidence_ids: list[str] = Field(default_factory=list)


class SynthesisResponse(BaseModel):
    claims: list[SynthesisClaim] = Field(default_factory=list)


def compose_result(response: SynthesisResponse, evidence: list[EvidenceChunk]) -> QueryResult:
    """Baut eine Antwort und verwirft jede nicht auflösbare Evidenz-Referenz."""
    if not evidence:
        return QueryResult(gaps=[GapSignal(kind="no_evidence", detail="Keine Evidenz gefunden.")])

    by_id = {item.evidence_id: item for item in evidence}
    citations = []
    gaps = []
    answer_parts = []
    for index, claim in enumerate(response.claims):
        text = claim.text.strip()
        if not text:
            continue
        answer_parts.append(text)
        valid_ids = list(dict.fromkeys(eid for eid in claim.evidence_ids if eid in by_id))
        invalid_ids = [eid for eid in claim.evidence_ids if eid not in by_id]
        if invalid_ids:
            gaps.append(
                GapSignal(
                    kind="unresolved_source",
                    detail=f"Unbekannte Evidenz-IDs: {', '.join(dict.fromkeys(invalid_ids))}",
                )
            )
        if not valid_ids:
            gaps.append(
                GapSignal(
                    kind="uncited_answer_text",
                    detail=f"Aussage {index + 1} enthält keinen belegten Verweis.",
                )
            )
            continue
        source_ids = list(dict.fromkeys(sid for eid in valid_ids for sid in by_id[eid].source_ids))
        citations.append(Citation(claim_index=index, evidence_ids=valid_ids, source_ids=source_ids))

    return QueryResult(
        answer="\n\n".join(answer_parts) or None,
        evidence=evidence,
        citations=citations,
        gaps=gaps,
    )
