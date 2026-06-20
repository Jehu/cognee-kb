import pytest

from kb import fetch_pdf
from kb.fetch_pdf import _doc
from kb.fetch_safety import UnsafeUrlError


class _Page:
    def __init__(self, text):
        self._t = text

    def extract_text(self):
        return self._t


def _reader(pages, title=None):
    meta = type("M", (), {"title": title})() if title else None
    return type("R", (), {"pages": pages, "metadata": meta})()


def test_doc_extracts_and_joins_pages():
    doc = _doc(
        _reader([_Page("Seite 1"), _Page("Seite 2")], title="Bericht"), "src", "https://x.de/p.pdf"
    )
    assert doc.body == "Seite 1\n\nSeite 2"
    assert doc.title == "Bericht"
    assert doc.url == "https://x.de/p.pdf"


def test_doc_falls_back_to_url_when_no_metadata_title():
    doc = _doc(_reader([_Page("nur text")]), "src", "https://x.de/p.pdf")
    assert doc.title == "PDF"  # URL → Fallback
    assert doc.body == "nur text"


def test_doc_falls_back_to_stem_for_local_path():
    doc = _doc(_reader([_Page("inhalt")]), "/tmp/Mein_Dokument.pdf", None)
    assert doc.title == "Mein_Dokument"
    assert doc.url is None


def test_doc_raises_on_empty_pdf():
    with pytest.raises(RuntimeError, match="Kein extrahierbarer Text"):
        _doc(_reader([_Page(""), _Page("   ")]), "src", None)


def test_fetch_url_blocks_internal_address():
    # SSRF-Guard greift VOR jedem Download (Plan 004): Metadata-IP literal, kein DNS.
    with pytest.raises(UnsafeUrlError):
        fetch_pdf.fetch("http://169.254.169.254/latest/meta-data/secret.pdf")


def test_from_path_uses_pdf_reader(monkeypatch):
    monkeypatch.setattr(
        fetch_pdf, "PdfReader", lambda path: _reader([_Page("Hallo PDF")], title="Titel")
    )
    doc = fetch_pdf.from_path("/tmp/x.pdf")
    assert doc.body == "Hallo PDF"
    assert doc.title == "Titel"
    assert doc.url is None
