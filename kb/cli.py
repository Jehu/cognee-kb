import asyncio
from pathlib import Path

import typer

from kb import cognee_io
from kb.config import get_instance, get_vault

app = typer.Typer(no_args_is_help=True)


@app.command()
def add(vault: str, path: Path):
    """Phase 0: eine Datei direkt ingestieren (ohne Queue)."""
    v = get_vault(vault)
    inst = get_instance(v.instance)
    cognee_io.load_instance_env(inst)
    asyncio.run(cognee_io.ingest(inst, path, v.dataset, node_sets=[]))
    typer.echo(f"ingested: {path} -> {v.dataset}")


@app.command()
def query(vault: str, question: str):
    v = get_vault(vault)
    inst = get_instance(v.instance)
    cognee_io.load_instance_env(inst)
    answer = asyncio.run(cognee_io.query(inst, question, datasets=[v.dataset]))
    typer.echo(answer)


@app.command()
def eval(vault: str = "privat", out: Path = Path("eval/antworten-cognee.md")):
    """Beantwortet alle Fragen aus eval/fragen.md für den Blind-Vergleich."""
    v = get_vault(vault)
    inst = get_instance(v.instance)
    cognee_io.load_instance_env(inst)
    fragen = [
        line.removeprefix("- ").strip()
        for line in Path("eval/fragen.md").read_text().splitlines()
        if line.startswith("- ")
    ]
    blocks = []
    for i, frage in enumerate(fragen, 1):
        antwort = asyncio.run(cognee_io.query(inst, frage, datasets=[v.dataset]))
        blocks.append(f"## Frage {i}: {frage}\n\n{antwort}\n")
    out.write_text("\n".join(blocks))
    typer.echo(f"{len(fragen)} Antworten -> {out}")


if __name__ == "__main__":
    app()
