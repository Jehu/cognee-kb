"""A/B-Test günstiger OpenRouter-Modelle für die Business-Instanz.

Aufruf (pro Modell EIN Prozess — cognee-Config ist prozess-global):
    uv run python eval/modeltest.py <modell> <dataset> <out.md>

Ingestiert zwei Eval-Quellen in ein eigenes Test-Dataset und stellt
zwei der Phase-0-Fragen. LLM_MODEL wird NACH dem Env-Load überschrieben
(vor dem ersten cognee-Import) — .env.business bleibt unangetastet.
"""

import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kb import cognee_io  # noqa: E402
from kb.config import get_instance  # noqa: E402

QUELLEN = [
    "/Users/marco/kDrive/4 Archiv/knowledge/wiki/concepts/agent-skills-pattern.md",
    "/Users/marco/kDrive/4 Archiv/knowledge/wiki/concepts/agent-hooks-enforcement.md",
]
FRAGEN = [
    "Was ist das Agent-Skills-Pattern und wie ist ein Skill strukturell aufgebaut?",
    "Wie hängen Agent-Autonomie und Enforcement über Hooks zusammen — wo braucht es harte technische Grenzen statt Vertrauen in den Agenten?",
]


async def main(model: str, dataset: str, out: Path) -> None:
    inst = get_instance("business")
    cognee_io.load_instance_env(inst)
    os.environ["LLM_MODEL"] = model  # Override nach Env-Load, vor cognee-Import

    blocks = [f"# Modeltest: {model}\n\nDataset: `{dataset}`\n"]

    t0 = time.time()
    for f in QUELLEN:
        await cognee_io.ingest(inst, Path(f), dataset, node_sets=[])
    blocks.append(f"**Ingest** ({len(QUELLEN)} Quellen): {time.time() - t0:.0f} s\n")

    for frage in FRAGEN:
        t = time.time()
        antwort = await cognee_io.query(inst, frage, datasets=[dataset])
        blocks.append(f"## {frage}\n\n_({time.time() - t:.1f} s)_\n\n{antwort}\n")

    out.write_text("\n".join(blocks))
    print(f"OK -> {out}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2], Path(sys.argv[3])))
