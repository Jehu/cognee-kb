"""Kapselt ALLE Cognee-SDK-Zugriffe. Nichts außerhalb dieses Moduls importiert cognee.

Gegen cognee 0.3.9 verifiziert (Introspektion der installierten Version):
- cognee.add(data, dataset_name=..., node_set=...) — Parameternamen wie im Plan.
- cognee.cognify(datasets=[...]) — wie im Plan.
- cognee.search(query_text=..., query_type=SearchType.GRAPH_COMPLETION,
  datasets=[...]) — wie im Plan; Rückgabe ist aber list[SearchResult]
  (Pydantic-Modell mit Feld `search_result`), nicht list[str]. `query()`
  extrahiert deshalb `search_result` statt das Modell roh zu str()-en.
"""

import os
from pathlib import Path

from kb.config import Instance
from kb.guard import assert_instance_env


def load_instance_env(instance: Instance, env_path: Path | None = None) -> None:
    """Lädt das Env-File der Instanz in os.environ (VOR dem ersten cognee-Import!)."""
    path = env_path or instance.env_file
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ[key.strip()] = value.strip()
    assert_instance_env(instance)


async def ingest(instance: Instance, file_path: Path, dataset: str, node_sets: list[str]) -> None:
    assert_instance_env(instance)
    import cognee  # lazy: erst nach load_instance_env importieren

    await cognee.add(str(file_path), dataset_name=dataset, node_set=node_sets or None)
    await cognee.cognify(datasets=[dataset])


async def query(instance: Instance, question: str, datasets: list[str]) -> str:
    assert_instance_env(instance)
    import cognee
    from cognee import SearchType

    results = await cognee.search(
        query_type=SearchType.GRAPH_COMPLETION,
        query_text=question,
        datasets=datasets,
    )
    return "\n".join(_render(r) for r in results)


def _render(result) -> str:
    """SearchResult.search_result extrahieren; Listen flach joinen."""
    payload = getattr(result, "search_result", result)
    if isinstance(payload, list):
        return "\n".join(str(item) for item in payload)
    return str(payload)
