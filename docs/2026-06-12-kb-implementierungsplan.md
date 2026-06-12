# KB Phase 0+1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validierung von Cognee (Phase 0) und Bau des Ingestion-Workers mit Multi-Vault-Routing, Provenance und Rohschicht (Phase 1).

**Architecture:** Zwei Cognee-Instanzen als getrennte Python-Worker-Prozesse (privat: Ollama-only; business: Cloud-LLM + ACL), je eigene SQLite-Job-Queue und eigene Datenpfade. Jeder Ingest erzeugt eine kanonische Rohtext-`.md` mit Frontmatter plus einen Source-Record, dann seriell `cognee.add()` + `cognee.cognify()`.

**Tech Stack:** Python 3.12, uv, cognee (gepinnt), youtube-transcript-api, trafilatura, typer, pytest, SQLite (WAL), Ollama.

**Projekt-Root:** `/Users/marco/coding/kb` (neues Git-Repo, bleibt lokal/privat)

**Scope:** Phase 0 (Validierung, Tasks 1–4, danach GATE) und Phase 1 (Worker, Tasks 5–13). Gateway/PWA (Phase 2) und MCP/Migration (Phase 3) bekommen eigene Pläne — sie hängen vom Gate-Ergebnis ab.

---

## Datei-Struktur (Zielbild)

```
kb/
├── pyproject.toml
├── .gitignore
├── .env.privat          # gitignored, aus .env.privat.template
├── .env.business        # gitignored, aus .env.business.template
├── .env.privat.template
├── .env.business.template
├── kb/
│   ├── __init__.py
│   ├── config.py        # Vault- & Instanz-Registry, Env-Loading
│   ├── guard.py         # Env-Guard (Datenschutz-Wand)
│   ├── sources.py       # SourceRecord + SQLite-Store
│   ├── rawstore.py      # Rohtext-.md mit Frontmatter schreiben
│   ├── queue.py         # SQLite-Job-Queue
│   ├── classify.py      # Input-Typ-Erkennung
│   ├── fetch_youtube.py # Transkript → Markdown
│   ├── fetch_web.py     # Webseite → Markdown
│   ├── cognee_io.py     # Kapselt ALLE Cognee-SDK-Calls
│   ├── worker.py        # serielle Worker-Loop
│   └── cli.py           # typer-CLI: ingest / worker / query / eval
├── eval/
│   ├── fragen.md        # Phase-0-Fragenkatalog (VOR dem Test fixiert)
│   └── quellen.txt      # Phase-0-Quellenliste
├── raw/                 # kanonische Rohtexte (im Git)
│   ├── privat/
│   ├── business-ki/
│   └── business-mwe/
├── var/                 # gitignored: Queues, Source-DBs, Cognee-Daten
└── tests/
```

---

## Phase 0 — Validierung

### Task 1: Projekt-Scaffold

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `kb/__init__.py`, `tests/__init__.py`, `tests/test_sanity.py`

- [ ] **Step 1: Repo + uv-Projekt anlegen**

```bash
mkdir -p /Users/marco/coding/kb && cd /Users/marco/coding/kb
git init
uv init --name kb --python 3.12
uv add "cognee==0.3.*" youtube-transcript-api trafilatura typer pyyaml
uv add --dev pytest pytest-asyncio
mkdir -p kb tests eval raw/privat raw/business-ki raw/business-mwe var
touch kb/__init__.py tests/__init__.py
```

*Hinweis: `cognee==0.3.*` ist die Pin-Vorgabe; falls `uv add` die Version nicht findet, die aktuell neueste Minor-Version pinnen und im Commit notieren.*

- [ ] **Step 2: `.gitignore` schreiben**

```gitignore
.venv/
__pycache__/
.env.privat
.env.business
var/
.pytest_cache/
```

- [ ] **Step 3: Sanity-Test schreiben** — `tests/test_sanity.py`:

```python
def test_imports():
    import kb  # noqa: F401
```

- [ ] **Step 4: Test laufen lassen**

Run: `uv run pytest -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "Scaffold kb project with uv, cognee, pytest"
```

---

### Task 2: Vault- & Instanz-Registry (`config.py`)

**Files:**
- Create: `kb/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Failing Test schreiben** — `tests/test_config.py`:

```python
import pytest
from kb.config import get_vault, get_instance, UnknownVaultError, VAULTS


def test_vault_registry_complete():
    assert set(VAULTS) == {"privat", "business-ki", "business-mwe"}


def test_privat_vault_maps_to_privat_instance():
    v = get_vault("privat")
    assert v.instance == "privat"
    assert v.dataset == "privat"
    assert v.raw_dir.name == "privat"


def test_business_vaults_share_business_instance():
    assert get_vault("business-ki").instance == "business"
    assert get_vault("business-mwe").instance == "business"


def test_unknown_vault_raises():
    with pytest.raises(UnknownVaultError):
        get_vault("nope")


def test_instance_has_env_file_and_guard_expectation():
    inst = get_instance("privat")
    assert inst.env_file.name == ".env.privat"
    assert inst.expected_llm_provider == "ollama"
    biz = get_instance("business")
    assert biz.expected_llm_provider == "custom"
```

- [ ] **Step 2: Test laufen lassen**

Run: `uv run pytest tests/test_config.py -q`
Expected: FAIL (`ModuleNotFoundError` / `ImportError`)

- [ ] **Step 3: Implementieren** — `kb/config.py`:

```python
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class UnknownVaultError(KeyError):
    pass


@dataclass(frozen=True)
class Instance:
    name: str                    # "privat" | "business"
    env_file: Path
    expected_llm_provider: str   # Guard: muss zu geladener Env passen
    expected_embedding_provider: str
    var_dir: Path                # Queue-DB, Source-DB, Cognee-Roots


