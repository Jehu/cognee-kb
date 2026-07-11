import asyncio
import fnmatch
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import typer

from kb import cognee_io, query_service
from kb.classify import build_payload
from kb.config import (
    GATEWAY_PORT,
    INSTANCES,
    ROOT,
    VAULTS,
    Instance,
    UnknownVaultError,
    Vault,
    get_instance,
    get_vault,
    queue_path,
    sources_path,
)
from kb.envutil import strip_quotes
from kb.maintenance import audit_instance
from kb.maintenance import repair as repair_maintenance
from kb.queue import JobQueue
from kb.sources import CollectionValidationError, SourceStore

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


def _collection_ids(vault: Vault, labels: list[str]) -> list[str]:
    store = SourceStore(sources_path(vault.instance))
    try:
        return store.resolve_collection_labels(vault.name, labels)
    except CollectionValidationError as exc:
        raise typer.BadParameter(str(exc), param_hint="--collection") from None
    finally:
        store.close()


@app.command("collections")
def collections_cmd(vault: str) -> None:
    """Listet aktive Sammlungen eines Vaults (read-only)."""
    try:
        v = get_vault(vault)
    except UnknownVaultError:
        raise typer.BadParameter(f"Unbekannter Vault: {vault}") from None
    store = SourceStore(sources_path(v.instance))
    try:
        for collection in store.list_collections(v.name):
            typer.echo(f"{collection.id}\t{collection.label}")
    finally:
        store.close()


@app.command()
def query(
    vault: str,
    question: str,
    collection: list[str] = typer.Option(None, "--collection", help="Sammlungsname (mehrfach)"),
) -> None:
    """Stellt eine evidenzgebundene Frage an einen Vault."""
    v, inst = _load(vault)
    store = SourceStore(sources_path(v.instance))
    try:
        kwargs = {}
        if collection:
            kwargs["collection_ids"] = _collection_ids(v, collection)
        result = asyncio.run(
            query_service.answer(inst, question, datasets=[v.dataset], store=store, **kwargs)
        )
    finally:
        store.close()
    typer.echo(result.answer or "Keine belegte Antwort möglich.")


@app.command()
def search(
    vault: str,
    question: str,
    collection: list[str] = typer.Option(None, "--collection", help="Sammlungsname (mehrfach)"),
) -> None:
    """Liefert gerankte Evidenz aus einem Vault, ohne Antwort-Synthese."""
    v, inst = _load(vault)
    store = SourceStore(sources_path(v.instance))
    try:
        kwargs = {}
        if collection:
            kwargs["collection_ids"] = _collection_ids(v, collection)
        result = asyncio.run(
            query_service.search(inst, question, datasets=[v.dataset], store=store, **kwargs)
        )
    finally:
        store.close()
    evidence = result.evidence
    if not evidence:
        typer.echo("Keine Evidenz gefunden.")
        return
    for item in evidence:
        typer.echo(f"[{item.rank}] {item.evidence_id} sources={','.join(item.source_ids) or '-'}")
        typer.echo(item.text)


