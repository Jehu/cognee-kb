"""Kapselt ALLE Cognee-SDK-Zugriffe. Nichts außerhalb dieses Moduls importiert cognee.

Gegen cognee 0.3.9 verifiziert (Introspektion der installierten Version):
- cognee.add(data, dataset_name=..., node_set=...) — Parameternamen wie im Plan.
- cognee.cognify(datasets=[...]) — wie im Plan.
- cognee.search(query_text=..., query_type=SearchType.GRAPH_COMPLETION,
  datasets=[...]) — wie im Plan; Rückgabe ist aber list[SearchResult]
  (Pydantic-Modell mit Feld `search_result`), nicht list[str]. Mit
  ENABLE_BACKEND_ACCESS_CONTROL=true kommen stattdessen dicts mit dem
  Key 'search_result' (empirisch, Phase-0-Lauf). `_render` behandelt beides.
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

logger = logging.getLogger("kb.cognee_io")

# Serialisiert ALLE cognee-Aufrufe innerhalb eines Prozesses (Spike 020):
# cognee 0.3.9 führt Kuzu-Operationen auf einer geteilten Connection in einem
# ThreadPool aus — cognify (Schreiben) und search (Lesen) dürfen daher nicht
# gleichzeitig bei cognee ankommen. Kosten: Queries blockieren während eines
# Ingests (single-user tragbar). Bindet sich lazily an den ersten Loop (3.10+),
# und jedes cognee_io wird prozesslokal auf genau einem Loop ausgeführt.
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


# Konzept: ein Worker/Instanz + ein Loop — aber ACHTUNG: cognee 0.3.9 nutzt bei
# shared_kuzu_lock=False (Default) einen ThreadPoolExecutor für Kuzu, d. h.
# cognify (Schreiben) und search (Lesen) liefen im selben Prozess concurrency
# auf EINEM geteilten Kuzu-Connection-Objekt (nicht thread-safe). Das ist der
# offene Punkt aus Spike 020 — Serialisierung via asyncio.Lock (Plan 025, DONE).
# Siehe plans/README.md "Spike notes".

_COGNEE_PATCHED = False


def _apply_cognee_workarounds() -> None:
    """Workaround für cognee 0.3.9 + instructor 1.15.3 (idempotent, lazy).

    cognee.infrastructure.llm.utils.test_llm_connection reicht `response_model=str`
    an instructor. instructor 1.15.3 ruft im OpenAI-v2-JSON-Handler
    `str.model_json_schema()` auf (ohne Simple-Type-Guard) -> AttributeError.
    cognee führt diesen Pre-Flight bei JEDEM cognify aus
    (setup_and_check_environment) -> sonst scheitert jeder Ingest.
    Wir ersetzen `str` durch ein semantisch äquivalentes Pydantic-Modell.
    cognee ist auf 0.3.9 gepinnt, daher ist dieses Patch-Ziel stabil.
    """
    global _COGNEE_PATCHED
    if _COGNEE_PATCHED:
        return

    from pydantic import BaseModel

    class _ConnectionProbe(BaseModel):
        value: str

    async def _test_llm_connection_fixed() -> None:
        from cognee.infrastructure.llm.LLMGateway import LLMGateway
        from cognee.shared.logging_utils import get_logger

        log = get_logger()
        try:
            await LLMGateway.acreate_structured_output(
                text_input="test",
                system_prompt='Respond with JSON: {"value": "test"}',
                response_model=_ConnectionProbe,
            )
        except Exception as e:  # noqa: BLE001 — wie das Original: loggen + weiterwerfen
            log.error(e)
            log.error("Connection to LLM could not be established.")
            raise

    # Tests mocken cognee (SimpleNamespace, kein echtes Paket) — dann Überspringen.
    import sys

    try:
        import cognee.infrastructure.llm.utils as _llm_utils
    except ImportError:
        return

    _COGNEE_PATCHED = True
    setattr(_llm_utils, "test_llm_connection", _test_llm_connection_fixed)  # noqa: B010
    # Auch bereits gebundene `from … import test_llm_connection`-Referenzen ersetzen.
    for _modname in (
        "cognee.modules.pipelines.layers.setup_and_check_environment",
        "cognee.api.health",
    ):
        _mod = sys.modules.get(_modname)
        if _mod is not None and hasattr(_mod, "test_llm_connection"):
            setattr(_mod, "test_llm_connection", _test_llm_connection_fixed)  # noqa: B010


async def ingest(instance: Instance, file_path: Path, dataset: str, node_sets: list[str]) -> None:
    assert_instance_env(instance)
    import cognee  # lazy: erst nach load_instance_env importieren

    _apply_cognee_workarounds()

    async with _COGNEE_LOCK:
        await cognee.add(str(file_path), dataset_name=dataset, node_set=node_sets or None)
        await cognee.cognify(datasets=[dataset])


async def query(instance: Instance, question: str, datasets: list[str]) -> str:
    assert_instance_env(instance)
    import cognee
    from cognee import SearchType

    _apply_cognee_workarounds()

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

    _apply_cognee_workarounds()

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
