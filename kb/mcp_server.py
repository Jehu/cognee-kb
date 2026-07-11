"""Dünner stdio-MCP-Server pro Instanz (FastMCP) — analog zum Gateway.

Wie das Gateway läuft dieser Prozess OHNE cognee-Import (Privacy-Wand): Queries
gehen per Query-Proxy an den Instance Service, Ingest direkt in die SQLite-Queue.
Erlaubte kb-Imports bleiben cognee-frei: config, classify, queue, query_proxy
und der kurzlebige SourceStore für Sammlungs-Discovery und -Validierung.

Startwege (primär: CLI):
  * `kb serve-mcp <instance>`                  ← primär
  * `KB_MCP_INSTANCE=<instance> python -m kb.mcp_server`  ← für .mcp.json direkt
"""

import json
import os
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from kb.classify import build_payload
from kb.config import VAULTS, get_instance, queue_path, sources_path
from kb.query_proxy import QueryProxyError, proxy_query, proxy_search
from kb.queue import JobQueue
from kb.sources import CollectionValidationError, SourceStore

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def _tool_name(vault_name: str) -> str:
    # MCP-Tool-Namen: Bindestriche → Unterstrich (business-ki → search_business_ki).
    return "search_" + vault_name.replace("-", "_")


def _retrieval_tool_name(vault_name: str) -> str:
    return "retrieve_" + vault_name.replace("-", "_")