@dataclass(frozen=True)
class Vault:
    name: str
    instance: str
    dataset: str
    raw_dir: Path


INSTANCES = {
    "privat": Instance(
        name="privat",
        env_file=ROOT / ".env.privat",
        expected_llm_provider="ollama",
        expected_embedding_provider="ollama",
        var_dir=ROOT / "var" / "privat",
    ),
    "business": Instance(
        name="business",
        env_file=ROOT / ".env.business",
        expected_llm_provider="custom",     # OpenRouter/Infomaniak via OpenAI-kompatiblem Endpoint
        expected_embedding_provider="ollama",
        var_dir=ROOT / "var" / "business",
    ),
}

VAULTS = {
    "privat": Vault("privat", "privat", "privat", ROOT / "raw" / "privat"),
    "business-ki": Vault("business-ki", "business", "business-ki", ROOT / "raw" / "business-ki"),
    "business-mwe": Vault("business-mwe", "business", "business-mwe", ROOT / "raw" / "business-mwe"),
}


def get_vault(name: str) -> Vault:
    try:
        return VAULTS[name]
    except KeyError:
        raise UnknownVaultError(name) from None


def get_instance(name: str) -> Instance:
    return INSTANCES[name]
```

- [ ] **Step 4: Test laufen lassen**

Run: `uv run pytest tests/test_config.py -q`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add kb/config.py tests/test_config.py
git commit -m "Add vault and instance registry"
```

---

### Task 3: Env-Templates + Env-Guard (`guard.py`)

**Files:**
- Create: `.env.privat.template`, `.env.business.template`, `kb/guard.py`
- Test: `tests/test_guard.py`

- [ ] **Step 1: Templates schreiben** — `.env.privat.template`:

```bash
# Privat-Instanz: ALLES lokal. Kein Cloud-Call, auch nicht query-seitig.
LLM_PROVIDER=ollama
LLM_MODEL=ollama/qwen3:14b
LLM_ENDPOINT=http://localhost:11434/v1

EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_DIMENSIONS=768
EMBEDDING_ENDPOINT=http://localhost:11434
EMBEDDING_BATCH_SIZE=8
HUGGINGFACE_TOKENIZER=nomic-ai/nomic-embed-text-v1.5

# Getrennte Datenpfade — Pflicht bei zwei Instanzen auf einem Host!
DATA_ROOT_DIRECTORY=/Users/marco/coding/kb/var/privat/cognee_data
SYSTEM_ROOT_DIRECTORY=/Users/marco/coding/kb/var/privat/cognee_system
CACHE_ROOT_DIRECTORY=/Users/marco/coding/kb/var/privat/cognee_cache
COGNEE_LOGS_DIR=/Users/marco/coding/kb/var/privat/logs
```

`.env.business.template`:

```bash
# Business-Instanz: Cloud-LLM, lokale Embeddings, ACL fuer Dataset-Scoping.
LLM_PROVIDER=custom
LLM_MODEL=openrouter/anthropic/claude-sonnet-4-6
LLM_ENDPOINT=https://openrouter.ai/api/v1
LLM_API_KEY=CHANGE_ME

EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_DIMENSIONS=768
EMBEDDING_ENDPOINT=http://localhost:11434
EMBEDDING_BATCH_SIZE=8
HUGGINGFACE_TOKENIZER=nomic-ai/nomic-embed-text-v1.5

# Ohne dieses Flag ignoriert search() den datasets-Parameter (alle Daten!).
ENABLE_BACKEND_ACCESS_CONTROL=true

DATA_ROOT_DIRECTORY=/Users/marco/coding/kb/var/business/cognee_data
SYSTEM_ROOT_DIRECTORY=/Users/marco/coding/kb/var/business/cognee_system
CACHE_ROOT_DIRECTORY=/Users/marco/coding/kb/var/business/cognee_cache
COGNEE_LOGS_DIR=/Users/marco/coding/kb/var/business/logs
```

- [ ] **Step 2: Failing Test schreiben** — `tests/test_guard.py`:

```python
import pytest
from kb.config import get_instance
from kb.guard import EnvGuardError, assert_instance_env


def test_guard_passes_when_env_matches(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "ollama")
    assert_instance_env(get_instance("privat"))  # darf nicht werfen


def test_guard_blocks_cloud_llm_on_privat(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "custom")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "ollama")
    with pytest.raises(EnvGuardError, match="LLM_PROVIDER"):
        assert_instance_env(get_instance("privat"))


def test_guard_blocks_cloud_embeddings_on_privat(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    with pytest.raises(EnvGuardError, match="EMBEDDING_PROVIDER"):
        assert_instance_env(get_instance("privat"))


def test_guard_blocks_missing_env(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    with pytest.raises(EnvGuardError):
        assert_instance_env(get_instance("privat"))
```

- [ ] **Step 3: Test laufen lassen**

Run: `uv run pytest tests/test_guard.py -q`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 4: Implementieren** — `kb/guard.py`:

```python
import os

from kb.config import Instance


class EnvGuardError(RuntimeError):
    """Die geladene Env passt nicht zur Instanz — Abbruch vor jedem Cognee-Call."""


def assert_instance_env(instance: Instance) -> None:
    checks = {
        "LLM_PROVIDER": instance.expected_llm_provider,
        "EMBEDDING_PROVIDER": instance.expected_embedding_provider,
    }
    for var, expected in checks.items():
        actual = os.environ.get(var)
        if actual != expected:
            raise EnvGuardError(
                f"{var}={actual!r}, erwartet {expected!r} für Instanz "
                f"'{instance.name}'. Falsches Env-File geladen?"
            )
```

- [ ] **Step 5: Test laufen lassen**

