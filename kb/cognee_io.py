"""Kapselt ALLE Cognee-SDK-Zugriffe. Nichts außerhalb dieses Moduls importiert cognee.

Die Integration zielt auf Cognee 1.2.2. Imports bleiben lazy, damit die Wall-
Konfiguration vor Cognees globaler Initialisierung gesetzt wird. Suchergebnisse
werden defensiv normalisiert, weil ACL- und Nicht-ACL-Modus verschiedene Shapes
liefern können.
"""

import asyncio
import logging
import os
import re
from collections.abc import Iterable, Iterator
from pathlib import Path

from kb.config import Instance
from kb.envutil import strip_quotes
from kb.guard import assert_instance_env
from kb.query_models import EvidenceChunk
from kb.synthesis import SynthesisResponse

logger = logging.getLogger("kb.cognee_io")

# Serialisiert ALLE Cognee-Aufrufe innerhalb eines Prozesses. Auch mit Ladybug
# bleibt kb bewusst single-writer; die Sperre verhindert konkurrierende Ingest-
# und Suchzugriffe und bindet sich lazy an den einen Instanz-Loop.
_COGNEE_LOCK = asyncio.Lock()

# Kompiliert als Konstante: pattern für YAML-Frontmatter source_id-Felder
_SOURCE_ID_RE = re.compile(
    r"source_id:\s*([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
)
_MAX_RELATED_SOURCES = 1


def load_instance_env(instance: Instance, env_path: Path | None = None) -> None:
    """Lädt das Env-File der Instanz in os.environ (VOR dem ersten cognee-Import!)."""
    path = env_path or instance.env_file
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ[key.strip()] = strip_quotes(value)
    # Cognee-Verzeichnisse per Konvention aus var_dir ableiten (Single Source:
    # config.py) statt absoluter Pfade in den Env-Files — portabel für die VPS.
    # Cognees eigene Defaults zeigen ins installierte Package (.venv!), und es
    # legt die Verzeichnisse nicht selbst an ('unable to open database file').
    cognee_dirs = {
        "DATA_ROOT_DIRECTORY": instance.var_dir / "cognee_data",
        "SYSTEM_ROOT_DIRECTORY": instance.var_dir / "cognee_system",
        "CACHE_ROOT_DIRECTORY": instance.var_dir / "cognee_cache",
        "COGNEE_LOGS_DIR": instance.var_dir / "logs",
    }
    for var, directory in cognee_dirs.items():
        os.environ[var] = str(directory)
        directory.mkdir(parents=True, exist_ok=True)
    assert_instance_env(instance)


def _ingest_ids(result: object) -> tuple[str | None, str | None]:
    item = result[0] if isinstance(result, (list, tuple)) and result else result
    if isinstance(item, dict):
        return item.get("dataset_id"), item.get("id") or item.get("data_id")
    return getattr(item, "dataset_id", None), getattr(item, "id", None) or getattr(
        item, "data_id", None
    )


async def ingest(
    instance: Instance, file_path: Path, dataset: str, node_sets: list[str]
) -> tuple[str | None, str | None]:
    assert_instance_env(instance)
    import cognee  # lazy: erst nach load_instance_env importieren

    async with _COGNEE_LOCK:
        result = await cognee.add(str(file_path), dataset_name=dataset, node_set=node_sets or None)
        await cognee.cognify(datasets=[dataset])
        dataset_id, data_id = _ingest_ids(result)
        if not dataset_id or not data_id:
            dataset_record = next(
                (item for item in await cognee.datasets.list_datasets() if item.name == dataset),
                None,
            )
            if dataset_record is not None:
                data = await cognee.datasets.list_data(dataset_record.id)
                provenance = node_sets[0] if node_sets else None
                match = next(
                    (
                        item
                        for item in reversed(data)
                        if provenance is not None and provenance in (item.node_set or [])
                    ),
                    None,
                )
                if match is not None:
                    dataset_id, data_id = str(dataset_record.id), str(match.id)
    return dataset_id, data_id


async def delete_source(
    instance: Instance,
    dataset_id: str,
    data_id: str,
    provenance_node_set: str | None = None,
) -> None:
    """Löscht alte und nach Teilfehlern verbliebene Daten einer Quelle."""
    assert_instance_env(instance)
    import cognee

    async with _COGNEE_LOCK:
        data = await cognee.datasets.list_data(dataset_id)
        matches = [
            item
            for item in data
            if str(item.id) == data_id
            or (
                provenance_node_set is not None
                and provenance_node_set in (item.node_set or [])
            )
        ]
        for item in matches:
            await cognee.datasets.delete_data(dataset_id, item.id)


async def query(instance: Instance, question: str, datasets: list[str]) -> str:
    assert_instance_env(instance)
    import cognee
    from cognee import SearchType

    async with _COGNEE_LOCK:
        results = await cognee.search(
            query_type=SearchType.GRAPH_COMPLETION,
            query_text=question,
            datasets=datasets,
        )
    return "\n".join(_render(r) for r in results)


def _render(result: object) -> str:
    """SearchResult.search_result extrahieren (Objekt ODER dict); Listen flach joinen."""
    if isinstance(result, dict):
        payload = result.get("search_result", result)
    else:
        payload = getattr(result, "search_result", result)
    if isinstance(payload, list):
        return "\n".join(str(item) for item in payload)
    return str(payload)


