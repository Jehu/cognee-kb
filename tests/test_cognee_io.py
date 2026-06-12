from kb.cognee_io import load_instance_env
from kb.config import get_instance


def test_load_instance_env_sets_vars(tmp_path, monkeypatch):
    env_file = tmp_path / ".env.test"
    env_file.write_text('LLM_PROVIDER=ollama\n# Kommentar\nEMBEDDING_PROVIDER=ollama\n')
    inst = get_instance("privat")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    load_instance_env(inst, env_path=env_file)
    import os
    assert os.environ["LLM_PROVIDER"] == "ollama"
