import socket

import pytest

from kb.fetch_safety import UnsafeUrlError, assert_safe_url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/x",
        "http://localhost/x",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.1/x",
        "http://192.168.1.1/x",
        "http://172.16.0.1/x",
        "http://[::1]/x",
        "ftp://example.com/x",
        "file:///etc/passwd",
        "gopher://example.com/x",
    ],
)
def test_assert_safe_url_blocks(url):
    # IP-Literale brauchen kein DNS; localhost löst lokal zu 127.0.0.1/::1 auf.
    with pytest.raises(UnsafeUrlError):
        assert_safe_url(url)


def test_assert_safe_url_allows_public(monkeypatch):
    # Kein echtes DNS: getaddrinfo auf eine öffentliche IP faken.
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    )
    assert_safe_url("https://example.com/")  # wirft nicht


def test_assert_safe_url_blocks_if_any_resolved_ip_is_private(monkeypatch):
    # DNS-Rebinding-artig: ein Record öffentlich, einer intern -> sperren.
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 0)),
        ],
    )
    with pytest.raises(UnsafeUrlError):
        assert_safe_url("https://example.com/")
