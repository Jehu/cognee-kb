import asyncio
from pathlib import Path

import typer

from kb import cognee_io
from kb.classify import classify
from kb.config import (
    ROOT,
    Instance,
    UnknownVaultError,
    Vault,
    get_instance,
    get_vault,
)
from kb.queue import JobQueue
from kb.sources import SourceStore

app = typer.Typer(no_args_is_help=True)


def _load(vault: str) -> tuple[Vault, Instance]:
    """Vault + Instanz auflösen und die Cognee-Env der Instanz laden."""
    v = get_vault(vault)
    inst = get_instance(v.instance)
    cognee_io.load_instance_env(inst)
    return v, inst


def queue_path(instance_name: str) -> Path:
    return get_instance(instance_name).var_dir / "queue.db"


@app.command()
def add(vault: str, path: Path):
    """Phase 0: eine Datei direkt ingestieren (ohne Queue)."""
    v, inst = _load(vault)
    asyncio.run(cognee_io.ingest(inst, path, v.dataset, node_sets=[]))
    typer.echo(f"ingested: {path} -> {v.dataset}")


@app.command()
def query(vault: str, question: str):
    """Stellt eine Frage an einen Vault (GRAPH_COMPLETION)."""
    v, inst = _load(vault)
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
    v, inst = _load(vault)
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


@app.command()
def ingest(vault: str, content: str, node_set: str = typer.Option(None)):
    """Wirft Input in die Queue des zuständigen Workers."""
    try:
        v = get_vault(vault)
    except UnknownVaultError:
        typer.echo(f"Unbekannter Vault: {vault}", err=True)
        raise typer.Exit(1)
    payload: dict = {"node_set": node_set} if node_set else {}
    p = Path(content).expanduser()
    if p.is_file():
        kind = "file"
        payload |= {"path": str(p.resolve())}
    else:
        c = classify(content)
        kind = c.kind
        if kind == "youtube":
            payload |= {"url": content.strip(), "video_id": c.video_id}
        elif kind == "web":
            payload |= {"url": content.strip()}
        else:
            payload |= {"text": content, "title": content[:50]}
    q = JobQueue(queue_path(v.instance))
    jid = q.enqueue(v.name, kind, payload)
    typer.echo(f"queued: job {jid} ({kind}) -> {v.name}")


@app.command()
def worker(instance: str):
    """Startet den seriellen Worker einer Instanz (local | cloud)."""
    from kb import worker as worker_mod

    inst = get_instance(instance)
    q = JobQueue(queue_path(instance))
    store = SourceStore(inst.var_dir / "sources.db")
    typer.echo(f"Worker '{instance}' läuft (seriell, Strg-C zum Beenden)")
    worker_mod.run_forever(inst, q, store)


def _load_env_file(path: Path) -> None:
    """Einfacher Env-Parser (wie cognee_io.load_instance_env, aber ohne Guard).

    load_instance_env hat zwar einen env_path-Parameter, prüft aber per
    assert_instance_env die LLM-Provider einer Instanz — für die Gateway-Env
    (nur KB_API_TOKEN) ungeeignet, daher dieser kleine lokale Helper.

    Bereits gesetzte Shell-Env gewinnt (dotenv-Konvention): setdefault
    überschreibt vorhandene Variablen nicht.
    """
    import os

    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


@app.command("serve-instance")
def serve_instance(instance: str):
    """Startet den Instance Service (local | cloud) auf 127.0.0.1."""
    # Lazy-Imports: instance_service zieht cognee — nur in diesem Befehl laden.
    import uvicorn

    from kb import instance_service

    inst = get_instance(instance)
    uvicorn.run(instance_service.create_app(instance), host="127.0.0.1", port=inst.port)


@app.command("serve-mcp")
def serve_mcp(instance: str):
    """Startet den stdio-MCP-Server einer Instanz (local | cloud)."""
    # Lazy-Import (wie worker/gateway) — mcp_server bleibt cognee-frei.
    from kb import mcp_server

    get_instance(instance)  # früh fehlschlagen bei unbekannter Instanz
    mcp_server.build_server(instance).run(transport="stdio")


@app.command("serve-gateway")
def serve_gateway():
    """Startet das Gateway (Auth, Enqueue, Query-Proxy, PWA) auf Port 8800."""
    import os

    import uvicorn

    from kb import gateway  # lazy — Gateway bleibt cognee-frei
    from kb.config import GATEWAY_PORT

    env_file = ROOT / ".env.gateway"
    if env_file.is_file():
        _load_env_file(env_file)
    token = os.environ.get("KB_API_TOKEN", "")
    if not token:
        typer.echo(
            "WARNUNG: KB_API_TOKEN nicht gesetzt — alle /api-Requests werden "
            "mit 401 abgelehnt (.env.gateway aus .env.gateway.template anlegen).",
            err=True,
        )
    elif token == "CHANGE_ME":
        # Kein Abbruch — lokales Testen bleibt möglich, aber laut warnen.
        typer.echo(
            "WARNUNG: KB_API_TOKEN steht noch auf dem Platzhalter 'CHANGE_ME' "
            "— vor produktivem Betrieb ein echtes Token setzen!",
            err=True,
        )
    uvicorn.run(gateway.create_app(), host="0.0.0.0", port=GATEWAY_PORT)


if __name__ == "__main__":
    app()
