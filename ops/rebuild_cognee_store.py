#!/usr/bin/env python3
"""Offline rebuild of one wall into a separate Cognee 1.2 target directory."""

import argparse
import asyncio
import socket
import sqlite3
from dataclasses import replace
from pathlib import Path

from kb import cognee_io
from kb.config import GATEWAY_PORT, ROOT, VAULTS, get_instance, sources_path
from kb.sources import SourceStore


def _port_is_free(port: int) -> bool:
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) != 0


def _copy_database(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=False)
    with sqlite3.connect(source) as source_db, sqlite3.connect(target) as target_db:
        source_db.backup(target_db)


async def _rebuild_vault_batch(instance, vault, store: SourceStore, sources) -> int:
    import cognee

    prepared = []
    for source in sources:
        raw_path = Path(source.raw_md_path)
        if not raw_path.is_absolute():
            raw_path = ROOT / raw_path
        if not raw_path.is_file():
            raise SystemExit(f"Rohdatei fehlt: {raw_path}")
        node_sets = [source.id, *store.collection_node_set_keys(source.id)]
        await cognee.add(str(raw_path), dataset_name=vault.dataset, node_set=node_sets)
        prepared.append(source)
        print(f"[{instance.name}] added: {vault.name}/{source.id}", flush=True)

    if not prepared:
        return 0
    await cognee.cognify(datasets=[vault.dataset])
    await _map_vault_data(vault, store, prepared)
    return len(prepared)


async def _map_vault_data(vault, store: SourceStore, sources) -> None:
    import cognee

    dataset = next(
        (item for item in await cognee.datasets.list_datasets() if item.name == vault.dataset), None
    )
    if dataset is None:
        raise SystemExit(f"Dataset fehlt nach Rebuild: {vault.dataset}")
    data = await cognee.datasets.list_data(dataset.id)
    for source in sources:
        match = next((item for item in data if source.id in (item.node_set or [])), None)
        if match is None:
            raise SystemExit(f"Cognee-Data fehlt nach Rebuild: {source.id}")
        store.set_cognee_ids(source.id, str(dataset.id), str(match.id))


async def resume_vault(wall: str, target: Path, vault_name: str) -> None:
    instance = get_instance(wall)
    if not _port_is_free(instance.port) or not _port_is_free(GATEWAY_PORT):
        raise SystemExit("Gateway und betroffene Wall müssen gestoppt sein")
    if not target.is_dir():
        raise SystemExit(f"Ziel fehlt: {target}")
    vault = VAULTS.get(vault_name)
    if vault is None or vault.instance != wall:
        raise SystemExit(f"Vault gehört nicht zur Wall: {vault_name}")
    target_instance = replace(instance, var_dir=target)
    cognee_io.load_instance_env(target_instance)
    import cognee

    store = SourceStore(target / "sources.db")
    try:
        sources = []
        offset = 0
        while page := store.list_by_vault(vault.name, limit=100, offset=offset):
            sources.extend(page)
            offset += len(page)
        await cognee.cognify(datasets=[vault.dataset])
        await _map_vault_data(vault, store, sources)
        print(f"[{wall}] resumed: {vault.name} ({len(sources)} sources)")
    finally:
        store.close()


async def rebuild(
    wall: str, target: Path, limit: int | None = None, batch_by_vault: bool = False
) -> None:
    instance = get_instance(wall)
    if not _port_is_free(instance.port) or not _port_is_free(GATEWAY_PORT):
        raise SystemExit("Gateway und betroffene Wall müssen gestoppt sein")
    if target.exists():
        raise SystemExit(f"Ziel existiert bereits: {target}")

    copied_db = target / "sources.db"
    _copy_database(sources_path(wall), copied_db)
    target_instance = replace(instance, var_dir=target)
    cognee_io.load_instance_env(target_instance)
    store = SourceStore(copied_db)
    try:
        total = 0
        for vault in (item for item in VAULTS.values() if item.instance == wall):
            if batch_by_vault:
                sources = []
                offset = 0
                while page := store.list_by_vault(vault.name, limit=100, offset=offset):
                    sources.extend(page)
                    offset += len(page)
                total += await _rebuild_vault_batch(target_instance, vault, store, sources)
                print(f"[{wall}] indexed: {vault.name} ({len(sources)} sources)", flush=True)
                continue
            offset = 0
            while sources := store.list_by_vault(vault.name, limit=100, offset=offset):
                for source in sources:
                    if limit is not None and total >= limit:
                        print(f"[{wall}] rehearsal complete: {total} sources -> {target}")
                        return
                    raw_path = Path(source.raw_md_path)
                    if not raw_path.is_absolute():
                        raw_path = ROOT / raw_path
                    if not raw_path.is_file():
                        raise SystemExit(f"Rohdatei fehlt: {raw_path}")
                    node_sets = [source.id, *store.collection_node_set_keys(source.id)]
                    dataset_id, data_id = await cognee_io.ingest(
                        target_instance, raw_path, vault.dataset, node_sets
                    )
                    if not dataset_id or not data_id:
                        raise SystemExit(f"Cognee-IDs fehlen nach Rebuild: {source.id}")
                    store.set_cognee_ids(source.id, dataset_id, data_id)
                    total += 1
                    print(f"[{wall}] {total}: {vault.name}/{source.id}", flush=True)
                offset += len(sources)

        integrity = store.conn.execute("PRAGMA integrity_check").fetchone()
        foreign_keys = store.conn.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != ("ok",) or foreign_keys:
            raise SystemExit(f"SQLite-Prüfung fehlgeschlagen: {integrity}, {foreign_keys}")
        print(f"[{wall}] rebuild complete: {total} sources -> {target}")
    finally:
        store.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("wall")
    parser.add_argument("target", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--batch-by-vault", action="store_true")
    parser.add_argument("--resume-vault")
    args = parser.parse_args()
    target = args.target.resolve()
    if args.resume_vault:
        asyncio.run(resume_vault(args.wall, target, args.resume_vault))
    else:
        asyncio.run(rebuild(args.wall, target, args.limit, args.batch_by_vault))


if __name__ == "__main__":
    main()