def build_server(instance_name: str) -> "FastMCP":
    """Baut den FastMCP-Server einer Instanz mit dynamisch registrierten Tools."""
    from mcp.server.fastmcp import FastMCP

    inst = get_instance(instance_name)
    vaults = [v for v in VAULTS.values() if v.instance == instance_name]
    vault_names = {v.name for v in vaults}
    mcp = FastMCP(f"kb-{instance_name}")

    def _validate_collections(vault: str, collection_ids: list[str] | None) -> str | None:
        if collection_ids is None:
            return None
        store = SourceStore(sources_path(instance_name))
        try:
            store.validate_collection_ids(vault, collection_ids)
        except CollectionValidationError as exc:
            return str(exc)
        finally:
            store.close()
        return None

    async def _query(
        question: str, datasets: list[str], collection_ids: list[str] | None = None
    ) -> str:
        try:
            if collection_ids is None:
                data = await proxy_query(instance_name, question, datasets)
            else:
                data = await proxy_query(
                    instance_name, question, datasets, collection_ids=collection_ids
                )
        except QueryProxyError as e:
            return str(e)
        return str(data["answer"])

    # --- pro Vault ein search-Tool (Closure über vault sauber gebunden) ---
    for v in vaults:

        def make_search(vault_name: str, dataset: str) -> Callable[..., Awaitable[str]]:
            async def search(question: str, collection_ids: list[str] | None = None) -> str:
                error = _validate_collections(vault_name, collection_ids)
                if error:
                    return error
                return await _query(question, [dataset], collection_ids)

            return search

        mcp.add_tool(
            make_search(v.name, v.dataset),
            name=_tool_name(v.name),
            description=f"Frage an den Vault '{v.name}' (GRAPH_COMPLETION).",
        )

        def make_retrieve(vault_name: str, dataset: str) -> Callable[..., Awaitable[str]]:
            async def retrieve(question: str, collection_ids: list[str] | None = None) -> str:
                error = _validate_collections(vault_name, collection_ids)
                if error:
                    return error
                try:
                    if collection_ids is None:
                        data = await proxy_search(instance_name, question, [dataset])
                    else:
                        data = await proxy_search(
                            instance_name, question, [dataset], collection_ids=collection_ids
                        )
                except QueryProxyError as e:
                    return str(e)
                return json.dumps(data, ensure_ascii=False, indent=2)

            return retrieve

        mcp.add_tool(
            make_retrieve(v.name, v.dataset),
            name=_retrieval_tool_name(v.name),
            description=f"Ruft gerankte Evidenz aus dem Vault '{v.name}' ab (ohne Synthese).",
        )

    # --- search_all nur bei >1 Vault ---
    if len(vaults) > 1:
        all_datasets = [v.dataset for v in vaults]

        async def search_all(question: str) -> str:
            """Frage über ALLE Vaults dieser Instanz gleichzeitig."""
            return await _query(question, all_datasets)

        mcp.add_tool(
            search_all,
            name="search_all",
            description="Frage über alle Vaults dieser Instanz "
            f"({', '.join(sorted(vault_names))}).",
        )

        async def retrieve_all(question: str) -> str:
            """Gerankte Evidenz aus allen Vaults dieser Instanz."""
            try:
                data = await proxy_search(instance_name, question, all_datasets)
            except QueryProxyError as e:
                return str(e)
            return json.dumps(data, ensure_ascii=False, indent=2)

        mcp.add_tool(
            retrieve_all,
            name="retrieve_all",
            description="Ruft gerankte Evidenz aus allen Vaults dieser Instanz ab (ohne Synthese).",
        )

    async def list_collections(vault: str) -> str:
        """Listet aktive Sammlungen mit stabilen IDs und Anzeigenamen."""
        if vault not in vault_names:
            return (
                f"Vault '{vault}' gehört nicht zur Instanz '{inst.name}'. "
                f"Erlaubt: {', '.join(sorted(vault_names))}"
            )
        store = SourceStore(sources_path(instance_name))
        try:
            records = store.list_collections(vault)
        finally:
            store.close()
        return json.dumps(
            {
                "vault": vault,
                "collections": [{"id": record.id, "label": record.label} for record in records],
            },
            ensure_ascii=False,
        )

    mcp.add_tool(
        list_collections,
        name="list_collections",
        description=f"Listet aktive Sammlungen der Instanz '{inst.name}' (read-only).",
    )

    # --- ingest ---
    async def ingest(
        vault: str,
        content: str,
        node_set: str | None = None,
        collection_ids: list[str] | None = None,
    ) -> str:
        """Wirft Input in die Queue eines Vaults dieser Instanz."""
        if vault not in vault_names:
            return (
                f"Vault '{vault}' gehört nicht zur Instanz '{inst.name}'. "
                f"Erlaubt: {', '.join(sorted(vault_names))}"
            )
        error = _validate_collections(vault, collection_ids)
        if error:
            return error
        # Payload wie Gateway/CLI über build_payload ableiten (eine Stelle für
        # die Snippet-Titel-Logik) — vermeidet die frühere Titel-Divergenz,
        # bei der der Titel roh abgeschnitten statt via snippet_title() gebaut wurde.
        kind, payload = build_payload(content)
        if node_set:
            payload["node_set"] = node_set
        if collection_ids:
            payload["collection_ids"] = collection_ids
        q = JobQueue(queue_path(instance_name))
        jid = q.enqueue(vault, kind, payload)
        return f"queued job {jid} ({kind}) -> {vault}"

    mcp.add_tool(
        ingest,
        name="ingest",
        description=f"Ingestiert Inhalt in einen Vault der Instanz '{inst.name}'.",
    )

    # --- job_status ---
    async def job_status(vault: str, job_id: int) -> str:
        """Status/Fehler eines Queue-Jobs eines Vaults dieser Instanz."""
        if vault not in vault_names:
            return (
                f"Vault '{vault}' gehört nicht zur Instanz '{inst.name}'. "
                f"Erlaubt: {', '.join(sorted(vault_names))}"
            )
        q = JobQueue(queue_path(instance_name))
        info = q.info(job_id)
        # Vault-Check: Vaults einer Instanz teilen sich die queue.db.
        if info is None or info["vault"] != vault:
            return f"Unbekannter Job {job_id} für Vault '{vault}'."
        text = f"job {job_id} ({info['kind']}) -> {vault}: {info['status']}"
        if info["error"]:
            text += f"\nFehler: {info['error']}"
        return text

    mcp.add_tool(
        job_status,
        name="job_status",
        description=f"Job-Status in der Queue der Instanz '{inst.name}'.",
    )

    return mcp


def main(instance_name: str) -> None:
    build_server(instance_name).run(transport="stdio")


if __name__ == "__main__":
    main(os.environ.get("KB_MCP_INSTANCE", "local"))
