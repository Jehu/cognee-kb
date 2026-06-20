import asyncio
import fnmatch
import hashlib
from pathlib import Path

import typer

from kb import cognee_io
from kb.classify import build_payload
from kb.config import (
    GATEWAY_PORT,
    INSTANCES,
    ROOT,
    Instance,
    UnknownVaultError,
    Vault,
    get_instance,
    get_vault,
    queue_path,
    sources_path,
)
from kb.envutil import strip_quotes
from kb.queue import JobQueue
from kb.sources import SourceStore

app = typer.Typer(no_args_is_help=True)


def _load(vault: str) -> tuple[Vault, Instance]:
    """Vault + Instanz auflösen und die Cognee-Env der Instanz laden."""
    v = get_vault(vault)
    inst = get_instance(v.instance)
    cognee_io.load_instance_env(inst)
    return v, inst


@app.command()
def add(vault: str, path: Path) -> None:
    """Phase 0: eine Datei direkt ingestieren (ohne Queue)."""
    v, inst = _load(vault)
    asyncio.run(cognee_io.ingest(inst, path, v.dataset, node_sets=[]))
    typer.echo(f"ingested: {path} -> {v.dataset}")


@app.command()
def query(vault: str, question: str) -> None:
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
def eval_cmd(vault: str = "privat", out: Path = ROOT / "eval" / "antworten-cognee.md") -> None:
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
def ingest(vault: str, content: str, node_set: str = typer.Option(None)) -> None:
    """Wirft Input in die Queue des zuständigen Workers."""
    try:
        v = get_vault(vault)
    except UnknownVaultError:
        typer.echo(f"Unbekannter Vault: {vault}", err=True)
        raise typer.Exit(1) from None
    p = Path(content).expanduser()
    if p.is_file():
        # Lokales PDF → eigener PDF-Zweig (pypdf-Extraktion), kein read_text().
        if p.suffix.lower() == ".pdf":
            kind, payload = "pdf", {"path": str(p.resolve())}
        else:
            kind, payload = "file", {"path": str(p.resolve())}
    else:
        kind, payload = build_payload(content)
    if node_set:
        payload["node_set"] = node_set
    q = JobQueue(queue_path(v.instance))
    jid = q.enqueue(v.name, kind, payload)
    typer.echo(f"queued: job {jid} ({kind}) -> {v.name}")


def _is_excluded(f: Path, root: Path, patterns: list[str]) -> bool:
    """True, wenn Dateiname ODER relativer Pfad auf ein Glob-Muster passt.

    fnmatch behandelt `*` inkl. Pfadtrenner, daher deckt `_index.md` (Name),
    `_*.md` (Prefix) und `drafts/*` (Unterordner) denselben Mechanismus ab.
    """
    if not patterns:
        return False
    try:
        rel = Path(f.name) if root.is_file() else f.relative_to(root)
    except ValueError:
        rel = Path(f.name)
    rel_s = str(rel)
    return any(fnmatch.fnmatch(f.name, p) or fnmatch.fnmatch(rel_s, p) for p in patterns)


