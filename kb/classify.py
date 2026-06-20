import re
from dataclasses import dataclass
from typing import Any

YOUTUBE_RE = re.compile(r"(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)([\w-]{11})")
URL_RE = re.compile(r"^https?://\S+$")
PDF_RE = re.compile(r"^https?://\S+\.pdf(?:[?#]|$)", re.IGNORECASE)


@dataclass(frozen=True)
class Classified:
    kind: str  # youtube | web | pdf | snippet
    video_id: str | None = None


def classify(text: str) -> Classified:
    text = text.strip()
    if URL_RE.match(text):
        if PDF_RE.match(text):
            return Classified("pdf")
        m = YOUTUBE_RE.search(text)
        if m:
            return Classified("youtube", video_id=m.group(1))
        return Classified("web")
    return Classified("snippet")


def _truncate_words(text: str, limit: int) -> str:
    """Whitespace/Zeilen kollabieren und am Wortende kürzen (mit Ellipsis)."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0] or text[:limit]
    return cut.rstrip() + "…"


def snippet_title(text: str) -> str:
    """Einzeiliger, sinnvoller Titel aus freiem Snippet-Text.

    Bevorzugt die erste Markdown-Überschrift mit echtem Inhalt, sonst die erste
    inhaltliche Zeile; entfernt Heading-/Listen-Marker und kürzt am Wortende.
    Ein blindes content[:50] schnitt mitten im Wort UND konnte mehrzeilig sein —
    Letzteres zerbrach die '# {title}'-H1 der Rohdatei. Beides vermeidet das hier.
    """
    heading = first = None
    for raw in text.splitlines():
        cleaned = raw.strip().lstrip("#").lstrip("-*> ").strip()
        if not cleaned or not re.search(r"\w", cleaned):
            continue
        if first is None:
            first = cleaned
        if raw.lstrip().startswith("#"):
            heading = cleaned
            break  # erste echte Überschrift gewinnt
    return _truncate_words(heading or first or "Snippet", 60)


def build_payload(content: str) -> tuple[str, dict[str, Any]]:
    """Klassifiziert freien Input und baut das Job-Payload (ohne node_set/Datei).

    Geteilt von Gateway und CLI, damit die Ableitung (inkl. Snippet-Titel) an
    EINER Stelle lebt statt dupliziert.
    """
    c = classify(content)
    if c.kind == "pdf":
        return c.kind, {"url": content.strip()}
    if c.kind == "youtube":
        return c.kind, {"url": content.strip(), "video_id": c.video_id}
    if c.kind == "web":
        return c.kind, {"url": content.strip()}
    return c.kind, {"text": content, "title": snippet_title(content)}
