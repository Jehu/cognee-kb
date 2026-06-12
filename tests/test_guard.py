import pytest
from kb.config import get_instance
from kb.guard import EnvGuardError, assert_instance_env


def test_guard_passes_when_env_matches(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fastembed")
    assert_instance_env(get_instance("privat"))  # darf nicht werfen


def test_guard_blocks_cloud_llm_on_privat(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "custom")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fastembed")
    with pytest.raises(EnvGuardError, match="LLM_PROVIDER"):
        assert_instance_env(get_instance("privat"))


def test_guard_blocks_cloud_embeddings_on_privat(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    with pytest.raises(EnvGuardError, match="EMBEDDING_PROVIDER"):
        assert_instance_env(get_instance("privat"))


def test_guard_blocks_missing_env(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    with pytest.raises(EnvGuardError):
        assert_instance_env(get_instance("privat"))
