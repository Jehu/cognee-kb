from kb.rawstore import slugify, write_raw
from kb.sources import SourceRecord


def test_slugify():
    assert slugify("Künstliche Intelligenz: Ein Überblick!") == "kuenstliche-intelligenz-ein-ueberblick"
    assert slugify("  --weird--  input  ") == "weird-input"


def test_write_raw_creates_file_with_frontmatter(tmp_path):
    r = SourceRecord.new(type="snippet", url=None, video_id=None, locator=None,
                         vault="privat", raw_md_path="")
    path, record = write_raw(tmp_path, title="Mein Snippet", body="Inhalt.", record=r)
    text = path.read_text()
    assert path.name.endswith("-mein-snippet.md")
    assert text.startswith("---\n")
    assert "source_id: " + r.id in text
    assert text.rstrip().endswith("Inhalt.")
    assert record.raw_md_path == str(path)


def test_write_raw_avoids_collisions(tmp_path):
    r1 = SourceRecord.new(type="snippet", url=None, video_id=None, locator=None,
                          vault="privat", raw_md_path="")
    r2 = SourceRecord.new(type="snippet", url=None, video_id=None, locator=None,
                          vault="privat", raw_md_path="")
    p1, _ = write_raw(tmp_path, "Titel", "a", r1)
    p2, _ = write_raw(tmp_path, "Titel", "b", r2)
    assert p1 != p2


def test_write_raw_collapses_multiline_title(tmp_path):
    # Ein mehrzeiliger Titel darf die '# {title}'-H1 nicht zerbrechen.
    r = SourceRecord.new(type="snippet", url=None, video_id=None, locator=None,
                         vault="privat", raw_md_path="")
    path, _ = write_raw(tmp_path, title="Zeile1\nZeile2\n# fremd", body="x", record=r)
    h1_lines = [ln for ln in path.read_text().splitlines() if ln.startswith("# ")]
    assert h1_lines == ["# Zeile1 Zeile2 # fremd"]
