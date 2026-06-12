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