def _iter_strings(obj: object, depth: int = 0) -> Iterator[str]:
    """Rekursiver Walker über alle String-Blätter eines Cognee-Suchergebnisses.

    Defensiv implementiert weil die exakte Shape von cognee.search(CHUNKS)
    je nach ACL-Modus variiert (SearchResult-Objekt, dict mit 'search_result',
    ACL-dict mit Unterlisten, plain str) — analog zur Begründung bei _render.
    Tiefenlimit verhindert Endlosrekursion bei unerwarteten Zyklen.
    """
    if depth > 6:
        return
    if isinstance(obj, str):
        yield obj
        return
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_strings(v, depth + 1)
        return
    if isinstance(obj, (list, tuple)):
        for item in obj:
            yield from _iter_strings(item, depth + 1)
        return
    # Objekt (z. B. SearchResult): bekannte Attribute abtasten
    for attr in ("text", "search_result", "payload"):
        val = getattr(obj, attr, None)
        if val is not None:
            yield from _iter_strings(val, depth + 1)


def _extract_source_ids(results: Iterable[object]) -> list[str]:
    """Extrahiert deduplizierte source_ids aus CHUNKS-Suchergebnissen.

    Jedes Ergebnis kann verschiedene Shapes haben (siehe _iter_strings),
    daher werden alle String-Blätter durchsucht. Reihenfolge wird bewahrt.
    """
    seen: dict[str, None] = {}
    for result in results:
        for text in _iter_strings(result):
            for match in _SOURCE_ID_RE.finditer(text):
                seen[match.group(1)] = None
    return list(seen.keys())


async def retrieve(
    instance: Instance,
    question: str,
    datasets: list[str],
    *,
    node_names: list[str] | None = None,
    top_k: int = 100,
) -> list[EvidenceChunk]:
    """Liefert gerankte CHUNKS, ohne eine Antwort vom LLM zu erzeugen."""
    assert_instance_env(instance)
    import cognee
    from cognee import SearchType

    search_kwargs: dict[str, object] = {
        "query_type": SearchType.CHUNKS,
        "query_text": question,
        "datasets": datasets,
    }
    if node_names:
        search_kwargs.update(
            node_name=node_names,
            node_name_filter_operator="OR",
            top_k=min(max(top_k, 1), 100),
        )
    async with _COGNEE_LOCK:
        results = await cognee.search(**search_kwargs)

    evidence = []
    for rank, result in enumerate(results, start=1):
        strings = list(dict.fromkeys(_iter_strings(result)))
        evidence.append(
            EvidenceChunk(
                evidence_id=f"e{rank}",
                rank=rank,
                text="\n".join(strings),
                source_ids=_extract_source_ids([result]),
            )
        )
    return evidence


async def _call_structured_output(
    text_input: str, system_prompt: str, response_model: type[SynthesisResponse]
) -> SynthesisResponse:
    from cognee.infrastructure.llm.LLMGateway import LLMGateway

    result = await LLMGateway.acreate_structured_output(
        text_input=text_input,
        system_prompt=system_prompt,
        response_model=response_model,
    )
    return SynthesisResponse.model_validate(result)


async def synthesize_evidence(
    instance: Instance,
    question: str,
    evidence: list[EvidenceChunk],
) -> SynthesisResponse:
    """Synthetisiert ausschließlich aus nummerierter, bereits gefundener Evidenz."""
    assert_instance_env(instance)
    blocks = "\n\n".join(f"[{item.evidence_id}]\n{item.text}" for item in evidence)
    prompt = f"Frage:\n{question}\n\nEvidenz:\n{blocks}"
    system_prompt = (
        "Beantworte die Frage ausschließlich aus der gelieferten Evidenz. "
        "Zerlege die Antwort in claims und verweise pro Claim nur auf IDs in eckigen Klammern. "
        "Wenn die Evidenz nicht reicht, erfinde nichts und liefere entsprechend weniger Claims."
    )
    async with _COGNEE_LOCK:
        return await _call_structured_output(prompt, system_prompt, SynthesisResponse)


async def query_with_sources(
    instance: Instance, question: str, datasets: list[str]
) -> tuple[str, list[str]]:
    """Beantwortet eine Frage und liefert die zugehörigen source_ids.

    Nutzt GRAPH_COMPLETION für die Antwort und CHUNKS für die Herkunfts-
    Extraktion — graph-frei, nur via YAML-Frontmatter-Regex in den Chunks.
    """
    assert_instance_env(instance)
    import cognee
    from cognee import SearchType

    async with _COGNEE_LOCK:
        results = await cognee.search(
            query_type=SearchType.GRAPH_COMPLETION,
            query_text=question,
            datasets=datasets,
        )
        answer = "\n".join(_render(r) for r in results)

        try:
            chunk_results = await cognee.search(
                query_type=SearchType.CHUNKS,
                query_text=question,
                datasets=datasets,
            )
            source_ids = _extract_source_ids(chunk_results)[:_MAX_RELATED_SOURCES]
        except Exception as e:  # noqa: BLE001 — Quellen sind Komfort, Antwort ist Pflicht
            # CHUNKS ist nur die Herkunfts-Extraktion. Schlägt sie fehl, liefern wir
            # die Antwort ohne Quellen-Chips statt die ganze Query sterben zu lassen
            # (sonst 502 trotz fertiger Antwort).
            logger.warning("CHUNKS-Suche fehlgeschlagen: %s: %s", type(e).__name__, e)
            source_ids = []
    return answer, source_ids
