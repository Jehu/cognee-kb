"""Upload-Staging: Wall-Confinement, Validierung, atomares Schreiben, Orphan-Reinigung."""

import io
import os
import re
import stat
import time
import uuid

import pytest
from fastapi import HTTPException
from pypdf import PdfWriter
from starlette.datastructures import UploadFile

from kb import uploads
from kb.config import Vault


@pytest.fixture(autouse=True)
def _isolated(isolated_var):
    """Staging aller Tests dieses Moduls liegt unter tmp_path/var/<wall>."""


def make_vault(tmp_path) -> Vault:
    return Vault(name="privat", instance="local", dataset="privat", raw_dir=tmp_path / "raw")


def fake_upload(data: bytes, filename: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), size=len(data), filename=filename)


def minimal_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


# --- display_name: Client-Pfade werden nie übernommen ---


def test_display_name_strips_client_path_and_unsafe_chars():
    assert uploads.display_name("../../etc/passwd.txt") == "passwd.txt"
    # Windows-Pfad bleibt harmlos: Trennzeichen/Nullbyte werden substituiert
    assert uploads.display_name("C:\\Users\\marco\\Notiz\x00.md") == "C_Users_marco_Notiz.md"
    assert uploads.display_name("  .  ") == "upload"
    assert uploads.display_name(None) == "upload"


def test_display_name_length_capped_at_160():
    assert len(uploads.display_name("l" * 500 + ".txt")) == 160


# --- stage_path: Referenzen bleiben in der Wall ---


def test_stage_path_keeps_valid_reference_inside_wall(tmp_path):
    vault = make_vault(tmp_path)
    reference = f"{uuid.uuid4().hex}.txt"
    path = uploads.stage_path(vault, reference)
    assert path.parent == uploads.upload_dir(vault).resolve()


@pytest.mark.parametrize(
    "reference",
    [
        "../escape.txt",  # Traversal
        "sub/inner.txt",  # Unterverzeichnis
        f"{uuid.uuid4().hex}.exe",  # verbotener Suffix
        "short.txt",  # kein 32-Hex-Name
        f"{uuid.uuid4().hex.upper()}.txt",  # Großbuchstaben sind kein Hex
        "",
    ],
)
def test_stage_path_rejects_invalid_references(tmp_path, reference):
    vault = make_vault(tmp_path)
    with pytest.raises(ValueError):
        uploads.stage_path(vault, reference)


# --- stage_upload: Validierung + atomares, privates Schreiben ---


@pytest.mark.asyncio
async def test_stage_upload_writes_txt_with_private_permissions(tmp_path):
    vault = make_vault(tmp_path)
    reference, name = await uploads.stage_upload(vault, fake_upload(b"Inhalt", "../../notiz.txt"))
    assert re.fullmatch(r"[0-9a-f]{32}\.txt", reference)
    assert name == "notiz.txt"
    staged = uploads.upload_dir(vault) / reference
    assert staged.read_bytes() == b"Inhalt"
    assert stat.S_IMODE(staged.stat().st_mode) == 0o600
    assert stat.S_IMODE(uploads.upload_dir(vault).stat().st_mode) == 0o700


@pytest.mark.asyncio
async def test_stage_upload_accepts_valid_pdf(tmp_path):
    vault = make_vault(tmp_path)
    pdf = minimal_pdf()
    reference, _ = await uploads.stage_upload(vault, fake_upload(pdf, "doc.pdf"))
    assert reference.endswith(".pdf")
    assert (uploads.upload_dir(vault) / reference).read_bytes() == pdf


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("data", "filename", "detail"),
    [
        (b"payload", "programm.exe", "Erlaubt sind PDF-, Markdown- und Textdateien"),
        (b"", "leer.txt", "Datei darf nicht leer sein"),
        (b"   \n\t ", "nur-whitespace.txt", "Datei darf nicht leer sein"),
        (b"\xff\xfe\x00bROKEN", "kein-utf8.txt", "Textdatei muss UTF-8-kodiert sein"),
        (b"not a pdf at all", "fake.pdf", "Datei ist kein gültiges PDF"),
        (b"%PDF-broken", "kaputt.pdf", "Datei ist kein lesbares PDF"),
    ],
)
async def test_stage_upload_rejects_invalid_files(tmp_path, data, filename, detail):
    vault = make_vault(tmp_path)
    with pytest.raises(HTTPException) as exc_info:
        await uploads.stage_upload(vault, fake_upload(data, filename))
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == detail


