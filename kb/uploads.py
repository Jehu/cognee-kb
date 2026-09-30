"""Privates Staging und Vertrauensgrenzen für Browser-Uploads."""

import os
import re
import stat
import time
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile
from pypdf import PdfReader

from kb.config import Vault, get_instance

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
_CHUNK_BYTES = 64 * 1024
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")
_ALLOWED_SUFFIXES = {".pdf", ".md", ".txt"}


def display_name(filename: str | None) -> str:
    """Liefert nur einen harmlosen Anzeigenamen, niemals einen Client-Pfad."""
    name = Path(filename or "upload").name.strip().replace("\x00", "")
    name = _SAFE_NAME.sub("_", name)[:160].strip(". ")
    return name or "upload"


def upload_dir(vault: Vault) -> Path:
    # Staging liegt im var/-Baum der Wall (Konvention aus config), nie in raw/.
    return get_instance(vault.instance).var_dir / "uploads" / vault.name


def _private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def stage_path(vault: Vault, reference: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}\.(?:pdf|md|txt)", reference):
        raise ValueError("Ungültige Upload-Referenz")
    # Regex schließt Traversal aus; die Datei selbst NICHT auflösen, sonst folgt
    # resolve() einem Symlink und resolve_staged_upload sieht per lstat nur das Ziel.
    return upload_dir(vault).resolve() / reference


async def stage_upload(vault: Vault, file: UploadFile) -> tuple[str, str]:
    """Prüft und schreibt genau einen begrenzten Upload atomar in seine Wall."""
    name = display_name(file.filename)
    suffix = Path(name).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(422, "Erlaubt sind PDF-, Markdown- und Textdateien")
    root = upload_dir(vault)
    _private_dir(root)
    reference = f"{uuid.uuid4().hex}{suffix}"
    destination = stage_path(vault, reference)
    temporary = root / f".{reference}.part"
    total = 0
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as staged:
            while chunk := await file.read(_CHUNK_BYTES):
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "Datei ist größer als 20 MiB")
                staged.write(chunk)
        if total == 0:
            raise HTTPException(422, "Datei darf nicht leer sein")
        if suffix in {".md", ".txt"}:
            try:
                text = temporary.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                raise HTTPException(422, "Textdatei muss UTF-8-kodiert sein") from None
            if not text.strip():
                raise HTTPException(422, "Datei darf nicht leer sein")
        else:
            with temporary.open("rb") as staged:
                if staged.read(5) != b"%PDF-":
                    raise HTTPException(422, "Datei ist kein gültiges PDF")
            try:
                PdfReader(temporary)
            except Exception:
                raise HTTPException(422, "Datei ist kein lesbares PDF") from None
        os.replace(temporary, destination)
        destination.chmod(0o600)
        return reference, name
    except BaseException:
        temporary.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


def resolve_staged_upload(vault: Vault, reference: object) -> Path:
    """Verifiziert eine Queue-Referenz, ohne Client-Pfade zu akzeptieren."""
    if not isinstance(reference, str):
        raise ValueError("Ungültige Upload-Referenz")
    path = stage_path(vault, reference)
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        raise ValueError("Staged Upload nicht gefunden") from None
    if not stat.S_ISREG(mode) or stat.S_ISLNK(mode):
        raise ValueError("Ungültige staged Upload-Datei")
    return path


def reconcile_orphans(vault: Vault, active_references: set[str], grace_seconds: float = 300.0) -> int:
    """Entfernt nur alte, nicht mehr von pending/running Jobs referenzierte Dateien."""
    root = upload_dir(vault)
    if not root.is_dir():
        return 0
    threshold = time.time() - grace_seconds
    removed = 0
    for path in root.iterdir():
        if path.name in active_references or path.name.startswith("."):
            continue
        try:
            stat_result = path.lstat()
            if stat.S_ISREG(stat_result.st_mode) and stat_result.st_mtime < threshold:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed
