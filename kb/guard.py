import os

from kb.config import Instance


class EnvGuardError(RuntimeError):
    """Die geladene Env passt nicht zur Instanz — Abbruch vor jedem Cognee-Call."""


def assert_instance_env(instance: Instance) -> None:
    # LLM-Provider ist umschaltbar (lokal/Cloud) — nur gegen Whitelist prüfen.
    llm = os.environ.get("LLM_PROVIDER")
    if llm not in instance.allowed_llm_providers:
        raise EnvGuardError(
            f"LLM_PROVIDER={llm!r}, erlaubt {instance.allowed_llm_providers!r} "
            f"für Instanz '{instance.name}'. Falsches Env-File geladen?"
        )
    # Embedding-Provider hart erzwingen: ein Wechsel invalidiert still alle
    # bestehenden Vektoren und erzwingt einen kompletten Re-Ingest.
    emb = os.environ.get("EMBEDDING_PROVIDER")
    if emb != instance.expected_embedding_provider:
        raise EnvGuardError(
            f"EMBEDDING_PROVIDER={emb!r}, erwartet "
            f"{instance.expected_embedding_provider!r} für Instanz "
            f"'{instance.name}'. Wechsel würde alle Vektoren invalidieren!"
        )