Run: `uv run pytest tests/test_guard.py -q`
Expected: `4 passed`

- [ ] **Step 6: Echte Env-Files aus Templates erzeugen**

```bash
cp .env.privat.template .env.privat
cp .env.business.template .env.business
# .env.business: LLM_API_KEY eintragen (OpenRouter-Key)
```

- [ ] **Step 7: Commit**

```bash
git add .env.privat.template .env.business.template kb/guard.py tests/test_guard.py
git commit -m "Add env templates and instance env guard"
```

---

### Task 4: Phase-0-Harness (`cognee_io.py` Grundform + Eval-Skript)

**Files:**
- Create: `kb/cognee_io.py`, `kb/cli.py`, `eval/fragen.md`, `eval/quellen.txt`
- Test: `tests/test_cognee_io.py`

- [ ] **Step 1: Failing Test schreiben** — `tests/test_cognee_io.py` (testet das Env-Loading, nicht Cognee selbst):

```python
from kb.cognee_io import load_instance_env
from kb.config import get_instance


def test_load_instance_env_sets_vars(tmp_path, monkeypatch):
    env_file = tmp_path / ".env.test"
    env_file.write_text('LLM_PROVIDER=ollama\n# Kommentar\nEMBEDDING_PROVIDER=ollama\n')
    inst = get_instance("privat")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    load_instance_env(inst, env_path=env_file)
    import os
    assert os.environ["LLM_PROVIDER"] == "ollama"
```

- [ ] **Step 2: Test laufen lassen**

Run: `uv run pytest tests/test_cognee_io.py -q`
Expected: FAIL

- [ ] **Step 3: Implementieren** — `kb/cognee_io.py`:

```python
"""Kapselt ALLE Cognee-SDK-Zugriffe. Nichts außerhalb dieses Moduls importiert cognee."""
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
    return "\n".join(str(r) for r in results)
```

*Hinweis: Cognee ist API-instabil. Wenn `cognee.add`/`search` in der gepinnten Version andere Parameternamen haben (`dataset_name` vs `datasets`), hier anpassen — deshalb existiert diese Kapselung.*

- [ ] **Step 4: CLI-Grundform** — `kb/cli.py`:

```python
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
```

In `pyproject.toml` ergänzen:

```toml
[project.scripts]
kb = "kb.cli:app"
```

- [ ] **Step 5: Fragenkatalog VOR dem Test fixieren** — `eval/fragen.md`:

```markdown
# Phase-0-Fragen (fixiert VOR dem ersten Cognee-Ingest — nicht mehr ändern!)

Bewertung: Blind-Vergleich. Antworten von Cognee und json-GraphRAG ohne Label
nebeneinander, pro Frage Gewinner markieren. Cognee muss >= 6/10 gewinnen.

- <Frage 1: echte Synthese-Frage über mehrere Quellen, von Marco einzutragen>
- <Frage 2 …>
```

`eval/quellen.txt`: 10 echte Quellen (YouTube-URLs, Weblinks), eine pro Zeile — von Marco zu befüllen.

- [ ] **Step 6: Alle Tests laufen lassen**

Run: `uv run pytest -q`
Expected: alle bisherigen Tests `passed`

- [ ] **Step 7: Phase 0 manuell durchführen**

```bash
# Ollama-Modelle bereitstellen
ollama pull qwen3:14b && ollama pull nomic-embed-text

# Quellen ingestieren (Transkripte/Texte vorerst manuell als .md ablegen)
uv run kb add privat raw/privat/quelle-01.md   # … für alle ~10 Quellen
# Dabei messen: Dauer pro cognify auf deiner Hardware notieren!

uv run kb eval --vault privat
```

Danach: Antworten des bestehenden json-GraphRAG zu denselben Fragen in `eval/antworten-vergleich.md` einfügen, Labels mischen, blind bewerten.

- [ ] **Step 8: Bleed-Test der Business-Instanz**

```bash
# Zwei Mini-Datasets in der Business-Instanz anlegen:
uv run kb add business-ki raw/business-ki/test-a.md    # Inhalt: "Der Codename ist AZURIT."
uv run kb add business-mwe raw/business-mwe/test-b.md  # Inhalt: "Der Codename ist KORALLE."
uv run kb query business-ki "Welcher Codename ist bekannt?"
```

