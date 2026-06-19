"""SSRF-Schutz für Web-Ingest.

Der Server darf nicht beliebige URLs fetchen — sonst erreicht ein
(prompt-injected) Ingest interne Dienste (127.0.0.1:8801/8802 ohne Token),
Tailscale-Hosts oder den Cloud-Metadata-Endpoint (169.254.169.254).
Gelöst über eine Schema-Whitelist plus Auflösung ALLER A/AAAA-Records: sobald
eine IP in einer gesperrten Range liegt (private/loopback/link-local/reserved/
multicast/unspecified), wird der Request verweigert. Redirects werden vom
Aufrufer per Hop erneut hier geprüft (siehe kb.fetch_web).
"""
import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeUrlError(ValueError):
    """URL würde eine interne/gesperrte Adresse erreichen."""


def _is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )


def assert_safe_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeUrlError(f"Schema nicht erlaubt: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise UnsafeUrlError("URL ohne Host")
    # Hostnamen auflösen (nicht der URL vertrauen — DNS kann auf interne
    # Adressen zeigen). Jede aufgelöste IP muss sauber sein; bei IP-Literalen
    # liefert getaddrinfo die Adresse direkt (kein DNS nötig).
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise UnsafeUrlError(f"Host {host} nicht auflösbar: {e}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if _is_blocked(ip):
            raise UnsafeUrlError(f"Host {host} löst zu gesperrter IP {ip} auf")
