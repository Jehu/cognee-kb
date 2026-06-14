from typer.testing import CliRunner

from kb.cli import app

runner = CliRunner()


def test_ingest_enqueues_youtube(tmp_path, monkeypatch):
    monkeypatch.setattr("kb.cli.queue_path", lambda inst: tmp_path / f"{inst}.db")
    result = runner.invoke(app, ["ingest", "privat",
                                 "https://youtu.be/dQw4w9WgXcQ"])
    assert result.exit_code == 0
    assert "queued" in result.output
    assert "youtube" in result.output


def test_ingest_enqueues_local_file(tmp_path, monkeypatch):
    monkeypatch.setattr("kb.cli.queue_path", lambda inst: tmp_path / f"{inst}.db")
    f = tmp_path / "notiz.md"
    f.write_text("# Lokale Notiz\n\nInhalt.")
    result = runner.invoke(app, ["ingest", "privat", str(f)])
    assert result.exit_code == 0
    assert "queued" in result.output
    assert "(file)" in result.output


def test_ingest_plain_text_stays_snippet(tmp_path, monkeypatch):
    monkeypatch.setattr("kb.cli.queue_path", lambda inst: tmp_path / f"{inst}.db")
    result = runner.invoke(app, ["ingest", "privat", "Nur ein Gedanke."])
    assert result.exit_code == 0
    assert "(snippet)" in result.output


def test_ingest_rejects_unknown_vault(tmp_path, monkeypatch):
    monkeypatch.setattr("kb.cli.queue_path", lambda inst: tmp_path / f"{inst}.db")
    result = runner.invoke(app, ["ingest", "geheim", "text"])
    assert result.exit_code != 0


def test_serve_befehle_registriert():
    # Nur Registrierung prüfen — uvicorn.run darf hier nicht laufen.
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "serve-instance" in result.output
    assert "serve-gateway" in result.output
    assert "restart" in result.output


def test_restart_target_resolves_wall():
    from kb.cli import _restart_target
    port, argv, log = _restart_target("local")
    assert port == 8801
    assert argv == ["serve-instance", "local"]
    assert log.name == "serve.log"


def test_restart_target_resolves_gateway():
    from kb.cli import _restart_target
    port, argv, _ = _restart_target("gateway")
    assert port == 8800
    assert argv == ["serve-gateway"]


def test_restart_rejects_unknown_target():
    # Schlägt fehl, BEVOR irgendein Prozess angefasst wird (kein lsof/kill/spawn).
    result = runner.invoke(app, ["restart", "bogus"])
    assert result.exit_code != 0
    assert "Unbekanntes Ziel" in result.output
