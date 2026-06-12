import re
from dataclasses import dataclass

YOUTUBE_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)([\w-]{11})")
URL_RE = re.compile(r"^https?://\S+$")


@dataclass(frozen=True)
class Classified:
    kind: str               # youtube | web | snippet
    video_id: str | None = None


def classify(text: str) -> Classified:
    text = text.strip()
    if URL_RE.match(text):
        m = YOUTUBE_RE.search(text)
        if m:
            return Classified("youtube", video_id=m.group(1))
        return Classified("web")
    return Classified("snippet")