@app.command("import")
def import_cmd(
    vault: str,
    path: Path,
    node_set: str = typer.Option(None, "--node-set"),
    exclude: list[str] = typer.Option(None, "--exclude", "-x", help="Glob-Ausschluss (mehrfach)"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Importiert alle .md/.txt-Dateien unter <path> in einen Vault (Queue).

    Migration bestehender Markdown-Bestände (PRD Phase 3). Enqueued pro Datei
    einen `file`-Job — der serielle Worker übernimmt Raw-Kopie + cognee-Ingest
    (Serial-Constraint F7 bleibt gewahrt). Duplikate (gleicher Body im selben
    Vault) werden übersprungen. Vault-Routing explizit per Arg (Single-User).
    `--exclude` filtert per Glob (z. B. `_index.md`, `_*.md`, `drafts/*`).
    """
    try:
        v = get_vault(vault)
    except UnknownVaultError:
        typer.echo(f"Unbekannter Vault: {vault}", err=True)
        raise typer.Exit(1) from None
    if not path.exists():
        typer.echo(f"Pfad nicht gefunden: {path}", err=True)
        raise typer.Exit(1) from None

    if path.is_file():
        files = [path] if path.suffix.lower() in (".md", ".txt") else []
    else:
        files = sorted(p for p in path.rglob("*") if p.suffix.lower() in (".md", ".txt"))
    if not files:
        typer.echo(f"Keine .md/.txt-Dateien unter {path} gefunden.", err=True)
        raise typer.Exit(1) from None

    # SourceStore nur für den Dedup-Vorab-Check (Lesen; WAL erlaubt das neben
    # einem laufenden Worker). Der Worker prüft ohnehin nochmal authoritativ.
    store = SourceStore(sources_path(v.instance))
    q = None if dry_run else JobQueue(queue_path(v.instance))
    enqueued = skipped = excluded = 0
    for f in files:
        if _is_excluded(f, path, exclude):
            excluded += 1
            typer.echo(f"  ausgeschlossen: {f.name}")
            continue
        try:
            body = f.read_text(encoding="utf-8")
        except OSError as e:
            typer.echo(f"  übersprungen (Lesefehler): {f} — {e}", err=True)
            continue
        content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if store.find_by_hash(content_hash, v.name) is not None:
            skipped += 1
            typer.echo(f"  Duplikat (übersprungen): {f.name}")
            continue
        if dry_run:
            enqueued += 1
            typer.echo(f"  würde enqueuen: {f.name}")
            continue
        payload: dict[str, object] = {"path": str(f.resolve())}
        if node_set:
            payload["node_set"] = node_set
        assert q is not None  # dry_run ist hier False
        q.enqueue(v.name, "file", payload)
        enqueued += 1
    mode = " (--dry-run)" if dry_run else ""
    typer.echo(
        f"Import{mode}: {enqueued} enqueued, {skipped} Duplikate, "
        f"{excluded} ausgeschlossen -> {v.name}"
    )


@app.command()
def worker(instance: str) -> None:
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
        os.environ.setdefault(key.strip(), strip_quotes(value))


@app.command("serve-instance")
def serve_instance(instance: str) -> None:
    """Startet den Instance Service (local | cloud) auf 127.0.0.1."""
    # Lazy-Imports: instance_service zieht cognee — nur in diesem Befehl laden.
    import uvicorn

    from kb import instance_service

    inst = get_instance(instance)
    uvicorn.run(instance_service.create_app(instance), host="127.0.0.1", port=inst.port)


@app.command("serve-mcp")
def serve_mcp(instance: str) -> None:
    """Startet den stdio-MCP-Server einer Instanz (local | cloud)."""
    # Lazy-Import (wie worker/gateway) — mcp_server bleibt cognee-frei.
    from kb import mcp_server

    get_instance(instance)  # früh fehlschlagen bei unbekannter Instanz
    mcp_server.build_server(instance).run(transport="stdio")


@app.command("serve-gateway")
def serve_gateway() -> None:
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


def _pids_on_port(port: int) -> list[int]:
    """PIDs, die auf dem TCP-Port LISTEN. Der Port ist der eindeutige Anker —
    genau der Prozess, der den Port hält, hält auch den Kuzu-Lock (kein
    fehleranfälliges Prozessnamen-Matching)."""
    import subprocess

    try:
        out = subprocess.run(
            ["lsof", "-t", "-i", f"tcp:{port}", "-sTCP:LISTEN"], capture_output=True, text=True
        ).stdout
    except FileNotFoundError:
        raise typer.BadParameter("`lsof` nicht gefunden — `kb restart` benötigt lsof") from None
    return [int(x) for x in out.split()]


def _restart_target(target: str) -> tuple[int, list[str], Path]:
    """(Port, serve-Argv, Logdatei) für ein Restart-Ziel. KeyError bei unbekannt."""
    if target == "gateway":
        return GATEWAY_PORT, ["serve-gateway"], ROOT / "var" / "gateway.log"
    inst = get_instance(target)  # KeyError bei unbekannter Wall
    return inst.port, ["serve-instance", target], inst.var_dir / "logs" / "serve.log"


@app.command()
def restart(target: str) -> None:
    """Stoppt den Prozess auf dem Port des Ziels und startet ihn frisch (detached).

    target: eine Wall (local | cloud) -> deren Instance Service,
            'gateway' -> das Gateway, oder 'all' -> alle.

    Nötig nach kb.toml-Änderungen: die Server halten die Topologie als
    Schnappschuss vom Start (config.py lädt kb.toml nur beim Import). CLI-Befehle
    wie ingest/query lesen sie hingegen bei jedem Aufruf frisch.
    """
    import os
    import signal
    import subprocess
    import sys
    import time

    targets = [*INSTANCES.keys(), "gateway"] if target == "all" else [target]
    kb_bin = Path(sys.executable).with_name("kb")  # gleicher venv, kein uv-Overhead

    for t in targets:
        try:
            port, argv, log = _restart_target(t)
        except KeyError:
            raise typer.BadParameter(
                f"Unbekanntes Ziel {t!r} — erlaubt: {', '.join(INSTANCES)}, gateway, all"
            ) from None

        def _kill(pid: int, sig: int) -> None:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass  # schon weg

        # 1. laufenden Port-Halter beenden: SIGTERM, nach Karenz hart SIGKILL
        old = _pids_on_port(port)
        for pid in old:
            _kill(pid, signal.SIGTERM)
        for _ in range(20):
            if not _pids_on_port(port):
                break
            time.sleep(0.5)
        else:
            for pid in _pids_on_port(port):
                _kill(pid, signal.SIGKILL)
            time.sleep(0.5)

        # 2. frisch + detached starten (überlebt das Ende dieses Befehls)
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a") as f:
            proc = subprocess.Popen(
                [str(kb_bin), *argv], stdout=f, stderr=f, start_new_session=True
            )

        # 3. kurz auf Bereitschaft warten (Port wieder belegt)
        ready = False
        for _ in range(40):  # ~20s
            time.sleep(0.5)
            if _pids_on_port(port):
                ready = True
                break
        gone = ",".join(map(str, old)) if old else "(lief nicht)"
        state = "bereit" if ready else f"gestartet, noch nicht bereit — Log: {log}"
        typer.echo(f"{t}: beendet {gone} -> PID {proc.pid}, Port {port} — {state}")


if __name__ == "__main__":
    app()
