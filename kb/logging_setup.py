"""Strukturiertes Logging für die kb-Services (stdlib, keine neue Dep).

Ausgabe auf stderr als `key=value`-Zeilen (menschenlesbar + grep-bar). Alle
kb-Logger laufen unter dem Namespace `kb.*` und propagieren an Root — so kann
pytest sie via ``caplog`` einfangen, ohne dass ein Handler konfiguriert sein
muss. ``setup_logging()`` installiert den stderr-Handler genau einmal.
"""

import logging
import sys

_FMT = "%(asctime)s %(levelname)s %(name)s — %(message)s"


def setup_logging() -> None:
    """Installiert den stderr-Handler am ``kb``-Logger (idempotent)."""
    root = logging.getLogger("kb")
    root.setLevel(logging.INFO)
    if not any(
        isinstance(h, logging.StreamHandler) and h.stream is sys.stderr for h in root.handlers
    ):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(_FMT))
        root.addHandler(handler)
