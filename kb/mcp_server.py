"""Dünner stdio-MCP-Server pro Instanz (FastMCP) — analog zum Gateway.

Wie das Gateway läuft dieser Prozess OHNE cognee-Import (Privacy-Wand): Queries
gehen per Query-Proxy an den Instance Service, Ingest direkt in die SQLite-Queue.
Erlaubte kb-Imports daher nur: config, classify, queue, query_proxy.

Startwege (primär: CLI):
  * `kb serve-mcp <instance>`                  ← primär
  * `KB_MCP_INSTANCE=<instance> python -m kb.mcp_server`  ← für .mcp.json direkt
"""

import os
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from kb.classify import build_payload
from kb.config import VAULTS, get_instance, queue_path
from kb.query_proxy import QueryProxyError, proxy_query
from kb.queue import JobQueue

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def _tool_name(vault_name: str) -> str:
    # MCP-Tool-Namen: Bindestriche → Unterstrich (business-ki → search_business_ki).
    return "search_" + vault_name.replace("-", "_")


def build_server(instance_name: str) -> "FastMCP":
    """Baut den FastMCP-Server einer Instanz mit dynamisch registrierten Tools."""
    from mcp.server.fastmcp import FastMCP

    inst = get_instance(instance_name)
    vaults = [v for v in VAULTS.values() if v.instance == instance_name]
    vault_names = {v.name for v in vaults}
    mcp = FastMCP(f"kb-{instance_name}")

    async def _query(question: str, datasets: list[str]) -> str:
        try:
            data = await proxy_query(instance_name, question, datasets)
        except QueryProxyError as e:
            return str(e)
        return str(data["answer"])

    # --- pro Vault ein search-Tool (Closure über vault sauber gebunden) ---
    for v in vaults:

        def make_search(dataset: str) -> Callable[[str], Awaitable[str]]:
            async def search(question: str) -> str:
                return await _query(question, [dataset])

            return search

        mcp.add_tool(
            make_search(v.dataset),
            name=_tool_name(v.name),
            description=f"Frage an den Vault '{v.name}' (GRAPH_COMPLETION).",
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

    # --- ingest ---
    async def ingest(vault: str, content: str, node_set: str | None = None) -> str:
        """Wirft Input in die Queue eines Vaults dieser Instanz."""
        if vault not in vault_names:
            return (
                f"Vault '{vault}' gehört nicht zur Instanz '{inst.name}'. "
                f"Erlaubt: {', '.join(sorted(vault_names))}"
            )
        # Payload wie Gateway/CLI über build_payload ableiten (eine Stelle für
        # die Snippet-Titel-Logik) — vermeidet die frühere Titel-Divergenz,
        # bei der der Titel roh abgeschnitten statt via snippet_title() gebaut wurde.
        kind, payload = build_payload(content)
        if node_set:
            payload["node_set"] = node_set
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
