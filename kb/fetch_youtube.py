from dataclasses import dataclass


@dataclass(frozen=True)
class FetchedDoc:
    title: str
    body: str
    url: str | None = None
    video_id: str | None = None
    locator: str | None = None


def transcript_to_markdown(segments: list[dict]) -> str:
    lines = []
    for seg in segments:
        m, s = divmod(int(seg["start"]), 60)
        lines.append(f"[{m:02d}:{s:02d}] {seg['text']}")
    return "\n".join(lines)


def fetch(url: str, video_id: str) -> FetchedDoc:
    """Holt Transkript (de bevorzugt, en als Fallback). Wirft bei fehlendem Transkript."""
    from youtube_transcript_api import YouTubeTranscriptApi

    api = YouTubeTranscriptApi()
    fetched = api.fetch(video_id, languages=["de", "en"])
    segments = [{"start": s.start, "text": s.text} for s in fetched]
    return FetchedDoc(
        title=f"YouTube {video_id}",
        body=transcript_to_markdown(segments),
        url=url,
        video_id=video_id,
    )
