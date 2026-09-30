from dataclasses import replace

import pytest

from kb import config


@pytest.fixture
def isolated_var(tmp_path, monkeypatch):
    """Legt var/<instance> aller Walls unter tmp_path — Upload-Staging darf nie
    ins echte var/ schreiben."""
    fake = {
        name: replace(inst, var_dir=tmp_path / "var" / name)
        for name, inst in config.INSTANCES.items()
    }
    monkeypatch.setattr("kb.uploads.get_instance", lambda name: fake[name])
    return tmp_path / "var"
