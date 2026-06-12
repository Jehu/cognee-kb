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
