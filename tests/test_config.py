import pytest
from kb.config import get_vault, get_instance, UnknownVaultError, ConfigError, VAULTS


def test_vault_registry_complete():
    assert set(VAULTS) == {"privat", "business-ki", "business-mwe"}


def test_privat_vault_maps_to_local_instance():
    v = get_vault("privat")
    assert v.instance == "local"
    assert v.dataset == "privat"
    assert v.raw_dir.name == "privat"


def test_business_vaults_share_cloud_instance():
    assert get_vault("business-ki").instance == "cloud"
    assert get_vault("business-mwe").instance == "cloud"


def test_unknown_vault_raises():
    with pytest.raises(UnknownVaultError):
        get_vault("nope")


def test_local_instance_env_and_guard_expectation():
    inst = get_instance("local")
    assert inst.env_file.name == ".env.local"
    assert inst.var_dir.name == "local"
    assert inst.allowed_llm_providers == ("ollama",)   # local: nur lokal
    assert inst.expected_embedding_provider == "fastembed"


def test_cloud_instance_env_and_guard_expectation():
    inst = get_instance("cloud")
    assert inst.env_file.name == ".env.cloud"
    assert inst.var_dir.name == "cloud"
    assert inst.allowed_llm_providers == ("custom",)   # cloud: Cloud-LLM
    assert inst.expected_embedding_provider == "fastembed"


def test_load_raises_configerror_on_invalid_toml(tmp_path):
    from kb import config

    bad = tmp_path / "kb.toml"
    bad.write_text("this is = not valid toml [[[")
    with pytest.raises(ConfigError):
        config._load(bad)


def test_load_raises_configerror_on_inconsistent_topology(tmp_path):
    from kb import config

    # Vault verweist auf eine nicht existierende Wall -> inkonsistent.
    bad = tmp_path / "kb.toml"
    bad.write_text(
        '[walls.local]\nmode = "local"\nport = 8801\n\n'
        '[[vaults]]\nname = "privat"\nwall = "nichtda"\n'
    )
    with pytest.raises(ConfigError):
        config._load(bad)
