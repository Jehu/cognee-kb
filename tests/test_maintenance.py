from pathlib import Path

from kb.config import Instance, Vault
from kb.maintenance import audit_instance, repair
from kb.queue import JobQueue
from kb.sources import SourceRecord, SourceStore


def _instance(tmp_path: Path) -> Instance:
    return Instance(
        name="local",
        env_file=tmp_path / ".env.local",
        allowed_llm_providers=("ollama",),
        expected_embedding_provider="fastembed",
        var_dir=tmp_path / "var",
        port=8801,
    )


def _vault(tmp_path: Path) -> Vault:
    return Vault(name="privat", instance="local", dataset="privat", raw_dir=tmp_path / "raw")


def test_audit_is_read_only_and_reports_missing_raw(tmp_path):
    inst = _instance(tmp_path)
    vault = _vault(tmp_path)
    store = SourceStore(inst.var_dir / "sources.db")
    store.insert(
        SourceRecord(
            id="sid1",
            type="snippet",
            url=None,
            video_id=None,
            locator=None,
            fetched_at="2026-01-01T00:00:00Z",
            vault="privat",
            raw_md_path=str(vault.raw_dir / "missing.md"),
            title="Test",
        )
    )
    before = store.conn.total_changes

    findings = audit_instance(inst, [vault])

    assert [(finding.kind, finding.subject) for finding in findings] == [("missing_raw", "sid1")]
    assert store.conn.total_changes == before


def test_repair_removes_only_reported_temp_orphans(tmp_path):
    inst = _instance(tmp_path)
    vault = _vault(tmp_path)
    vault.raw_dir.mkdir(parents=True)
    orphan = vault.raw_dir / "abandoned.tmp"
    markdown = vault.raw_dir / "keep.md"
    orphan.write_text("x")
    markdown.write_text("x")

    findings = audit_instance(inst, [vault])
    changed = repair(inst, [vault], "orphan-temp", findings=findings)

    assert changed == 1
    assert not orphan.exists()
    assert markdown.exists()


def test_repair_recovers_stale_jobs_via_queue(tmp_path):
    inst = _instance(tmp_path)
    q = JobQueue(inst.var_dir / "queue.db")
    q.enqueue("privat", "snippet", {"text": "x"})
    assert q.claim_next() is not None

    changed = repair(inst, [_vault(tmp_path)], "stale-jobs")

    assert changed == 1
    assert q.counts()["pending"] == 1
