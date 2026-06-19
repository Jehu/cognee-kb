import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

GATEWAY_PORT = 8800
CONFIG_FILE = ROOT / "kb.toml"

# Hart erzwungen, nicht über kb.toml konfigurierbar:
EMBEDDING_PROVIDER = "fastembed"  # Wechsel würde alle bestehenden Vektoren invalidieren
MODE_PROVIDERS = {  # Wall-mode -> erlaubte LLM-Provider (Guard-Whitelist)
    "local": ("ollama",),  # zwingend lokal — kein Cloud-Call
    "cloud": ("custom",),  # Cloud-LLM via OpenAI-kompatiblem Endpoint
}


class UnknownVaultError(KeyError):
    pass


class ConfigError(RuntimeError):
    """kb.toml ist fehlerhaft oder inkonsistent."""


@dataclass(frozen=True)
class Instance:
    name: str
    env_file: Path
    allowed_llm_providers: tuple[str, ...]  # Guard-Whitelist (aus Wall-mode abgeleitet)
    expected_embedding_provider: str  # Guard hart: Wechsel invalidiert ALLE Vektoren
    var_dir: Path  # Queue-DB, Source-DB, Cognee-Roots
    port: int  # Instance Service (127.0.0.1)


@dataclass(frozen=True)
class Vault:
    name: str
    instance: str  # Name der Wall, zu der dieser Vault gehört
    dataset: str
    raw_dir: Path


def _load(path: Path = CONFIG_FILE) -> tuple[dict[str, Instance], dict[str, Vault]]:
    """Baut Instances + Vaults aus kb.toml. Pfade per Konvention aus den Namen."""
    try:
        data = tomllib.loads(path.read_text())
    except FileNotFoundError as e:
        raise ConfigError(f"Topologie-Datei fehlt: {path}") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"kb.toml ist kein gültiges TOML: {e}") from e

    instances: dict[str, Instance] = {}
    for name, w in data.get("walls", {}).items():
        mode = w.get("mode")
        if mode not in MODE_PROVIDERS:
            raise ConfigError(f"Wall '{name}': mode={mode!r}, erlaubt {sorted(MODE_PROVIDERS)}")
        if "port" not in w:
            raise ConfigError(f"Wall '{name}': 'port' fehlt")
        instances[name] = Instance(
            name=name,
            env_file=ROOT / f".env.{name}",
            allowed_llm_providers=MODE_PROVIDERS[mode],
            expected_embedding_provider=EMBEDDING_PROVIDER,
            var_dir=ROOT / "var" / name,
            port=w["port"],
        )
    if not instances:
        raise ConfigError("kb.toml definiert keine Walls ([walls.<name>])")

    vaults: dict[str, Vault] = {}
    for v in data.get("vaults", []):
        name, wall = v.get("name"), v.get("wall")
        if not name or not wall:
            raise ConfigError(f"Vault-Eintrag unvollständig: {v!r} (name+wall nötig)")
        if wall not in instances:
            raise ConfigError(f"Vault '{name}': unbekannte Wall '{wall}'")
        if name in vaults:
            raise ConfigError(f"Vault '{name}' doppelt definiert")
        vaults[name] = Vault(name=name, instance=wall, dataset=name, raw_dir=ROOT / "raw" / name)
    if not vaults:
        raise ConfigError("kb.toml definiert keine Vaults ([[vaults]])")

    # Ports müssen eindeutig sein (und dürfen nicht aufs Gateway fallen).
    ports = [i.port for i in instances.values()] + [GATEWAY_PORT]
    if len(ports) != len(set(ports)):
        raise ConfigError(f"Doppelte oder mit Gateway ({GATEWAY_PORT}) kollidierende Ports")

    return instances, vaults


INSTANCES, VAULTS = _load()


def get_vault(name: str) -> Vault:
    try:
        return VAULTS[name]
    except KeyError:
        raise UnknownVaultError(name) from None


def get_instance(name: str) -> Instance:
    return INSTANCES[name]


def queue_path(instance_name: str) -> Path:
    """Pfad zur Queue-DB einer Instanz (geteilt von Gateway/MCP/CLI)."""
    return get_instance(instance_name).var_dir / "queue.db"


def sources_path(instance_name: str) -> Path:
    """Pfad zur Source-DB einer Instanz (geteilt von Gateway/MCP/CLI)."""
    return get_instance(instance_name).var_dir / "sources.db"