Expected: Antwort enthält AZURIT, **nicht** KORALLE. Wenn doch → Dataset-Bleed (cognee#1023), Architektur-Eskalation: drei Instanzen statt zwei.

- [ ] **Step 9: Commit + GATE-Entscheidung**

```bash
git add -A && git commit -m "Add phase-0 harness: direct ingest, query, blind-eval CLI"
```

> **🚦 GATE:** Weiter zu Task 5 nur, wenn (a) Cognee den Blind-Vergleich ≥ 6/10 gewinnt, (b) Ingest-Dauer pro Quelle akzeptabel ist, (c) kein Dataset-Bleed. Sonst: Stopp, Architektur-Doc-Annahme falsifiziert.

---

## Phase 1 — Ingestion-Worker

### Task 5: SourceRecord + Source-Store (`sources.py`)

**Files:**
- Create: `kb/sources.py`
- Test: `tests/test_sources.py`

- [ ] **Step 1: Failing Test schreiben** — `tests/test_sources.py`:

```python
from kb.sources import SourceRecord, SourceStore


def make_record(**over):
    base = dict(
        type="youtube", url="https://youtu.be/abc12345678", video_id="abc12345678",
        locator=None, vault="privat", raw_md_path="raw/privat/x.md",
    )
    base.update(over)
    return SourceRecord.new(**base)


def test_new_record_gets_id_and_fetched_at():
    r = make_record()
    assert len(r.id) == 36          # uuid4
    assert r.fetched_at.endswith("Z")


def test_roundtrip(tmp_path):
    store = SourceStore(tmp_path / "sources.db")
    r = make_record()
    store.insert(r)
    got = store.get(r.id)
    assert got == r


def test_frontmatter_renders_all_fields():
    r = make_record(locator="00:12:30")
    fm = r.frontmatter()
    assert fm.startswith("---\n") and fm.rstrip().endswith("---")
    for needle in ("source_id:", "type: youtube", "video_id: abc12345678",
                   "locator: '00:12:30'", "vault: privat"):
        assert needle in fm
```

- [ ] **Step 2: Test laufen lassen**

Run: `uv run pytest tests/test_sources.py -q`
Expected: FAIL

- [ ] **Step 3: Implementieren** — `kb/sources.py`:

```python
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    url TEXT,
    video_id TEXT,
    locator TEXT,
    fetched_at TEXT NOT NULL,
    vault TEXT NOT NULL,
    raw_md_path TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class SourceRecord:
    id: str
    type: str          # youtube | web | snippet | file
    url: str | None
    video_id: str | None
    locator: str | None
    fetched_at: str    # ISO-8601 UTC
    vault: str
    raw_md_path: str

    @classmethod
    def new(cls, **kwargs) -> "SourceRecord":
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return cls(id=str(uuid.uuid4()), fetched_at=now, **kwargs)

    def frontmatter(self) -> str:
        data = asdict(self)
        data["source_id"] = data.pop("id")
        body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True,
                              default_flow_style=False)
        return f"---\n{body}---\n"


class SourceStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    def insert(self, r: SourceRecord) -> None:
        self.conn.execute(
            "INSERT INTO sources VALUES (?,?,?,?,?,?,?,?)",
            (r.id, r.type, r.url, r.video_id, r.locator, r.fetched_at,
             r.vault, r.raw_md_path),
        )
        self.conn.commit()

    def get(self, source_id: str) -> SourceRecord | None:
        row = self.conn.execute(
            "SELECT id,type,url,video_id,locator,fetched_at,vault,raw_md_path "
            "FROM sources WHERE id=?", (source_id,)).fetchone()
        if row is None:
            return None
        return SourceRecord(*row)
```

*Hinweis zu `locator: '00:12:30'` im Test: yaml.safe_dump quotet Strings mit Doppelpunkten automatisch.*

- [ ] **Step 4: Test laufen lassen**

Run: `uv run pytest tests/test_sources.py -q`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add kb/sources.py tests/test_sources.py
git commit -m "Add source record model and sqlite store"
```

---

### Task 6: Rohschicht-Writer (`rawstore.py`)

**Files:**
- Create: `kb/rawstore.py`
- Test: `tests/test_rawstore.py`

- [ ] **Step 1: Failing Test schreiben** — `tests/test_rawstore.py`:

```python
from kb.rawstore import slugify, write_raw
from kb.sources import SourceRecord


def test_slugify():
    assert slugify("Künstliche Intelligenz: Ein Überblick!") == "kuenstliche-intelligenz-ein-ueberblick"
    assert slugify("  --weird--  input  ") == "weird-input"


def test_write_raw_creates_file_with_frontmatter(tmp_path):
    r = SourceRecord.new(type="snippet", url=None, video_id=None, locator=None,
                         vault="privat", raw_md_path="")
    path = write_raw(tmp_path, title="Mein Snippet", body="Inhalt.", record=r)
    text = path.read_text()
    assert path.name.endswith("-mein-snippet.md")
    assert text.startswith("---\n")
    assert "source_id: " + r.id in text
    assert text.rstrip().endswith("Inhalt.")


def test_write_raw_avoids_collisions(tmp_path):
    r1 = SourceRecord.new(type="snippet", url=None, video_id=None, locator=None,
                          vault="privat", raw_md_path="")
    r2 = SourceRecord.new(type="snippet", url=None, video_id=None, locator=None,
                          vault="privat", raw_md_path="")
    p1 = write_raw(tmp_path, "Titel", "a", r1)
    p2 = write_raw(tmp_path, "Titel", "b", r2)
    assert p1 != p2
```

- [ ] **Step 2: Test laufen lassen**

Run: `uv run pytest tests/test_rawstore.py -q`
Expected: FAIL

- [ ] **Step 3: Implementieren** — `kb/rawstore.py`:

```python
import dataclasses
import re
from datetime import date
from pathlib import Path

from kb.sources import SourceRecord

UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
                         "Ä": "ae", "Ö": "oe", "Ü": "ue"})


def slugify(text: str) -> str:
    text = text.translate(UMLAUTS).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def write_raw(raw_dir: Path, title: str, body: str, record: SourceRecord) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{date.today().isoformat()}-{slugify(title)[:60]}"
    path = raw_dir / f"{stem}.md"
    n = 1
    while path.exists():
        n += 1
        path = raw_dir / f"{stem}-{n}.md"
    record = dataclasses.replace(record, raw_md_path=str(path))
    path.write_text(f"{record.frontmatter()}\n# {title}\n\n{body}\n")
    return path
```

*Achtung Stolperfalle: `write_raw` ersetzt `raw_md_path` per `dataclasses.replace` — der Aufrufer (Worker, Task 11) muss den Record mit gesetztem Pfad in den Store schreiben. Deshalb gibt der Worker `write_raw` den Record VOR dem `store.insert`.*

Korrektur für saubere Schnittstelle — `write_raw` gibt beides zurück. Finale Version:

```python
def write_raw(raw_dir: Path, title: str, body: str,
              record: SourceRecord) -> tuple[Path, SourceRecord]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{date.today().isoformat()}-{slugify(title)[:60]}"
    path = raw_dir / f"{stem}.md"
    n = 1
    while path.exists():
        n += 1
        path = raw_dir / f"{stem}-{n}.md"
    record = dataclasses.replace(record, raw_md_path=str(path))
    path.write_text(f"{record.frontmatter()}\n# {title}\n\n{body}\n")
    return path, record
