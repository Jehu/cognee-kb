from kb.cognee_io import _render, load_instance_env
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
