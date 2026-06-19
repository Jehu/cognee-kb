from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FetchedDoc:
    title: str
    body: str
    url: str | None = None
    video_id: str | None = None
    locator: str | None = None


def transcript_to_markdown(segments: list[dict[str, Any]]) -> str:
    lines = []
    for seg in segments:
        m, s = divmod(int(seg["start"]), 60)
        lines.append(f"[{m:02d}:{s:02d}] {seg['text']}")
    return "\n".join(lines)


def _video_title(url: str, video_id: str) -> str:
    """Echter Video-Titel via YouTube-oEmbed (kein API-Key nötig). Titel ist
    nice-to-have — bei JEDEM Fehler Fallback auf die video_id, niemals Hard-Fail
    (sonst würde ein oEmbed-Ausfall den ganzen Ingest blockieren)."""
    import httpx

    try:
        r = httpx.get(
            "https://www.youtube.com/oembed", params={"url": url, "format": "json"}, timeout=10.0
        )
        if r.status_code == 200:
            title = r.json().get("title")
            if title:
                return str(title)
    except Exception:  # noqa: BLE001 — Titel darf den Ingest nie scheitern lassen
        pass
    return f"YouTube {video_id}"


def fetch(url: str, video_id: str) -> FetchedDoc:
    """Holt Transkript (de bevorzugt, en als Fallback). Wirft bei fehlendem Transkript."""
    from youtube_transcript_api import YouTubeTranscriptApi

    api = YouTubeTranscriptApi()
    fetched = api.fetch(video_id, languages=["de", "en"])
    segments = [{"start": s.start, "text": s.text} for s in fetched]
    return FetchedDoc(
        title=_video_title(url, video_id),
        body=transcript_to_markdown(segments),
        url=url,
        video_id=video_id,
    )
