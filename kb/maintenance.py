"""Read-only Wissensbestand-Audit mit eng begrenzten Reparaturen."""

from dataclasses import dataclass
from pathlib import Path

from kb.config import Instance, Vault
from kb.queue import JobQueue
from kb.sources import SourceStore


@dataclass(frozen=True)
class MaintenanceFinding:
    kind: str
    subject: str
    detail: str
    repair: str | None = None


def audit_instance(instance: Instance, vaults: list[Vault]) -> list[MaintenanceFinding]:
    """Prüft DB und Rohschicht ohne Schreiboperationen."""
    findings = []
    store = SourceStore(instance.var_dir / "sources.db")
    try:
        referenced: set[Path] = set()
        hashes: dict[tuple[str, str], str] = {}
        for vault in vaults:
            raw_root = vault.raw_dir.resolve()
            for record in store.list_by_vault(vault.name, limit=100_000):
                path = Path(record.raw_md_path).resolve()
                referenced.add(path)
                if raw_root != path.parent and raw_root not in path.parents:
                    findings.append(
                        MaintenanceFinding("raw_outside_vault", record.id, record.raw_md_path)
                    )
                elif not path.is_file():
                    findings.append(
                        MaintenanceFinding("missing_raw", record.id, record.raw_md_path)
                    )
                if record.content_hash:
                    key = (record.vault, record.content_hash)
                    prior = hashes.get(key)
                    if prior is not None:
                        findings.append(
                            MaintenanceFinding(
                                "duplicate_hash",
                                record.id,
                                f"Gleicher Inhalt wie {prior}",
                            )
                        )
                    else:
                        hashes[key] = record.id
            if vault.raw_dir.is_dir():
                for temp in vault.raw_dir.rglob("*.tmp"):
                    if temp.resolve() not in referenced:
                        findings.append(
                            MaintenanceFinding(
                                "orphan_temp",
                                str(temp),
                                "Temporäre Datei ohne SourceRecord",
                                repair="orphan-temp",
                            )
                        )
    finally:
        store.close()

    queue_db = instance.var_dir / "queue.db"
    if queue_db.exists():
        queue = JobQueue(queue_db)
        try:
            rows = queue.conn.execute(
                "SELECT id, status, error FROM jobs "
                "WHERE status IN ('running', 'failed') ORDER BY id"
            ).fetchall()
            for job_id, status, error in rows:
                findings.append(
                    MaintenanceFinding(
                        f"{status}_job",
                        str(job_id),
                        error or status,
                        repair="stale-jobs" if status == "running" else None,
                    )
                )
        finally:
            queue.close()
    return findings


def repair(
    instance: Instance,
    vaults: list[Vault],
    repair_name: str,
    *,
    findings: list[MaintenanceFinding] | None = None,
) -> int:
    """Wendet genau eine benannte, sichere Reparaturklasse an."""
    if repair_name == "stale-jobs":
        queue = JobQueue(instance.var_dir / "queue.db")
        try:
            return queue.recover_stale()
        finally:
            queue.close()
    if repair_name == "orphan-temp":
        selected = findings if findings is not None else audit_instance(instance, vaults)
        changed = 0
        for finding in selected:
            if finding.kind != "orphan_temp" or finding.repair != repair_name:
                continue
            path = Path(finding.subject)
            if path.is_file() and path.suffix == ".tmp":
                path.unlink()
                changed += 1
        return changed
    raise ValueError(f"Unbekannte Reparatur: {repair_name}")
