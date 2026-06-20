from typer.testing import CliRunner

from kb.cli import app
from kb.queue import JobQueue
from kb.sources import SourceRecord, SourceStore

runner = CliRunner()


def _patch_io(monkeypatch, tmp_path):
    monkeypatch.setattr("kb.cli.queue_path", lambda inst: tmp_path / f"{inst}_q.db")
    monkeypatch.setattr("kb.cli.sources_path", lambda inst: tmp_path / f"{inst}_s.db")


def test_ingest_enqueues_youtube(tmp_path, monkeypatch):
    monkeypatch.setattr("kb.cli.queue_path", lambda inst: tmp_path / f"{inst}.db")
    result = runner.invoke(app, ["ingest", "privat", "https://youtu.be/dQw4w9WgXcQ"])
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


def test_import_enqueues_md_and_txt(tmp_path, monkeypatch):
    _patch_io(monkeypatch, tmp_path)
    d = tmp_path / "vault"
    d.mkdir()
    (d / "a.md").write_text("Inhalt A")
    (d / "b.txt").write_text("Text B")
    (d / "skip.pdf").write_text("nope")  # kein .md/.txt
    result = runner.invoke(app, ["import", "privat", str(d)])
    assert result.exit_code == 0, result.output
    assert "2 enqueued" in result.output
    rows = JobQueue(tmp_path / "local_q.db").conn.execute("SELECT kind FROM jobs").fetchall()
    assert len(rows) == 2
    assert all(r[0] == "file" for r in rows)


def test_import_dry_run_enqueues_nothing(tmp_path, monkeypatch):
    _patch_io(monkeypatch, tmp_path)
    d = tmp_path / "vault"
    d.mkdir()
    (d / "a.md").write_text("Inhalt A")
    result = runner.invoke(app, ["import", "privat", str(d), "--dry-run"])
    assert result.exit_code == 0
    assert "1 enqueued" in result.output
    assert "würde enqueuen" in result.output
    assert not (tmp_path / "local_q.db").exists()


def test_import_skips_duplicates(tmp_path, monkeypatch):
    import hashlib

    _patch_io(monkeypatch, tmp_path)
    d = tmp_path / "vault"
    d.mkdir()
    body = "Identischer Inhalt"
    (d / "dup.md").write_text(body)
    (d / "neu.md").write_text("Neu")
    # Hash von dup.md bereits in der Source-DB -> Duplikat.
    h = hashlib.sha256(body.encode("utf-8")).hexdigest()
    SourceStore(tmp_path / "local_s.db").insert(
        SourceRecord(
            id="x",
            type="file",
            url=None,
            video_id=None,
            locator=None,
            fetched_at="2026-01-01T00:00:00Z",
            vault="privat",
            raw_md_path="r",
            content_hash=h,
        )
    )
    result = runner.invoke(app, ["import", "privat", str(d)])
    assert result.exit_code == 0
    assert "1 enqueued" in result.output  # nur neu.md
    assert "1 Duplikate" in result.output


def test_import_single_file(tmp_path, monkeypatch):
    _patch_io(monkeypatch, tmp_path)
    f = tmp_path / "ein.md"
    f.write_text("x")
    result = runner.invoke(app, ["import", "privat", str(f)])
    assert result.exit_code == 0
    assert "1 enqueued" in result.output


def test_import_rejects_unknown_vault(tmp_path, monkeypatch):
    _patch_io(monkeypatch, tmp_path)
    result = runner.invoke(app, ["import", "geheim", str(tmp_path)])
    assert result.exit_code != 0


def test_import_no_matching_files(tmp_path, monkeypatch):
    _patch_io(monkeypatch, tmp_path)
    d = tmp_path / "vault"
    d.mkdir()
    (d / "img.png").write_text("x")
    result = runner.invoke(app, ["import", "privat", str(d)])
    assert result.exit_code != 0
    assert "Keine" in result.output