@pytest.mark.asyncio
async def test_stage_upload_oversize_returns_413_without_leftovers(tmp_path, monkeypatch):
    vault = make_vault(tmp_path)
    monkeypatch.setattr(uploads, "MAX_UPLOAD_BYTES", 16)
    with pytest.raises(HTTPException) as exc_info:
        await uploads.stage_upload(vault, fake_upload(b"x" * 64, "big.txt"))
    assert exc_info.value.status_code == 413
    # Weder .part-Temp-Datei noch Ziel bleibt zurück.
    assert list(uploads.upload_dir(vault).iterdir()) == []


@pytest.mark.asyncio
async def test_stage_upload_failed_validation_leaves_no_files(tmp_path):
    vault = make_vault(tmp_path)
    with pytest.raises(HTTPException):
        await uploads.stage_upload(vault, fake_upload(b"%PDF-definitely broken", "x.pdf"))
    assert list(uploads.upload_dir(vault).iterdir()) == []


# --- resolve_staged_upload: Verifikation ohne Client-Pfade ---


@pytest.mark.asyncio
async def test_resolve_staged_upload_returns_existing_file(tmp_path):
    vault = make_vault(tmp_path)
    reference, _ = await uploads.stage_upload(vault, fake_upload(b"ok", "ok.txt"))
    assert uploads.resolve_staged_upload(vault, reference) == uploads.stage_path(vault, reference)


@pytest.mark.asyncio
async def test_resolve_staged_upload_rejects_symlink(tmp_path):
    vault = make_vault(tmp_path)
    reference, _ = await uploads.stage_upload(vault, fake_upload(b"ok", "ok.txt"))
    staged = uploads.stage_path(vault, reference)
    link = uploads.upload_dir(vault) / f"{uuid.uuid4().hex}.txt"
    os.symlink(staged, link)
    with pytest.raises(ValueError):
        uploads.resolve_staged_upload(vault, link.name)


def test_resolve_staged_upload_rejects_missing_or_malformed(tmp_path):
    vault = make_vault(tmp_path)
    with pytest.raises(ValueError):  # existiert nicht
        uploads.resolve_staged_upload(vault, f"{uuid.uuid4().hex}.txt")
    with pytest.raises(ValueError):  # kein String (Queue-Payload kann beliebig sein)
        uploads.resolve_staged_upload(vault, None)
    with pytest.raises(ValueError):  # kein gültiges Format
        uploads.resolve_staged_upload(vault, "../../etc/passwd")


# --- reconcile_orphans: vorsichtige Reinigung ---


def _make_stale(path) -> None:
    old = time.time() - 400  # älter als die 300s-Grace
    os.utime(path, (old, old), follow_symlinks=False)


def test_reconcile_orphans_removes_only_stale_unreferenced_files(tmp_path):
    vault = make_vault(tmp_path)
    root = uploads.upload_dir(vault)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    active = root / f"{uuid.uuid4().hex}.txt"
    stale = root / f"{uuid.uuid4().hex}.txt"
    fresh = root / f"{uuid.uuid4().hex}.txt"
    partial = root / f".{uuid.uuid4().hex}.part"
    for path in (active, stale, fresh, partial):
        path.write_bytes(b"x")
    _make_stale(stale)
    _make_stale(active)  # alt, aber noch von einem Job referenziert
    _make_stale(partial)  # alter .part-Rest — bleibt (noch) liegen

    removed = uploads.reconcile_orphans(vault, active_references={active.name})

    assert removed == 1
    assert not stale.exists()
    assert active.exists()
    assert fresh.exists()
    assert partial.exists()


def test_reconcile_orphans_skips_symlinks(tmp_path):
    vault = make_vault(tmp_path)
    root = uploads.upload_dir(vault)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = root / f"{uuid.uuid4().hex}.txt"
    target.write_bytes(b"x")
    link = root / f"{uuid.uuid4().hex}.txt"
    os.symlink(target, link)
    _make_stale(link)

    assert uploads.reconcile_orphans(vault, set()) == 0
    assert link.exists() and target.exists()


def test_reconcile_orphans_missing_dir_returns_zero(tmp_path):
    assert uploads.reconcile_orphans(make_vault(tmp_path), set()) == 0
