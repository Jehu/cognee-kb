from unittest.mock import patch

import pytest

from kb import fetch_web
from kb.fetch_safety import UnsafeUrlError
from kb.fetch_web import fetch


def test_fetch_extracts_title_and_text():
    html = "<html><head><title>Mein Artikel</title></head><body><article><p>Inhalt des Artikels.</p></article></body></html>"
    with patch("kb.fetch_web.assert_safe_url"), \
         patch("kb.fetch_web._fetch_following_redirects", return_value=html):
        doc = fetch("https://example.com/artikel")
    assert doc.url == "https://example.com/artikel"
    assert "Inhalt des Artikels." in doc.body
    assert doc.title  # trafilatura extrahiert den Titel aus Metadaten


def test_fetch_raises_on_empty_page():
    with patch("kb.fetch_web.assert_safe_url"), \
         patch("kb.fetch_web._fetch_following_redirects", return_value=None):
        with pytest.raises(RuntimeError, match="nicht laden"):
            fetch("https://example.com/down")


def test_fetch_blocks_metadata_endpoint():
    # IP-Literal -> kein DNS nötig; assert_safe_url schlägt vor jedem httpx zu.
    with pytest.raises(UnsafeUrlError):
        fetch("http://169.254.169.254/latest/meta-data/")


def test_fetch_refuses_redirect_to_internal(monkeypatch):
    # Ein Redirect von einer (hier gefakten) sicheren Start-URL auf eine
    # interne Adresse muss pro Hop neu geprüft und verweigert werden.
    calls = []

    def fake_assert(url):
        calls.append(url)
        if "127.0.0.1" in url:
            raise UnsafeUrlError("interne Adresse blockiert")

    monkeypatch.setattr(fetch_web, "assert_safe_url", fake_assert)

    class _Resp:
        status_code = 302
        headers = {"location": "http://127.0.0.1/secret"}
        text = ""

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, url):
            return _Resp()

    monkeypatch.setattr(fetch_web.httpx, "Client", _Client)

    with pytest.raises(UnsafeUrlError):
        fetch("http://example.com/start")
    # assert_safe_url wurde für Start- UND Redirect-URL aufgerufen.
    assert "http://127.0.0.1/secret" in calls