```

Tests entsprechend anpassen: `path, r = write_raw(...)` und `r.raw_md_path == str(path)` zusätzlich asserten.

- [ ] **Step 4: Test laufen lassen**

Run: `uv run pytest tests/test_rawstore.py -q`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add kb/rawstore.py tests/test_rawstore.py
git commit -m "Add raw markdown writer with frontmatter provenance"
```

---

### Task 7: Job-Queue (`queue.py`)

**Files:**
- Create: `kb/queue.py`
- Test: `tests/test_queue.py`

- [ ] **Step 1: Failing Test schreiben** — `tests/test_queue.py`:

```python
from kb.queue import JobQueue


def test_enqueue_and_claim(tmp_path):
    q = JobQueue(tmp_path / "q.db")
    job_id = q.enqueue(vault="privat", kind="youtube",
                       payload={"url": "https://youtu.be/abc12345678"})
    job = q.claim_next()
    assert job.id == job_id
    assert job.kind == "youtube"
    assert job.payload["url"].endswith("abc12345678")
    assert q.claim_next() is None  # running blockiert weiteren Claim


def test_done_and_failed(tmp_path):
    q = JobQueue(tmp_path / "q.db")
    a = q.enqueue("privat", "snippet", {"text": "x"})
    b = q.enqueue("privat", "snippet", {"text": "y"})
    j1 = q.claim_next()
    q.mark_done(j1.id)
    j2 = q.claim_next()
    q.mark_failed(j2.id, "kaputt")
    assert q.status(a) == "done"
    assert q.status(b) == "failed"
    assert q.claim_next() is None
```

- [ ] **Step 2: Test laufen lassen**

Run: `uv run pytest tests/test_queue.py -q`
Expected: FAIL

- [ ] **Step 3: Implementieren** — `kb/queue.py`:

```python
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vault TEXT NOT NULL,
    kind TEXT NOT NULL,           -- youtube | web | snippet | file
    payload TEXT NOT NULL,        -- JSON
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
"""


@dataclass(frozen=True)
class Job:
    id: int
    vault: str
    kind: str
    payload: dict


class JobQueue:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    def enqueue(self, vault: str, kind: str, payload: dict) -> int:
        cur = self.conn.execute(
            "INSERT INTO jobs (vault, kind, payload) VALUES (?,?,?)",
            (vault, kind, json.dumps(payload)))
        self.conn.commit()
        return cur.lastrowid

    def claim_next(self) -> Job | None:
        row = self.conn.execute(
            "UPDATE jobs SET status='running' WHERE id = ("
            "  SELECT id FROM jobs WHERE status='pending' ORDER BY id LIMIT 1"
            ") RETURNING id, vault, kind, payload").fetchone()
        self.conn.commit()
        if row is None:
            return None
        return Job(row[0], row[1], row[2], json.loads(row[3]))

    def mark_done(self, job_id: int) -> None:
        self.conn.execute("UPDATE jobs SET status='done' WHERE id=?", (job_id,))
        self.conn.commit()

    def mark_failed(self, job_id: int, error: str) -> None:
        self.conn.execute(
            "UPDATE jobs SET status='failed', error=? WHERE id=?", (error, job_id))
        self.conn.commit()

    def status(self, job_id: int) -> str | None:
        row = self.conn.execute(
            "SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        return row[0] if row else None
```

- [ ] **Step 4: Test laufen lassen**

Run: `uv run pytest tests/test_queue.py -q`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add kb/queue.py tests/test_queue.py
git commit -m "Add sqlite job queue with serial claim semantics"
```

---

### Task 8: Typ-Erkennung (`classify.py`)

**Files:**
- Create: `kb/classify.py`
- Test: `tests/test_classify.py`

- [ ] **Step 1: Failing Test schreiben** — `tests/test_classify.py`:

```python
import pytest
from kb.classify import classify


@pytest.mark.parametrize("inp,kind", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube"),
    ("https://youtu.be/dQw4w9WgXcQ?t=42", "youtube"),
    ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "youtube"),
    ("https://example.com/artikel", "web"),
    ("http://blog.fefe.de/?ts=99", "web"),
    ("Nur ein Gedanke ohne Link.", "snippet"),
    ("Text mit URL drin https://example.com aber Text dominiert", "snippet"),
])
def test_classify(inp, kind):
    assert classify(inp).kind == kind


def test_youtube_extracts_video_id():
    c = classify("https://youtu.be/dQw4w9WgXcQ")
    assert c.video_id == "dQw4w9WgXcQ"
```

- [ ] **Step 2: Test laufen lassen**

Run: `uv run pytest tests/test_classify.py -q`
Expected: FAIL

- [ ] **Step 3: Implementieren** — `kb/classify.py`:

```python
import re
from dataclasses import dataclass

YOUTUBE_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)([\w-]{11})")
URL_RE = re.compile(r"^https?://\S+$")


@dataclass(frozen=True)
class Classified:
    kind: str               # youtube | web | snippet
    video_id: str | None = None


def classify(text: str) -> Classified:
    text = text.strip()
    if URL_RE.match(text):
        m = YOUTUBE_RE.search(text)
        if m:
            return Classified("youtube", video_id=m.group(1))
        return Classified("web")
    return Classified("snippet")
```

- [ ] **Step 4: Test laufen lassen**

Run: `uv run pytest tests/test_classify.py -q`
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add kb/classify.py tests/test_classify.py
git commit -m "Add input type classification"
```

---

