from kb.fetch_youtube import transcript_to_markdown


def test_transcript_to_markdown_with_timestamps():
    segments = [
        {"start": 0.0, "text": "Hallo und willkommen."},
        {"start": 65.5, "text": "Zweiter Punkt."},
        {"start": 3661.0, "text": "Nach einer Stunde."},
    ]
    md = transcript_to_markdown(segments)
    assert "[00:00] Hallo und willkommen." in md
    assert "[01:05] Zweiter Punkt." in md
    assert "[61:01] Nach einer Stunde." in md


class _OembedResponse:
    status_code = 200

    def json(self):
        return {"title": "Echtes Video — Titel"}


def test_video_title_uses_oembed(monkeypatch):
    from kb.fetch_youtube import _video_title

    monkeypatch.setattr("httpx.get", lambda *a, **k: _OembedResponse())
    assert _video_title("https://youtu.be/x", "vid123") == "Echtes Video — Titel"


def test_video_title_falls_back_on_error(monkeypatch):
    from kb.fetch_youtube import _video_title

    def boom(*a, **k):
        raise RuntimeError("offline")

    monkeypatch.setattr("httpx.get", boom)
    assert _video_title("https://youtu.be/x", "vid123") == "YouTube vid123"
