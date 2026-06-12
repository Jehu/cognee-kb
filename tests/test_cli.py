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


def test_ingest_rejects_unknown_vault(tmp_path, monkeypatch):
    monkeypatch.setattr("kb.cli.queue_path", lambda inst: tmp_path / f"{inst}.db")
    result = runner.invoke(app, ["ingest", "geheim", "text"])
    assert result.exit_code != 0