### Task 9: YouTube-Fetcher (`fetch_youtube.py`)

**Files:**
- Create: `kb/fetch_youtube.py`
- Test: `tests/test_fetch_youtube.py`

- [ ] **Step 1: Failing Test schreiben** — `tests/test_fetch_youtube.py` (Netzwerk gemockt; nur die pure Formatierung wird real getestet):

```python
from kb.fetch_youtube import transcript_to_markdown


def test_transcript_to_markdown_with_timestamps():
    segments = [
        {"start": 0.0, "text": "Hallo und willkommen."},
        {"start": 65.5, "text": "Zweiter Punkt."},
        {"start": 3661.0, "text": "Nach einer Stunde."},
    ]
    md = transcript_to_markdown(segments)
    assert "[00:00] Hallo und willkommen." in md
    assert "[01:05] Zweiter Punkt." in md
    assert "[61:01] Nach einer Stunde." in md
```

- [ ] **Step 2: Test laufen lassen**

Run: `uv run pytest tests/test_fetch_youtube.py -q`
Expected: FAIL

- [ ] **Step 3: Implementieren** — `kb/fetch_youtube.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class FetchedDoc:
    title: str
    body: str
    url: str | None = None
    video_id: str | None = None
    locator: str | None = None


def transcript_to_markdown(segments: list[dict]) -> str:
    lines = []
    for seg in segments:
        m, s = divmod(int(seg["start"]), 60)
        lines.append(f"[{m:02d}:{s:02d}] {seg['text']}")
    return "\n".join(lines)


def fetch(url: str, video_id: str) -> FetchedDoc:
    """Holt Transkript (de bevorzugt, en als Fallback). Wirft bei fehlendem Transkript."""
    from youtube_transcript_api import YouTubeTranscriptApi

    api = YouTubeTranscriptApi()
    fetched = api.fetch(video_id, languages=["de", "en"])
    segments = [{"start": s.start, "text": s.text} for s in fetched]
    return FetchedDoc(
        title=f"YouTube {video_id}",
        body=transcript_to_markdown(segments),
        url=url,
        video_id=video_id,
    )
```

*Hinweis: `youtube-transcript-api` ≥ 1.0 nutzt die Instanz-API (`YouTubeTranscriptApi().fetch`). Bei älterer Version: `YouTubeTranscriptApi.get_transcript(video_id, languages=[...])` — liefert direkt list[dict]. Beim Implementieren die installierte Version prüfen (`uv pip show youtube-transcript-api`).*

- [ ] **Step 4: Test laufen lassen**

Run: `uv run pytest tests/test_fetch_youtube.py -q`
Expected: `1 passed`

- [ ] **Step 5: Manueller Smoke-Test mit echtem Video**

Run: `uv run python -c "from kb.fetch_youtube import fetch; d = fetch('https://youtu.be/dQw4w9WgXcQ', 'dQw4w9WgXcQ'); print(d.body[:200])"`
Expected: Transkriptzeilen mit `[mm:ss]`-Präfix

- [ ] **Step 6: Commit**

```bash
git add kb/fetch_youtube.py tests/test_fetch_youtube.py
git commit -m "Add youtube transcript fetcher with timestamp markdown"
```

---

### Task 10: Web-Fetcher (`fetch_web.py`)

**Files:**
- Create: `kb/fetch_web.py`
- Test: `tests/test_fetch_web.py`

- [ ] **Step 1: Failing Test schreiben** — `tests/test_fetch_web.py`:

```python
from unittest.mock import patch

from kb.fetch_web import fetch


def test_fetch_extracts_title_and_text():
    html = "<html><head><title>Mein Artikel</title></head><body><article><p>Inhalt des Artikels.</p></article></body></html>"
    with patch("trafilatura.fetch_url", return_value=html):
        doc = fetch("https://example.com/artikel")
    assert doc.url == "https://example.com/artikel"
    assert "Inhalt des Artikels." in doc.body
    assert doc.title  # trafilatura extrahiert den Titel aus Metadaten


def test_fetch_raises_on_empty_page():
    import pytest
    with patch("trafilatura.fetch_url", return_value=None):
        with pytest.raises(RuntimeError, match="nicht laden"):
            fetch("https://example.com/down")
```

- [ ] **Step 2: Test laufen lassen**

Run: `uv run pytest tests/test_fetch_web.py -q`
Expected: FAIL

- [ ] **Step 3: Implementieren** — `kb/fetch_web.py`:

```python
import trafilatura

from kb.fetch_youtube import FetchedDoc


def fetch(url: str) -> FetchedDoc:
    html = trafilatura.fetch_url(url)
    if html is None:
        raise RuntimeError(f"Konnte {url} nicht laden")
    text = trafilatura.extract(html, output_format="markdown", with_metadata=False)
    if not text:
        raise RuntimeError(f"Kein extrahierbarer Text auf {url}")
    meta = trafilatura.extract_metadata(html)
    title = (meta.title if meta and meta.title else url)
    return FetchedDoc(title=title, body=text, url=url)
```

- [ ] **Step 4: Test laufen lassen**

Run: `uv run pytest tests/test_fetch_web.py -q`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add kb/fetch_web.py tests/test_fetch_web.py
git commit -m "Add web article fetcher via trafilatura"
```

---

### Task 11: Worker-Loop (`worker.py`)

**Files:**
- Create: `kb/worker.py`
- Test: `tests/test_worker.py`

- [ ] **Step 1: Failing Test schreiben** — `tests/test_worker.py`:

```python
from pathlib import Path
from unittest.mock import AsyncMock, patch

from kb.config import Vault
from kb.queue import JobQueue
from kb.sources import SourceStore
from kb.worker import process_one


