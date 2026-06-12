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
