"""PDF-Connector: lädt ein PDF (URL über SSRF-Guard oder lokaler Pfad) und
extrahiert den Text mit pypdf. Der Text wird als `body` geliefert, damit die
bestehende Pipeline (Raw-`.md` + Dedup + cognee.add der `.md`) unverändert läuft.

pypdf ist bewusst eine direkte Dep (nicht nur transitiv über cognee), damit der
Connector nicht still bricht, falls cogee pypdf später droppt.
"""

import io
from pathlib import Path

import httpx
from pypdf import PdfReader

from kb.fetch_safety import UnsafeUrlError, assert_safe_url
from kb.fetch_youtube import FetchedDoc

_MAX_HOPS = 3
_PDF_TITLE_FALLBACK = "PDF"


def _doc(reader: PdfReader, source: str, url: str | None) -> FetchedDoc:
    body = "\n\n".join((page.extract_text() or "") for page in reader.pages).strip()
    if not body:
        raise RuntimeError(f"Kein extrahierbarer Text im PDF: {source}")
    meta_title = getattr(reader.metadata, "title", None) if reader.metadata else None
    title = (str(meta_title).strip() if meta_title else None) or (
        Path(source).stem if not url else _PDF_TITLE_FALLBACK
    )
    return FetchedDoc(title=title, body=body, url=url)


def fetch(url: str) -> FetchedDoc:
    # Kontrollierter Download (Schema + IP-Guard + per-Hop-Revalidierung),
    # analog zu fetch_web — kein blindes cognee-Fetch, sonst SSRF (Plan 004).
    assert_safe_url(url)
    current = url
    for _ in range(_MAX_HOPS + 1):
        with httpx.Client(timeout=30.0, follow_redirects=False) as client:
            r = client.get(current)
        if r.status_code in (301, 302, 303, 307, 308):
            loc = r.headers.get("location")
            if not loc:
                raise RuntimeError(f"Redirect ohne Location: {current}")
            current = str(httpx.URL(current).join(loc))
            assert_safe_url(current)
            continue
        if r.status_code != 200:
            raise RuntimeError(f"Konnte {url} nicht laden (Status {r.status_code})")
        return _doc(PdfReader(io.BytesIO(r.content)), url, url)
    raise RuntimeError(f"Zu viele Redirects: {url}")


def from_path(path: str) -> FetchedDoc:
    return _doc(PdfReader(path), path, None)


__all__ = ["UnsafeUrlError", "fetch", "from_path"]