def make_vault(tmp_path) -> Vault:
    return Vault(name="privat", instance="privat", dataset="privat",
                 raw_dir=tmp_path / "raw")


def test_process_one_snippet_full_chain(tmp_path):
    q = JobQueue(tmp_path / "q.db")
    store = SourceStore(tmp_path / "s.db")
    q.enqueue("privat", "snippet", {"text": "Wichtiger Gedanke.", "title": "Notiz"})
    ingest_mock = AsyncMock()
    with patch("kb.worker.get_vault", return_value=make_vault(tmp_path)), \
         patch("kb.cognee_io.ingest", ingest_mock):
        worked = process_one(instance=None, q=q, store=store)
    assert worked is True
    # Rohdatei existiert und enthält Frontmatter + Text
    files = list((tmp_path / "raw").glob("*.md"))
    assert len(files) == 1
    assert "Wichtiger Gedanke." in files[0].read_text()
    # Source-Record zeigt auf die Datei
    ingest_mock.assert_awaited_once()
    # Job ist done
    assert q.claim_next() is None


def test_process_one_marks_failed_on_fetch_error(tmp_path):
    q = JobQueue(tmp_path / "q.db")
    store = SourceStore(tmp_path / "s.db")
    jid = q.enqueue("privat", "web", {"url": "https://example.com/down"})
    with patch("kb.worker.get_vault", return_value=make_vault(tmp_path)), \
         patch("kb.fetch_web.fetch", side_effect=RuntimeError("offline")):
        worked = process_one(instance=None, q=q, store=store)
    assert worked is True
    assert q.status(jid) == "failed"


def test_process_one_returns_false_on_empty_queue(tmp_path):
    q = JobQueue(tmp_path / "q.db")
    store = SourceStore(tmp_path / "s.db")
    assert process_one(instance=None, q=q, store=store) is False
```

- [ ] **Step 2: Test laufen lassen**

Run: `uv run pytest tests/test_worker.py -q`
Expected: FAIL

- [ ] **Step 3: Implementieren** — `kb/worker.py`:

```python
import asyncio
import time

from kb import cognee_io, fetch_web, fetch_youtube, rawstore
from kb.config import Instance, get_vault
from kb.fetch_youtube import FetchedDoc
from kb.queue import JobQueue
from kb.sources import SourceRecord, SourceStore


def _fetch(kind: str, payload: dict) -> FetchedDoc:
    if kind == "youtube":
        return fetch_youtube.fetch(payload["url"], payload["video_id"])
    if kind == "web":
        return fetch_web.fetch(payload["url"])
    if kind == "snippet":
        return FetchedDoc(title=payload.get("title", "Snippet"),
                          body=payload["text"])
    if kind == "file":
        from pathlib import Path
        p = Path(payload["path"])
        return FetchedDoc(title=p.stem, body=p.read_text())
    raise ValueError(f"Unbekannter Job-Typ: {kind}")


def process_one(instance: Instance | None, q: JobQueue, store: SourceStore) -> bool:
    """Verarbeitet genau einen Job. True = es gab Arbeit, False = Queue leer."""
    job = q.claim_next()
    if job is None:
        return False
    try:
        vault = get_vault(job.vault)
        doc = _fetch(job.kind, job.payload)
        record = SourceRecord.new(
            type=job.kind, url=doc.url, video_id=doc.video_id,
            locator=doc.locator, vault=vault.name, raw_md_path="")
        path, record = rawstore.write_raw(vault.raw_dir, doc.title, doc.body, record)
        store.insert(record)
        node_sets = job.payload.get("node_set")
        asyncio.run(cognee_io.ingest(
            instance, path, vault.dataset,
            node_sets=[node_sets] if node_sets else []))
        q.mark_done(job.id)
    except Exception as e:  # noqa: BLE001 — Worker darf nie sterben
        q.mark_failed(job.id, f"{type(e).__name__}: {e}")
    return True


def run_forever(instance: Instance, q: JobQueue, store: SourceStore,
                poll_seconds: float = 5.0) -> None:
    cognee_io.load_instance_env(instance)
    while True:
        if not process_one(instance, q, store):
            time.sleep(poll_seconds)
```

- [ ] **Step 4: Test laufen lassen**

Run: `uv run pytest tests/test_worker.py -q`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add kb/worker.py tests/test_worker.py
git commit -m "Add serial worker loop: fetch, raw copy, provenance, cognee ingest"
```

---

### Task 12: CLI komplettieren (`cli.py`)

**Files:**
- Modify: `kb/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Failing Test schreiben** — `tests/test_cli.py`:

```python
from typer.testing import CliRunner

from kb.cli import app

runner = CliRunner()


def test_ingest_enqueues_youtube(tmp_path, monkeypatch):
    monkeypatch.setattr("kb.cli.queue_path", lambda inst: tmp_path / f"{inst}.db")
    result = runner.invoke(app, ["ingest", "privat",
                                 "https://youtu.be/dQw4w9WgXcQ"])
    assert result.exit_code == 0
    assert "queued" in result.output
    assert "youtube" in result.output


def test_ingest_rejects_unknown_vault(tmp_path, monkeypatch):
    monkeypatch.setattr("kb.cli.queue_path", lambda inst: tmp_path / f"{inst}.db")
    result = runner.invoke(app, ["ingest", "geheim", "text"])
    assert result.exit_code != 0
```

- [ ] **Step 2: Test laufen lassen**

Run: `uv run pytest tests/test_cli.py -q`
Expected: FAIL

- [ ] **Step 3: CLI erweitern** — in `kb/cli.py` ergänzen (bestehende Phase-0-Commands bleiben):

```python
from pathlib import Path

from kb.classify import classify
from kb.config import UnknownVaultError
from kb.queue import JobQueue
from kb.sources import SourceStore


