import pytest
from kb.config import get_instance
from kb.guard import EnvGuardError, assert_instance_env


def test_guard_passes_when_env_matches(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fastembed")
    assert_instance_env(get_instance("local"))  # darf nicht werfen


def test_guard_blocks_cloud_llm_on_local(monkeypatch):
    # local erlaubt NUR ollama — ein Cloud-LLM wäre eine Fehlkonfiguration.
    monkeypatch.setenv("LLM_PROVIDER", "custom")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fastembed")
    with pytest.raises(EnvGuardError, match="LLM_PROVIDER"):
        assert_instance_env(get_instance("local"))


def test_guard_blocks_unknown_llm_on_local(monkeypatch):
    # Nicht-gelistete Provider (Tippfehler/Fehlkonfiguration) werden geblockt.
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fastembed")
    with pytest.raises(EnvGuardError, match="LLM_PROVIDER"):
        assert_instance_env(get_instance("local"))


def test_guard_passes_cloud_with_custom(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "custom")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fastembed")
    assert_instance_env(get_instance("cloud"))  # darf nicht werfen


def test_guard_blocks_local_llm_on_cloud(monkeypatch):
    # cloud erlaubt nur "custom" — ollama wäre hier eine Fehlkonfiguration.
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fastembed")
    with pytest.raises(EnvGuardError, match="LLM_PROVIDER"):
        assert_instance_env(get_instance("cloud"))


def test_guard_blocks_cloud_embeddings_on_local(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    with pytest.raises(EnvGuardError, match="EMBEDDING_PROVIDER"):
        assert_instance_env(get_instance("local"))


def test_guard_blocks_missing_env(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    with pytest.raises(EnvGuardError):
        assert_instance_env(get_instance("local"))
