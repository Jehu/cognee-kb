import httpx
import trafilatura

from kb.fetch_safety import UnsafeUrlError, assert_safe_url
from kb.fetch_youtube import FetchedDoc

_MAX_HOPS = 3


def fetch(url: str) -> FetchedDoc:
    # Kontrollierter Fetch statt trafilatura.fetch_url: jede URL (Start +
    # Redirects) wird gegen fetch_safety.assert_safe_url geprüft, Redirects per
    # Hand verfolgt, sodass ein Redirect-Niemand auf eine interne IP entkommen
    # kann. UnsafeUrlError ist eine ValueError und wird vom Worker-Except als
    # job-Fehler mit klarem Text markiert.
    assert_safe_url(url)
    html = _fetch_following_redirects(url)
    if html is None:
        raise RuntimeError(f"Konnte {url} nicht laden")
    text = trafilatura.extract(html, output_format="markdown", with_metadata=False)
    if not text:
        raise RuntimeError(f"Kein extrahierbarer Text auf {url}")
    meta = trafilatura.extract_metadata(html)
    title = (meta.title if meta and meta.title else url)
    return FetchedDoc(title=title, body=text, url=url)


def _fetch_following_redirects(url: str, hops: int = 0) -> str | None:
    # follow_redirects=False: jede Hop-URL explizit erneut via assert_safe_url
    # prüfen, bevor ihr gefolgt wird.
    with httpx.Client(timeout=30.0, follow_redirects=False) as client:
        r = client.get(url)
        if r.status_code in (301, 302, 303, 307, 308) and hops < _MAX_HOPS:
            loc = r.headers.get("location")
            if not loc:
                return None
            next_url = str(httpx.URL(url).join(loc))
            assert_safe_url(next_url)
            return _fetch_following_redirects(next_url, hops + 1)
        if r.status_code != 200:
            return None
        return r.text
