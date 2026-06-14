import pytest
from kb.config import (
    CONFIG_FILE,
    INSTANCES,
    ConfigError,
    UnknownVaultError,
    VAULTS,
    get_instance,
    get_vault,
)


def test_registry_matches_kb_toml():
    # config lädt GENAU die in kb.toml deklarierten Vaults — aus der Datei
    # abgeleitet, nicht hardcoded: bricht NICHT bei jeder Topologie-Änderung,
    # fängt aber Parse-/Drop-Bugs in config._load.
    import tomllib

    declared = {v["name"] for v in tomllib.loads(CONFIG_FILE.read_text())["vaults"]}
    assert set(VAULTS) == declared
    assert VAULTS  # nicht leer


def test_every_vault_maps_to_a_known_wall():
    # Konsistenz-Invariante: jeder Vault gehört zu einer existierenden Wall.
    for v in VAULTS.values():
        assert v.instance in INSTANCES


def test_vault_paths_follow_naming_convention():
    # config.py leitet dataset + Rohpfad aus dem Namen ab (Konvention, nicht
    # doppelt pflegen) — gilt für JEDEN Vault, unabhängig von den Namen.
    for name, v in VAULTS.items():
        assert v.name == name
        assert v.dataset == name
        assert v.raw_dir.name == name


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