def queue_path(instance_name: str) -> Path:
    from kb.config import get_instance
    return get_instance(instance_name).var_dir / "queue.db"


@app.command()
def ingest(vault: str, content: str, node_set: str = typer.Option(None)):
    """Wirft Input in die Queue des zuständigen Workers."""
    try:
        v = get_vault(vault)
    except UnknownVaultError:
        typer.echo(f"Unbekannter Vault: {vault}", err=True)
        raise typer.Exit(1)
    c = classify(content)
    payload: dict = {"node_set": node_set} if node_set else {}
    if c.kind == "youtube":
        payload |= {"url": content.strip(), "video_id": c.video_id}
    elif c.kind == "web":
        payload |= {"url": content.strip()}
    else:
        payload |= {"text": content, "title": content[:50]}
    q = JobQueue(queue_path(v.instance))
    jid = q.enqueue(v.name, c.kind, payload)
    typer.echo(f"queued: job {jid} ({c.kind}) -> {v.name}")


@app.command()
def worker(instance: str):
    """Startet den seriellen Worker einer Instanz (privat | business)."""
    from kb import worker as worker_mod
    from kb.config import get_instance
    inst = get_instance(instance)
    q = JobQueue(inst.var_dir / "queue.db")
    store = SourceStore(inst.var_dir / "sources.db")
    typer.echo(f"Worker '{instance}' läuft (seriell, Strg-C zum Beenden)")
    worker_mod.run_forever(inst, q, store)
```

- [ ] **Step 4: Test laufen lassen**

Run: `uv run pytest -q`
Expected: alle Tests `passed`

- [ ] **Step 5: End-to-End-Smoke-Test (echt, Privat-Instanz)**

```bash
uv run kb ingest privat "https://youtu.be/<echtes-video>"
uv run kb worker privat   # in zweitem Terminal; wartet, verarbeitet Job, dann Strg-C
uv run kb query privat "Worum geht es im Video?"
```

Expected: Antwort mit Inhalt aus dem Video; `raw/privat/` enthält neue `.md` mit Frontmatter; `var/privat/sources.db` enthält den Record.

- [ ] **Step 6: Commit**

```bash
git add kb/cli.py tests/test_cli.py
git commit -m "Add ingest and worker CLI commands"
```

---

### Task 13: Betrieb — launchd-Services für beide Worker

**Files:**
- Create: `ops/de.michelyweb.kb.worker-privat.plist`, `ops/de.michelyweb.kb.worker-business.plist`, `ops/install.sh`

- [ ] **Step 1: plist schreiben** — `ops/de.michelyweb.kb.worker-privat.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>de.michelyweb.kb.worker-privat</string>
    <key>ProgramArguments</key>
    <array>
        <string>/opt/homebrew/bin/uv</string>
        <string>run</string><string>kb</string>
        <string>worker</string><string>privat</string>
    </array>
    <key>WorkingDirectory</key><string>/Users/marco/coding/kb</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>/Users/marco/coding/kb/var/privat/worker.log</string>
    <key>StandardErrorPath</key><string>/Users/marco/coding/kb/var/privat/worker.err</string>
</dict>
</plist>
```

`ops/de.michelyweb.kb.worker-business.plist`: identisch, überall `privat` → `business`.

- [ ] **Step 2: Install-Skript** — `ops/install.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
for name in privat business; do
  cp "ops/de.michelyweb.kb.worker-${name}.plist" ~/Library/LaunchAgents/
  launchctl unload ~/Library/LaunchAgents/de.michelyweb.kb.worker-${name}.plist 2>/dev/null || true
  launchctl load ~/Library/LaunchAgents/de.michelyweb.kb.worker-${name}.plist
done
echo "Beide Worker installiert. Logs: var/<instanz>/worker.log"
```

- [ ] **Step 3: Installieren und verifizieren**

```bash
chmod +x ops/install.sh && ./ops/install.sh
launchctl list | grep de.michelyweb.kb
```

Expected: beide Labels gelistet, Status 0 bzw. PID vorhanden.

- [ ] **Step 4: Commit**

```bash
git add ops/
git commit -m "Add launchd services for both instance workers"
```

---

## Self-Review (durchgeführt)

1. **Spec-Abdeckung:** F1 (Tasks 8–11: youtube/web/snippet/file), F2+F3 (Tasks 2–3: Registry, getrennte Pfade, ACL-Env, Prozess-Trennung), F4 (Tasks 5–6), F5 (Task 6), F6 (Task 3 Templates), F7 (Tasks 7+11: serielle Queue, ein Worker/Instanz), Phase-0-Gate (Task 4). **F8 (MCP) und F9 (iOS/Gateway) sind bewusst NICHT in diesem Plan** — Phase 2/3, eigene Pläne nach dem Gate.
2. **Platzhalter:** `eval/fragen.md` und `eval/quellen.txt` enthalten bewusst von Marco zu füllende Inhalte (echte Fragen/Quellen kann nur er liefern — vor Task-4-Step-7 ausfüllen). `LLM_API_KEY=CHANGE_ME` ist ein Secret, kein Plan-Platzhalter.
3. **Typ-Konsistenz:** `FetchedDoc` wird in Task 9 definiert, von Tasks 10–11 importiert. `write_raw` gibt `tuple[Path, SourceRecord]` zurück (finale Version in Task 6), Worker in Task 11 nutzt genau diese Signatur. `JobQueue.status()` aus Task 7 wird im Task-11-Test verwendet. ✓
4. **Bekannte Unschärfen (im Plan markiert):** Cognee-API-Parameternamen (Task 4, Kapselung in `cognee_io.py`) und youtube-transcript-api-Version (Task 9) — beide mit Prüfanweisung versehen.
