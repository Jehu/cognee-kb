from kb.query_models import EvidenceChunk
from kb.synthesis import SynthesisClaim, SynthesisResponse, compose_result


def test_compose_result_accepts_only_known_evidence_ids() -> None:
    evidence = [EvidenceChunk(evidence_id="e1", rank=1, text="Beleg", source_ids=["sid1"])]
    response = SynthesisResponse(
        claims=[
            SynthesisClaim(text="Belegte Aussage.", evidence_ids=["e1", "erfunden"]),
            SynthesisClaim(text="Unbelegte Aussage.", evidence_ids=[]),
        ]
    )

    result = compose_result(response, evidence)

    assert result.answer == "Belegte Aussage.\n\nUnbelegte Aussage."
    assert result.citations[0].evidence_ids == ["e1"]
    assert result.citations[0].source_ids == ["sid1"]
    assert {gap.kind for gap in result.gaps} == {"unresolved_source", "uncited_answer_text"}


def test_compose_result_marks_empty_evidence() -> None:
    result = compose_result(SynthesisResponse(claims=[]), [])
    assert result.answer is None
    assert [gap.kind for gap in result.gaps] == ["no_evidence"]
