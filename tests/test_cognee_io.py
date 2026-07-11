import asyncio
import sys
from types import SimpleNamespace

import pytest

from kb.cognee_io import (
    _extract_source_ids,
    _iter_strings,
    _render,
    load_instance_env,
    query_with_sources,
    retrieve,
    synthesize_evidence,
)
from kb.config import get_instance
from kb.query_models import EvidenceChunk
from kb.synthesis import SynthesisClaim, SynthesisResponse


def test_load_instance_env_sets_vars(tmp_path, monkeypatch):
    env_file = tmp_path / ".env.test"
    env_file.write_text("LLM_PROVIDER=ollama\n# Kommentar\nEMBEDDING_PROVIDER=fastembed\n")
    inst = get_instance("local")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
    load_instance_env(inst, env_path=env_file)
    import os

    assert os.environ["LLM_PROVIDER"] == "ollama"
    assert os.environ["EMBEDDING_PROVIDER"] == "fastembed"


def test_load_instance_env_strips_surrounding_quotes(tmp_path, monkeypatch):
    # dotenv-Konvention: umschließende " oder ' werden entfernt — sonst bekäme
    # cognee z. B. '"sk-..."' als Key (mit Literal-Quotes) -> stummer Auth-Fehler.
    import os

    env_file = tmp_path / ".env.test"
    env_file.write_text(
        "LLM_PROVIDER=custom\n"
        'LLM_API_KEY="sk-geheim"\n'
        "LLM_MODEL='qwen3'\n"
        "EMBEDDING_PROVIDER=fastembed\n"
        "LLM_ENDPOINT=http://x\n"  # ohne Quotes bleibt unangetastet
    )
    inst = get_instance("cloud")
    for k in ("LLM_API_KEY", "LLM_MODEL", "EMBEDDING_PROVIDER", "LLM_ENDPOINT", "LLM_PROVIDER"):
        monkeypatch.delenv(k, raising=False)
    load_instance_env(inst, env_path=env_file)
    assert os.environ["LLM_API_KEY"] == "sk-geheim"
    assert os.environ["LLM_MODEL"] == "qwen3"
    assert os.environ["LLM_ENDPOINT"] == "http://x"


def test_strip_quotes_unit():
    from kb.envutil import strip_quotes

    assert strip_quotes('"sk-x"') == "sk-x"
    assert strip_quotes("'qwen'") == "qwen"
    assert strip_quotes("plain") == "plain"
    assert strip_quotes('a"b') == 'a"b'  # ungepaart -> unangetastet
    assert strip_quotes('""') == ""


class _StubSearchResult:
    """Nachbau von cognee SearchResult — nur das Feld, das _render nutzt."""

    def __init__(self, search_result):
        self.search_result = search_result


def test_render_joins_list_payload():
    result = _StubSearchResult(["Antwort A", "Antwort B"])
    assert _render(result) == "Antwort A\nAntwort B"


def test_render_passes_string_payload_through():
    assert _render(_StubSearchResult("nur Text")) == "nur Text"


def test_render_falls_back_to_str_without_attribute():
    assert _render(42) == "42"


def test_render_unwraps_dict_payload():
    # Mit ENABLE_BACKEND_ACCESS_CONTROL liefert search() dicts statt Objekten.
    assert _render({"search_result": ["Antwort A", "Antwort B"]}) == "Antwort A\nAntwort B"


def test_render_dict_without_key_falls_back():
    assert _render({"foo": "bar"}) == "{'foo': 'bar'}"


# Tests für _iter_strings und _extract_source_ids

_UUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
_FM = f"---\nsource_id: {_UUID}\ntype: snippet\n---\nInhalt"


def test_extract_source_ids_from_dict_with_text():
    results = [{"text": _FM}]
    assert _extract_source_ids(results) == [_UUID]


class _ObjWithSearchResult:
    def __init__(self, texts):
        self.search_result = texts


def test_extract_source_ids_from_object_search_result():
    results = [_ObjWithSearchResult([_FM, "kein frontmatter hier"])]
    assert _extract_source_ids(results) == [_UUID]


def test_extract_source_ids_from_acl_dict_nested():
    # ACL-Modus: search_result ist eine Liste von dicts mit 'text'
    results = [{"search_result": [{"text": _FM}]}]
    assert _extract_source_ids(results) == [_UUID]


def test_extract_source_ids_deduplicates_same_source():
    # Zwei Chunks derselben Quelle → genau eine ID
    results = [{"text": _FM}, {"text": _FM}]
    ids = _extract_source_ids(results)
    assert ids == [_UUID]


def test_extract_source_ids_no_source_id():
    results = [{"text": "Kein Frontmatter hier, nur plain text."}]
    assert _extract_source_ids(results) == []


def test_retrieve_returns_ranked_evidence_without_graph_completion(monkeypatch):
    calls = []

    class _SearchType:
        CHUNKS = "chunks"

    async def search(**kwargs):
        calls.append(kwargs)
        return [{"text": _FM}, {"text": "Zweiter Beleg"}]

    fake_cognee = SimpleNamespace(search=search, SearchType=_SearchType)
    monkeypatch.setitem(sys.modules, "cognee", fake_cognee)
    monkeypatch.setattr("kb.cognee_io.assert_instance_env", lambda instance: None)

    evidence = asyncio.run(retrieve(get_instance("local"), "Frage?", ["privat"]))

    assert [(item.evidence_id, item.rank) for item in evidence] == [("e1", 1), ("e2", 2)]
    assert evidence[0].source_ids == [_UUID]
    assert evidence[1].source_ids == []
    assert calls == [{"query_type": "chunks", "query_text": "Frage?", "datasets": ["privat"]}]


