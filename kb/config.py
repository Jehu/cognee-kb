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
        expected_embedding_provider="fastembed",
        var_dir=ROOT / "var" / "privat",
    ),
    "business": Instance(
        name="business",
        env_file=ROOT / ".env.business",
        expected_llm_provider="custom",     # OpenRouter/Infomaniak via OpenAI-kompatiblem Endpoint
        expected_embedding_provider="fastembed",
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
