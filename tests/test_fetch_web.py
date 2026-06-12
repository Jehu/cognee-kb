from unittest.mock import patch

from kb.fetch_web import fetch


def test_fetch_extracts_title_and_text():
    html = "<html><head><title>Mein Artikel</title></head><body><article><p>Inhalt des Artikels.</p></article></body></html>"
    with patch("trafilatura.fetch_url", return_value=html):
        doc = fetch("https://example.com/artikel")
    assert doc.url == "https://example.com/artikel"
    assert "Inhalt des Artikels." in doc.body
    assert doc.title  # trafilatura extrahiert den Titel aus Metadaten


def test_fetch_raises_on_empty_page():
    import pytest
    with patch("trafilatura.fetch_url", return_value=None):
        with pytest.raises(RuntimeError, match="nicht laden"):
            fetch("https://example.com/down")