def test_synthesize_evidence_uses_numbered_chunks_and_guard(monkeypatch):
    captured = {}

    async def fake_structured(text_input, system_prompt, response_model):
        captured["text_input"] = text_input
        captured["response_model"] = response_model
        return SynthesisResponse(claims=[SynthesisClaim(text="A", evidence_ids=["e1"])])

    guard_call = []
    monkeypatch.setattr("kb.cognee_io._call_structured_output", fake_structured)
    monkeypatch.setattr("kb.cognee_io._apply_cognee_workarounds", lambda: None)
    monkeypatch.setattr(
        "kb.cognee_io.assert_instance_env", lambda instance: guard_call.append(instance)
    )
    evidence = [EvidenceChunk(evidence_id="e1", rank=1, text="Beleg", source_ids=[])]

    response = asyncio.run(synthesize_evidence(get_instance("local"), "Frage?", evidence))

    assert response.claims[0].evidence_ids == ["e1"]
    assert "[e1]" in captured["text_input"]
    assert captured["response_model"] is SynthesisResponse
    assert guard_call == [get_instance("local")]


def test_query_with_sources_returns_only_best_related_source(monkeypatch):
    calls = []
    other_uuid = "bbbbbbbb-1111-2222-3333-444444444444"

    class _SearchType:
        GRAPH_COMPLETION = "graph"
        CHUNKS = "chunks"

    async def search(**kwargs):
        calls.append(kwargs)
        if kwargs["query_type"] == _SearchType.GRAPH_COMPLETION:
            return [_StubSearchResult("Antwort")]
        return [
            {"text": _FM},
            {"text": f"---\nsource_id: {other_uuid}\ntype: web\n---\nIrrelevant"},
        ]

    fake_cognee = SimpleNamespace(search=search, SearchType=_SearchType)
    monkeypatch.setitem(sys.modules, "cognee", fake_cognee)
    monkeypatch.setattr("kb.cognee_io.assert_instance_env", lambda instance: None)

    answer, source_ids = asyncio.run(
        query_with_sources(get_instance("local"), "Frage?", ["privat"])
    )

    assert answer == "Antwort"
    assert source_ids == [_UUID]
    assert calls[1]["query_type"] == _SearchType.CHUNKS


def test_query_with_sources_returns_answer_when_chunks_fails(monkeypatch):
    # GRAPH_COMPLETION liefert die Antwort; schlägt der zweite CHUNKS-Lauf fehl,
    # muss dennoch (answer, []) zurückkommen — nicht 502 bei fertiger Antwort.
    class _SearchType:
        GRAPH_COMPLETION = "graph"
        CHUNKS = "chunks"

    async def search(**kwargs):
        if kwargs["query_type"] == _SearchType.GRAPH_COMPLETION:
            return [_StubSearchResult("Antwort")]
        raise RuntimeError("chunks broken")

    fake_cognee = SimpleNamespace(search=search, SearchType=_SearchType)
    monkeypatch.setitem(sys.modules, "cognee", fake_cognee)
    monkeypatch.setattr("kb.cognee_io.assert_instance_env", lambda instance: None)

    answer, source_ids = asyncio.run(
        query_with_sources(get_instance("local"), "Frage?", ["privat"])
    )
    assert answer == "Antwort"
    assert source_ids == []


def test_iter_strings_plain_string():
    assert list(_iter_strings("hallo")) == ["hallo"]


def test_iter_strings_list():
    assert list(_iter_strings(["a", "b"])) == ["a", "b"]


def test_iter_strings_depth_limit():
    # Extrem tief verschachteltes dict — darf nicht crashen
    obj: dict = {}
    cur = obj
    for _ in range(20):
        inner: dict = {}
        cur["x"] = inner
        cur = inner
    cur["leaf"] = "tief"
    # Kein Crash, evtl. leaf nicht gefunden (jenseits Tiefenlimit) — OK
    result = list(_iter_strings(obj))
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_cognee_access_is_serialized(monkeypatch):
    # Spike 020: cognee 0.3.9 führt Kuzu-Operationen in einem ThreadPool auf
    # EINER geteilten Connection aus -> cognify+search dürfen nicht gleichzeitig
    # bei cognee ankommen. cognee_io muss sie serialisieren (asyncio.Lock).
    # Dieser Test schlägt fehl, sobald zwei query_with_sources cognee.search
    # überlappend betreten (ohne Lock).
    import asyncio as _asyncio

    in_flight = {"n": 0, "max": 0}

    class _SearchType:
        GRAPH_COMPLETION = "graph"
        CHUNKS = "chunks"

    async def search(**kwargs):
        in_flight["n"] += 1
        in_flight["max"] = max(in_flight["max"], in_flight["n"])
        await _asyncio.sleep(0.03)  # Fenster für echtes Overlap
        in_flight["n"] -= 1
        return [_StubSearchResult("A")]

    fake_cognee = SimpleNamespace(search=search, SearchType=_SearchType)
    monkeypatch.setitem(sys.modules, "cognee", fake_cognee)
    monkeypatch.setattr("kb.cognee_io.assert_instance_env", lambda instance: None)

    await _asyncio.gather(
        query_with_sources(get_instance("local"), "Q1", ["privat"]),
        query_with_sources(get_instance("local"), "Q2", ["privat"]),
    )
    assert in_flight["max"] == 1, "cognee.search wurde konkurrent betreten (Serialisierung fehlt)"
