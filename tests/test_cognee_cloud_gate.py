"""Bewusst opt-in: empirischer Cognee-Gate gegen die konfigurierte Cloud-Wall."""

import os
import uuid
from pathlib import Path

import pytest

from kb.cognee_io import load_instance_env
from kb.config import Instance, get_instance

pytestmark = pytest.mark.skipif(
    os.environ.get("KB_RUN_COGNEE_CLOUD_GATE") != "1",
    reason="setzt KB_RUN_COGNEE_CLOUD_GATE=1 und eine konfigurierte .env.cloud voraus",
)


def _strings(value: object, depth: int = 0) -> list[str]:
    if depth > 7:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _strings(item, depth + 1)]
    if isinstance(value, (list, tuple)):
        return [text for item in value for text in _strings(item, depth + 1)]
    return [
        text
        for attr in ("text", "search_result", "payload")
        if (item := getattr(value, attr, None)) is not None
        for text in _strings(item, depth + 1)
    ]


@pytest.mark.asyncio
async def test_cloud_nodeset_delete_and_readd_gate(tmp_path: Path, monkeypatch) -> None:
    """Beweist den riskanten U10-Pfad ohne bestehende Wall-Daten anzufassen."""
    # load_instance_env schreibt direkt nach os.environ. Eine private Kopie hält
    # den opt-in Test auch bei einem gemeinsamen pytest-Prozess nebenwirkungsfrei.
    monkeypatch.setattr(os, "environ", os.environ.copy())
    configured = get_instance("cloud")
    isolated = Instance(
        name=configured.name,
        env_file=configured.env_file,
        allowed_llm_providers=configured.allowed_llm_providers,
        expected_embedding_provider=configured.expected_embedding_provider,
        var_dir=tmp_path / "runtime",
        port=configured.port,
    )
    load_instance_env(isolated)
    os.environ["CACHING"] = "false"

    import cognee
    from cognee import SearchType

    dataset_name = f"kb_u10_{uuid.uuid4().hex[:10]}"
    source_a, source_b = uuid.uuid4(), uuid.uuid4()
    collection_a = f"collection:{uuid.uuid4()}"
    collection_b = f"collection:{uuid.uuid4()}"
    token_a = f"AURORA{uuid.uuid4().hex[:12]}"
    token_b = f"BOREALIS{uuid.uuid4().hex[:12]}"
    shared = f"HeliosUnion{uuid.uuid4().hex[:10]}"
    path_a, path_b = tmp_path / "source-a.md", tmp_path / "source-b.md"
    path_a.write_text(
        f"---\nsource_id: {source_a}\ntype: snippet\n---\n"
        f"{token_a} is operated by {shared} in Berlin."
    )
    path_b.write_text(
        f"---\nsource_id: {source_b}\ntype: snippet\n---\n"
        f"{token_b} is operated by {shared} in Hamburg."
    )

    async def scoped(query: str, node_names: list[str]) -> str:
        result = await cognee.search(
            query_type=SearchType.CHUNKS,
            query_text=query,
            datasets=[dataset_name],
            node_name=node_names,
            node_name_filter_operator="OR",
            top_k=20,
        )
        return "\n".join(_strings(result))

    await cognee.add(
        str(path_a), dataset_name=dataset_name, node_set=[collection_a, f"source:{source_a}"]
    )
    await cognee.add(
        str(path_b), dataset_name=dataset_name, node_set=[collection_b, f"source:{source_b}"]
    )
    await cognee.cognify(datasets=[dataset_name])

    only_a, only_b = await scoped(token_a, [collection_a]), await scoped(
        token_b, [collection_b]
    )
    union_a, union_b = await scoped(token_a, [collection_a, collection_b]), await scoped(
        token_b, [collection_a, collection_b]
    )
    assert token_a in only_a and token_b not in only_a
    assert token_b in only_b and token_a not in only_b
    assert token_a in union_a and token_b in union_b

    dataset = next(
        item for item in await cognee.datasets.list_datasets() if item.name == dataset_name
    )
    data = await cognee.datasets.list_data(dataset.id)
    assert len(data) == 2
    data_a = next(item for item in data if collection_a in (item.node_set or []))
    await cognee.datasets.delete_data(dataset.id, data_a.id)

    assert token_a not in await scoped(token_a, [collection_a, collection_b])
    preserved_b = await scoped(token_b, [collection_b])
    assert token_b in preserved_b and shared in preserved_b
    assert len(await cognee.datasets.list_data(dataset.id)) == 1

    await cognee.add(
        str(path_a), dataset_name=dataset_name, node_set=[collection_a, f"source:{source_a}"]
    )
    await cognee.cognify(datasets=[dataset_name])
    assert token_a in await scoped(token_a, [collection_a])
    assert token_b in await scoped(token_b, [collection_b])
    assert len(await cognee.datasets.list_data(dataset.id)) == 2

    # Gleiches Dokument ein zweites Mal zu addieren darf keinen Datensatz duplizieren.
    await cognee.add(
        str(path_a), dataset_name=dataset_name, node_set=[collection_a, f"source:{source_a}"]
    )
    await cognee.cognify(datasets=[dataset_name])
    assert len(await cognee.datasets.list_data(dataset.id)) == 2
    assert token_a in await scoped(token_a, [collection_a])
    final_b = await scoped(token_b, [collection_b])
    assert token_b in final_b and shared in final_b
