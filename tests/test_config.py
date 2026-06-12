import pytest
from kb.config import get_vault, get_instance, UnknownVaultError, VAULTS


def test_vault_registry_complete():
    assert set(VAULTS) == {"privat", "business-ki", "business-mwe"}


def test_privat_vault_maps_to_privat_instance():
    v = get_vault("privat")
    assert v.instance == "privat"
    assert v.dataset == "privat"
    assert v.raw_dir.name == "privat"


def test_business_vaults_share_business_instance():
    assert get_vault("business-ki").instance == "business"
    assert get_vault("business-mwe").instance == "business"


def test_unknown_vault_raises():
    with pytest.raises(UnknownVaultError):
        get_vault("nope")


def test_instance_has_env_file_and_guard_expectation():
    inst = get_instance("privat")
    assert inst.env_file.name == ".env.privat"
    assert inst.expected_llm_provider == "ollama"
    biz = get_instance("business")
    assert biz.expected_llm_provider == "custom"
