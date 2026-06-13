from kb.cognee_io import _extract_source_ids, _iter_strings, _render, load_instance_env
from kb.config import get_instance


def test_load_instance_env_sets_vars(tmp_path, monkeypatch):
    env_file = tmp_path / ".env.test"
    env_file.write_text('LLM_PROVIDER=ollama\n# Kommentar\nEMBEDDING_PROVIDER=fastembed\n')
    inst = get_instance("local")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
    load_instance_env(inst, env_path=env_file)
    import os
    assert os.environ["LLM_PROVIDER"] == "ollama"
    assert os.environ["EMBEDDING_PROVIDER"] == "fastembed"


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
