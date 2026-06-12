from kb.sources import SourceRecord, SourceStore


def make_record(**over):
    base = dict(
        type="youtube", url="https://youtu.be/abc12345678", video_id="abc12345678",
        locator=None, vault="privat", raw_md_path="raw/privat/x.md",
    )
    base.update(over)
    return SourceRecord.new(**base)


def test_new_record_gets_id_and_fetched_at():
    r = make_record()
    assert len(r.id) == 36          # uuid4
    assert r.fetched_at.endswith("Z")


def test_roundtrip(tmp_path):
    store = SourceStore(tmp_path / "sources.db")
    r = make_record()
    store.insert(r)
    got = store.get(r.id)
    assert got == r


def test_frontmatter_renders_all_fields():
    r = make_record(locator="00:12:30")
    fm = r.frontmatter()
    assert fm.startswith("---\n") and fm.rstrip().endswith("---")
    for needle in ("source_id:", "type: youtube", "video_id: abc12345678",
                   "locator: '00:12:30'", "vault: privat"):
        assert needle in fm
