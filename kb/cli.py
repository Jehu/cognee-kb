import asyncio
from pathlib import Path

import typer

from kb import cognee_io
from kb.config import ROOT, Instance, get_instance, get_vault

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


async def _answer_all(inst: Instance, fragen: list[str], datasets: list[str]) -> list[str]:
    """Alle Fragen sequenziell im SELBEN Event-Loop beantworten.

    cognee cachet loop-gebundene Ressourcen — ein frischer Loop pro Frage
    riskiert 'attached to a different loop'-Fehler.
    """
    blocks = []
    for i, frage in enumerate(fragen, 1):
        antwort = await cognee_io.query(inst, frage, datasets=datasets)
        blocks.append(f"## Frage {i}: {frage}\n\n{antwort}\n")
    return blocks


@app.command("eval")
def eval_cmd(vault: str = "privat", out: Path = ROOT / "eval" / "antworten-cognee.md"):
    """Beantwortet alle Fragen aus eval/fragen.md für den Blind-Vergleich."""
    v = get_vault(vault)
    inst = get_instance(v.instance)
    cognee_io.load_instance_env(inst)
    fragen = [
        line.removeprefix("- ").strip()
        for line in (ROOT / "eval" / "fragen.md").read_text().splitlines()
        if line.startswith("- ")
    ]
    if not fragen or fragen[0].startswith("<"):
        raise typer.BadParameter("eval/fragen.md ist noch nicht ausgefüllt")
    blocks = asyncio.run(_answer_all(inst, fragen, datasets=[v.dataset]))
    out.write_text("\n".join(blocks))
    typer.echo(f"{len(fragen)} Antworten -> {out}")


if __name__ == "__main__":
    app()
