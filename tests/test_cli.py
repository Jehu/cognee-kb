from datetime import UTC
from pathlib import Path

from typer.testing import CliRunner

from kb.cli import _is_excluded, _parse_cutoff, app
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
    from kb.cli import _target_spec

    port, argv, log = _target_spec("local")
    assert port == 8801
    assert argv == ["serve-instance", "local"]
    assert log.name == "serve.log"


def test_restart_target_resolves_gateway():
    from kb.cli import _target_spec

    port, argv, _ = _target_spec("gateway")
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


def test_is_excluded_matches_name_glob_and_path():
    root = Path("/wiki")
    assert _is_excluded(Path("/wiki/_index.md"), root, ["_index.md"])
    assert _is_excluded(Path("/wiki/sub/_index.md"), root, ["_index.md"])  # überall
    assert _is_excluded(Path("/wiki/_sidebar.md"), root, ["_*.md"])
    assert not _is_excluded(Path("/wiki/notiz.md"), root, ["_*.md"])
    assert _is_excluded(Path("/wiki/drafts/wip.md"), root, ["drafts/*"])
    assert not _is_excluded(Path("/wiki/_index.md"), root, [])  # ohne Muster: nichts


def test_import_exclude_by_name(tmp_path, monkeypatch):
    _patch_io(monkeypatch, tmp_path)
    d = tmp_path / "vault"
    d.mkdir()
    (d / "_index.md").write_text("MOC")
    (d / "notiz.md").write_text("Inhalt")
    result = runner.invoke(app, ["import", "privat", str(d), "--exclude", "_index.md"])
    assert result.exit_code == 0, result.output
    assert "1 enqueued" in result.output
    assert "1 ausgeschlossen" in result.output
    n = JobQueue(tmp_path / "local_q.db").conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    assert n == 1  # nur notiz.md


def test_import_exclude_glob_prefix(tmp_path, monkeypatch):
    _patch_io(monkeypatch, tmp_path)
    d = tmp_path / "vault"
    d.mkdir()
    (d / "_index.md").write_text("MOC")
    (d / "_sidebar.md").write_text("nav")
    (d / "notiz.md").write_text("Inhalt")
    result = runner.invoke(app, ["import", "privat", str(d), "-x", "_*.md"])
    assert result.exit_code == 0
    assert "1 enqueued" in result.output
    assert "2 ausgeschlossen" in result.output


def test_import_exclude_subdir(tmp_path, monkeypatch):
    _patch_io(monkeypatch, tmp_path)
    d = tmp_path / "vault"
    (d / "drafts").mkdir(parents=True)
    (d / "drafts" / "wip.md").write_text("draft")
    (d / "notiz.md").write_text("Inhalt")
    result = runner.invoke(app, ["import", "privat", str(d), "--exclude", "drafts/*"])
    assert result.exit_code == 0
    assert "1 enqueued" in result.output
    n = JobQueue(tmp_path / "local_q.db").conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    assert n == 1  # drafts/wip.md gefiltert


def test_parse_cutoff_dauer():
    from datetime import datetime

    jetzt = datetime.now(UTC)
    assert abs((jetzt - _parse_cutoff("7d")).total_seconds() - 7 * 86400) < 5
    assert abs((jetzt - _parse_cutoff("2w")).total_seconds() - 14 * 86400) < 5
    assert abs((jetzt - _parse_cutoff("12h")).total_seconds() - 12 * 3600) < 5


def test_parse_cutoff_iso_date():
    from datetime import datetime

    assert _parse_cutoff("2026-06-01") == datetime(2026, 6, 1, tzinfo=UTC)


def test_parse_cutoff_rejects_invalid():
    import pytest
    import typer

    with pytest.raises(typer.BadParameter):
        _parse_cutoff("neulich")


def test_import_limit_caps_enqueued(tmp_path, monkeypatch):
    _patch_io(monkeypatch, tmp_path)
    d = tmp_path / "vault"
    d.mkdir()
    for i in range(3):
        (d / f"n{i}.md").write_text(f"Inhalt {i}")
    result = runner.invoke(app, ["import", "privat", str(d), "--limit", "1"])
    assert result.exit_code == 0, result.output
    assert "1 enqueued" in result.output
    n = JobQueue(tmp_path / "local_q.db").conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    assert n == 1


def test_import_only_newer_than_duration(tmp_path, monkeypatch):
    import os
    import time

    _patch_io(monkeypatch, tmp_path)
    d = tmp_path / "vault"
    d.mkdir()
    alt = d / "alt.md"
    alt.write_text("alt")
    neu = d / "neu.md"
    neu.write_text("neu")
    alters_ts = time.time() - 2 * 86400  # 2 Tage her
    os.utime(alt, (alters_ts, alters_ts))
    result = runner.invoke(app, ["import", "privat", str(d), "--only-newer-than", "1d"])
    assert result.exit_code == 0, result.output
    assert "1 enqueued" in result.output
    assert "1 zu alt" in result.output


def test_import_only_newer_than_iso(tmp_path, monkeypatch):
    import os

    _patch_io(monkeypatch, tmp_path)
    d = tmp_path / "vault"
    d.mkdir()
    alt = d / "alt.md"
    alt.write_text("alt")
    neu = d / "neu.md"
    neu.write_text("neu")
    # 'alt' weit in der Vergangenheit, 'neu' jetzt.
    os.utime(alt, (1_000_000_000, 1_000_000_000))
    result = runner.invoke(app, ["import", "privat", str(d), "--only-newer-than", "2020-01-01"])
    assert result.exit_code == 0
    assert "1 enqueued" in result.output
    assert "1 zu alt" in result.output
