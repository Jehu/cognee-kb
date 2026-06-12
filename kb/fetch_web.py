import trafilatura

from kb.fetch_youtube import FetchedDoc


def fetch(url: str) -> FetchedDoc:
    html = trafilatura.fetch_url(url)
    if html is None:
        raise RuntimeError(f"Konnte {url} nicht laden")
    text = trafilatura.extract(html, output_format="markdown", with_metadata=False)
    if not text:
        raise RuntimeError(f"Kein extrahierbarer Text auf {url}")
    meta = trafilatura.extract_metadata(html)
    title = (meta.title if meta and meta.title else url)
    return FetchedDoc(title=title, body=text, url=url)
