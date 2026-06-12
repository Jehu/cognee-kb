import pytest
from kb.classify import classify


@pytest.mark.parametrize("inp,kind", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube"),
    ("https://youtu.be/dQw4w9WgXcQ?t=42", "youtube"),
    ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "youtube"),
    ("https://example.com/artikel", "web"),
    ("http://blog.fefe.de/?ts=99", "web"),
    ("Nur ein Gedanke ohne Link.", "snippet"),
    ("Text mit URL drin https://example.com aber Text dominiert", "snippet"),
])
def test_classify(inp, kind):
    assert classify(inp).kind == kind


def test_youtube_extracts_video_id():
    c = classify("https://youtu.be/dQw4w9WgXcQ")
    assert c.video_id == "dQw4w9WgXcQ"