@app.command("diagnose-query")
def diagnose_query(
    vault: str,
    question: str,
    show_content: bool = typer.Option(False, help="Chunk-Inhalte in der Diagnose anzeigen."),
) -> None:
    """Zeigt Retrieval-Ränge, Quellenauflösung und Laufzeiten; Inhalte standardmäßig redigiert."""
    v, inst = _load(vault)
    store = SourceStore(sources_path(v.instance))
    try:
        result = asyncio.run(
            query_service.search(inst, question, datasets=[v.dataset], store=store)
        )
    finally:
        store.close()
    typer.echo(
        json.dumps(
            query_service.diagnostic_payload(result, show_content=show_content),
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command()
def maintain(
    instance: str,
    apply_repair: str | None = typer.Option(
        None, "--apply", help="Eine Reparaturklasse anwenden: stale-jobs oder orphan-temp."
    ),
) -> None:
    """Prüft Quellen, Rohschicht und Queue; ohne --apply garantiert read-only."""
    inst = get_instance(instance)
    vaults = [vault for vault in VAULTS.values() if vault.instance == instance]
    findings = audit_instance(inst, vaults)
    for finding in findings:
        typer.echo(f"{finding.kind}\t{finding.subject}\t{finding.detail}")
    if not findings:
        typer.echo("Keine Auffälligkeiten.")
    if apply_repair:
        try:
            changed = repair_maintenance(inst, vaults, apply_repair, findings=findings)
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="--apply") from None
        typer.echo(f"Repariert: {changed}")


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
def ingest(
    vault: str,
    content: str,
    node_set: str = typer.Option(None),
    collection: list[str] = typer.Option(None, "--collection", help="Sammlungsname (mehrfach)"),
) -> None:
    """Wirft Input in die Queue des zuständigen Workers."""
    try:
        v = get_vault(vault)
    except UnknownVaultError:
        typer.echo(f"Unbekannter Vault: {vault}", err=True)
        raise typer.Exit(1) from None
    payload: dict[str, object]
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
    if collection:
        payload["collection_ids"] = _collection_ids(v, collection)
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


_DURATION_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days", "w": "weeks"}


def _parse_cutoff(value: str) -> datetime:
    """Übersetzt `--only-newer-than` in einen UTC-Zeitstempel (Cutoff).

    Akzeptiert eine Dauer (`7d`, `12h`, `30m`, `2w`) → jetzt minus Dauer, oder
    ein ISO-Datum (`2026-06-01` bzw. `2026-06-01T12:00:00`) → direkt als Cutoff.
    Naive Datumsangaben werden als UTC angenommen.
    """
    m = re.fullmatch(r"\s*(\d+)\s*([smhdw])\s*", value, re.IGNORECASE)
    if m:
        unit = _DURATION_UNITS[m.group(2).lower()]
        return datetime.now(UTC) - timedelta(**{unit: int(m.group(1))})
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError as e:
        raise typer.BadParameter(
            "--only-newer-than: Dauer (z. B. 7d/12h/30m/2w) oder ISO-Datum "
            f"(2026-06-01) erwartet, bekam {value!r}"
        ) from e
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


@app.command("import")
def import_cmd(
    vault: str,
    path: Path,
    node_set: str = typer.Option(None, "--node-set"),
    collection: list[str] = typer.Option(None, "--collection", help="Sammlungsname (mehrfach)"),
    exclude: list[str] = typer.Option(None, "--exclude", "-x", help="Glob-Ausschluss (mehrfach)"),
    only_newer_than: str = typer.Option(
        None,
        "--only-newer-than",
        help="Nur neuer als: Dauer (7d/12h/30m/2w) oder ISO-Datum (2026-06-01)",
    ),
    limit: int = typer.Option(0, "--limit", "-n", help="Höchstens N enqueued (0 = unbegrenzt)"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Importiert alle .md/.txt-Dateien unter <path> in einen Vault (Queue).

    Migration bestehender Markdown-Bestände (PRD Phase 3). Enqueued pro Datei
    einen `file`-Job — der serielle Worker übernimmt Raw-Kopie + cognee-Ingest
    (Serial-Constraint F7 bleibt gewahrt). Duplikate (gleicher Body im selben
    Vault) werden übersprungen. Vault-Routing explizit per Arg (Single-User).

    Filter/Steuerung: `--exclude` (Glob), `--only-newer-than` (Alter, mtime),
    `--limit N` (max. N enqueued), `--dry-run` (nur anzeigen).
    """
    try:
        v = get_vault(vault)
    except UnknownVaultError:
        typer.echo(f"Unbekannter Vault: {vault}", err=True)
        raise typer.Exit(1) from None
    if not path.exists():
        typer.echo(f"Pfad nicht gefunden: {path}", err=True)
        raise typer.Exit(1) from None
    cutoff = _parse_cutoff(only_newer_than) if only_newer_than else None
    collection_ids = _collection_ids(v, collection) if collection else []

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
    enqueued = skipped = excluded = too_old = 0
    for f in files:
        if limit and enqueued >= limit:
            break
        if _is_excluded(f, path, exclude):
            excluded += 1
            typer.echo(f"  ausgeschlossen: {f.name}")
            continue
        if cutoff is not None and datetime.fromtimestamp(f.stat().st_mtime, tz=UTC) < cutoff:
            too_old += 1
            typer.echo(f"  zu alt (übersprungen): {f.name}")
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
        if collection_ids:
            payload["collection_ids"] = collection_ids
        assert q is not None  # dry_run ist hier False
        q.enqueue(v.name, "file", payload)
        enqueued += 1
    mode = " (--dry-run)" if dry_run else ""
    typer.echo(
        f"Import{mode}: {enqueued} enqueued, {skipped} Duplikate, "
        f"{excluded} ausgeschlossen, {too_old} zu alt -> {v.name}"
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


# --- Process-Orchestrierung (up/down/status/logs/restart) -------------------
# Gemeinsame Basis für alle Serve-Targets. Der Port ist der eindeutige Anker —
# genau der Prozess, der den Port hält, hält auch den Kuzu-Lock (kein
# fehleranfälliges Prozessnamen-Matching).

# Serve-Targets in kanonischer Reihenfolge (Instances zuerst, dann Gateway).
# `all` und die Default-Reihenfolge für `up`/`status` nutzen diese Liste.
_ALL_TARGETS: list[str] = [*INSTANCES.keys(), "gateway"]


def _resolve_targets(target: str) -> list[str]:
    """Einzelnes Ziel oder 'all' -> Liste der Serve-Targets. BadParameter bei Unbekannt."""
    if target == "all":
        return list(_ALL_TARGETS)
    if target in _ALL_TARGETS:
        return [target]
    raise typer.BadParameter(
        f"Unbekanntes Ziel {target!r} — erlaubt: {', '.join(_ALL_TARGETS)}, all"
    )


def _target_spec(target: str) -> tuple[int, list[str], Path]:
    """(Port, serve-Argv, Logdatei) für ein Serve-Target. KeyError bei unbekannt."""
    if target == "gateway":
        return GATEWAY_PORT, ["serve-gateway"], ROOT / "var" / "gateway.log"
    inst = get_instance(target)  # KeyError bei unbekannter Wall
    return inst.port, ["serve-instance", target], inst.var_dir / "logs" / "serve.log"


def _pids_on_port(port: int) -> list[int]:
    """PIDs, die auf dem TCP-Port LISTEN."""
    try:
        out = subprocess.run(
            ["lsof", "-t", "-i", f"tcp:{port}", "-sTCP:LISTEN"], capture_output=True, text=True
        ).stdout
    except FileNotFoundError:
        raise typer.BadParameter(
            "`lsof` nicht gefunden — Process-Orchestrierung benötigt lsof"
        ) from None
    return [int(x) for x in out.split()]


def _kill_pid(pid: int, sig: int) -> None:
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        pass  # schon weg


def _kill_port(port: int, *, grace_s: int = 10) -> list[int]:
    """Beendet alle Prozesse auf dem Port: SIGTERM, nach Karenz hart SIGKILL.
    Liefert die beendeten PIDs (leer wenn der Port frei war)."""
    old = _pids_on_port(port)
    for pid in old:
        _kill_pid(pid, signal.SIGTERM)
    for _ in range(grace_s * 2):
        if not _pids_on_port(port):
            break
        time.sleep(0.5)
    else:
        for pid in _pids_on_port(port):
            _kill_pid(pid, signal.SIGKILL)
        time.sleep(0.5)
    return old


def _spawn_detached(argv: list[str], log: Path) -> int:
    """Startet `kb <argv>` detached (überlebt das Ende dieses Befehls). PID."""
    kb_bin = Path(sys.executable).with_name("kb")  # gleicher venv, kein uv-Overhead
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a") as f:
        proc = subprocess.Popen([str(kb_bin), *argv], stdout=f, stderr=f, start_new_session=True)
    return proc.pid


def _wait_port(port: int, *, timeout_s: int = 20) -> bool:
    """Wartet bis der Port belegt ist. True wenn innerhalb Timeout."""
    for _ in range(timeout_s * 2):
        time.sleep(0.5)
        if _pids_on_port(port):
            return True
    return False


@app.command()
def up(target: str = "all") -> None:
    """Startet Dienste detached (idempotent — läuft etwas schon, wird es nicht doppelt gestartet).

    target: eine Wall (local | cloud), 'gateway', oder 'all' (Default).
    """
    for t in _resolve_targets(target):
        port, argv, log = _target_spec(t)
        if _pids_on_port(port):
            typer.echo(f"{t}: läuft bereits (Port {port}) — übersprungen")
            continue
        pid = _spawn_detached(argv, log)
        ready = _wait_port(port)
        state = "bereit" if ready else f"gestartet, noch nicht bereit — Log: {log}"
        typer.echo(f"{t}: gestartet -> PID {pid}, Port {port} — {state}")


@app.command()
def down(target: str = "all") -> None:
    """Stoppt Dienste (SIGTERM, nach Karenz SIGKILL).

    target: eine Wall (local | cloud), 'gateway', oder 'all' (Default).
    """
    for t in _resolve_targets(target):
        port, _argv, _log = _target_spec(t)
        old = _kill_port(port)
        gone = ",".join(map(str, old)) if old else "(lief nicht)"
        typer.echo(f"{t}: beendet {gone} — Port {port} frei")


@app.command()
def status() -> None:
    """Zeigt den Lauf-Status aller Dienste (Port belegt? PID?)."""
    for t in _ALL_TARGETS:
        port, _argv, log = _target_spec(t)
        pids = _pids_on_port(port)
        if pids:
            typer.echo(f"  {t:12s} ✓ läuft   PID {','.join(map(str, pids)):8s}  Port {port}")
        else:
            typer.echo(f"  {t:12s} ✗ gestoppt              Port {port} frei")


@app.command()
def logs(target: str) -> None:
    """Zeigt die letzten Log-Zeilen eines Dienstes und folgt live (tail -f).

    target: eine Wall (local | cloud) oder 'gateway'.
    """
    if target not in _ALL_TARGETS:
        raise typer.BadParameter(
            f"Unbekanntes Ziel {target!r} — erlaubt: {', '.join(_ALL_TARGETS)}"
        )
    _port, _argv, log = _target_spec(target)
    if not log.is_file():
        typer.echo(f"Noch keine Log-Datei: {log}", err=True)
        raise typer.Exit(1)
    # tail -f — Strg-C bricht ab, der detach laufende Dienst läuft weiter.
    os.execvp("tail", ["tail", "-n", "50", "-f", str(log)])


@app.command()
def restart(target: str) -> None:
    """Stoppt den Prozess auf dem Port des Ziels und startet ihn frisch (detached).

    target: eine Wall (local | cloud) -> deren Instance Service,
            'gateway' -> das Gateway, oder 'all' -> alle.

    Nötig nach kb.toml-Änderungen: die Server halten die Topologie als
    Schnappschuss vom Start (config.py lädt kb.toml nur beim Import). CLI-Befehle
    wie ingest/query lesen sie hingegen bei jedem Aufruf frisch.
    """
    for t in _resolve_targets(target):
        port, argv, log = _target_spec(t)
        old = _kill_port(port)
        pid = _spawn_detached(argv, log)
        ready = _wait_port(port)
        gone = ",".join(map(str, old)) if old else "(lief nicht)"
        state = "bereit" if ready else f"gestartet, noch nicht bereit — Log: {log}"
        typer.echo(f"{t}: beendet {gone} -> PID {pid}, Port {port} — {state}")


@app.command()
def serve() -> None:
    """Startet alle Dienste im Vordergrund (für Docker PID 1, lokales Dev).

    Anders als `up` (detached) läuft dieser Befehl im Vordergrund und wartet
    auf alle Kind-Prozesse. Jede Instance läuft im eigenen Subprozess (nötig:
    cognee hält DATA_ROOT etc. prozess-global in os.environ, zwei Instances
    im selben Prozess würden sich überschreiben). Strg-C / SIGTERM fährt alle
    sauber herunter.
    """
    import signal

    # Env für das Gateway laden (die Subprozesse laden ihre eigene Env).
    env_file = ROOT / ".env.gateway"
    if env_file.is_file():
        _load_env_file(env_file)

    children: list[subprocess.Popen[bytes]] = []
    # Im Container (KB_FOREGROUND=1) erben Subprozesse stdout/stderr → Docker
    # sammelt die Logs. Lokal schreiben sie ins Logfile (für `kb logs <target>`).
    use_stdout = os.environ.get("KB_FOREGROUND") == "1"
    for t in _ALL_TARGETS:
        _port, argv, log = _target_spec(t)
        if use_stdout:
            child_stdout = None  # erbt Parent-stdout
        else:
            log.parent.mkdir(parents=True, exist_ok=True)
            child_stdout = open(log, "a")  # noqa: SIM115 — hält offen bis Programmende
        children.append(
            subprocess.Popen(
                _kb_argv(*argv),
                stdout=child_stdout,
                stderr=subprocess.STDOUT,
                env=os.environ.copy(),
            )
        )

    def _shutdown(signum: int, _frame: object) -> None:
        for c in children:
            if c.poll() is None:
                c.send_signal(signum)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # Warten bis alle Kinder beendet sind (Signal-Handler leitet SIGTERM weiter).
    for c in children:
        c.wait()


def _kb_argv(*args: str) -> list[str]:
    """Build [kb, *args] mit dem aktuellen Interpreter-Binary."""
    kb_bin = Path(sys.executable).with_name("kb")
    return [str(kb_bin), *args]


if __name__ == "__main__":
    app()
