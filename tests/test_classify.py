import pytest

from kb.classify import build_payload, classify, snippet_title


@pytest.mark.parametrize(
    "inp,kind",
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube"),
        ("https://youtu.be/dQw4w9WgXcQ?t=42", "youtube"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "youtube"),
        ("https://example.com/artikel", "web"),
        ("http://blog.fefe.de/?ts=99", "web"),
        ("https://example.com/paper.pdf", "pdf"),
        ("https://example.com/paper.PDF?download=1", "pdf"),
        ("Nur ein Gedanke ohne Link.", "snippet"),
        ("Text mit URL drin https://example.com aber Text dominiert", "snippet"),
    ],
)
def test_classify(inp, kind):
    assert classify(inp).kind == kind


def test_youtube_extracts_video_id():
    c = classify("https://youtu.be/dQw4w9WgXcQ")
    assert c.video_id == "dQw4w9WgXcQ"


def test_snippet_title_prefers_heading():
    assert snippet_title("intro zeile\n# Echter Titel\nmehr text") == "Echter Titel"


def test_snippet_title_skips_delimiter_heading():
    # '# ---' ist kein sinnvoller Titel -> die nächste echte Überschrift gewinnt
    assert snippet_title("# ---\ntags: x\n# Menschenkenntnis\nbody") == "Menschenkenntnis"


def test_snippet_title_falls_back_to_first_line():
    assert snippet_title("Das ist die erste Zeile.\nzweite") == "Das ist die erste Zeile."


def test_snippet_title_is_always_single_line():
    t = snippet_title("---\ntags:\n  - buch\nAuthor: x")
    assert "\n" not in t and t


def test_snippet_title_truncates_long_single_line():
    t = snippet_title("wort " * 60)
    assert t.endswith("…") and len(t) <= 61 and not t.endswith(" …")


def test_snippet_title_empty_is_snippet():
    assert snippet_title("   \n  ") == "Snippet"


def test_build_payload_youtube():
    kind, p = build_payload("https://youtu.be/dQw4w9WgXcQ")
    assert kind == "youtube" and p["video_id"] == "dQw4w9WgXcQ"


def test_build_payload_web():
    kind, p = build_payload("https://example.com/x")
    assert kind == "web" and p["url"] == "https://example.com/x"


def test_build_payload_pdf_url():
    kind, p = build_payload("https://example.com/paper.pdf")
    assert kind == "pdf" and p["url"] == "https://example.com/paper.pdf"


def test_build_payload_snippet_derives_clean_title():
    kind, p = build_payload("# Mein Titel\nInhalt hier")
    assert kind == "snippet"
    assert p["title"] == "Mein Titel"
    assert p["text"] == "# Mein Titel\nInhalt hier"  # Body unverändert
