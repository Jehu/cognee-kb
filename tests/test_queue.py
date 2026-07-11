from kb.queue import JobQueue


def test_enqueue_and_claim(tmp_path):
    q = JobQueue(tmp_path / "q.db")
    job_id = q.enqueue(
        vault="privat", kind="youtube", payload={"url": "https://youtu.be/abc12345678"}
    )
    job = q.claim_next()
    assert job.id == job_id
    assert job.kind == "youtube"
    assert job.payload["url"].endswith("abc12345678")
    assert q.claim_next() is None  # running blockiert weiteren Claim


def test_done_and_failed(tmp_path):
    q = JobQueue(tmp_path / "q.db")
    a = q.enqueue("privat", "snippet", {"text": "x"})
    b = q.enqueue("privat", "snippet", {"text": "y"})
    j1 = q.claim_next()
    q.mark_done(j1.id)
    j2 = q.claim_next()
    q.mark_failed(j2.id, "kaputt")
    assert q.status(a) == "done"
    assert q.status(b) == "failed"
    assert q.claim_next() is None


def test_recover_stale_requeues_running_jobs(tmp_path):
    q = JobQueue(tmp_path / "q.db")
    job_id = q.enqueue("privat", "snippet", {"text": "x"})
    claimed = q.claim_next()
    assert claimed.id == job_id
    assert q.status(job_id) == "running"
    assert q.recover_stale() == 1
    again = q.claim_next()
    assert again is not None
    assert again.id == job_id


def test_node_sets_lists_unique_explicit_sets_for_vault(tmp_path):
    q = JobQueue(tmp_path / "q.db")
    q.enqueue("privat", "snippet", {"text": "a", "node_set": "projekt-a"})
    q.enqueue("privat", "snippet", {"text": "b", "node_set": ["projekt-b", "projekt-a"]})
    q.enqueue("privat", "snippet", {"text": "c"})
    q.enqueue("business-ki", "snippet", {"text": "d", "node_set": "fremd"})

    assert q.node_sets("privat") == ["projekt-a", "projekt-b"]


def test_enqueue_reindex_is_idempotent_per_source_revision(tmp_path):
    q = JobQueue(tmp_path / "q.db")
    first = q.enqueue_reindex("privat", "source-1", 2)
    second = q.enqueue_reindex("privat", "source-1", 2)

    assert second == first
    assert q.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    job = q.claim_next()
    assert job.kind == "collection_reindex"
    assert job.payload == {"source_id": "source-1", "revision": 2}
