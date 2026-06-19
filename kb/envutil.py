"""Geteilter Helfer für die Env-File-Parser (cognee_io + cli).

Eine eigene Stelle, damit `KEY="value"` in beiden Parsern gleich behandelt wird
(dotenv-Konvention) und sich die Logik nicht wieder dupliziert.
"""


def strip_quotes(value: str) -> str:
    """Entfernt EIN passendes umschließendes Anführungszeichen (" oder ').

    `KEY="v"` -> `v`, `KEY='v'` -> `v`; ungepaarte/fehlende Quotes bleiben
    unangetastet (`KEY=a"b` -> `a"b`).
    """
    v = value.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v
