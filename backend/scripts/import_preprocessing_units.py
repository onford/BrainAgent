"""Offline importer for the reviewed Feishu snapshot; never invoked by a worker."""

import ast
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "docs/sources/preprocessing-units-feishu-2026-09-06.csv"
DEST = ROOT / "backend/app/preprocessing/units"


def main():
    rows = list(csv.DictReader(SOURCE.open(encoding="utf-8-sig", newline="")))
    assert len(rows) == len({r["id"] for r in rows}) == 50
    (DEST / "source").mkdir(parents=True, exist_ok=True)
    (DEST / "source/__init__.py").write_text("", encoding="utf-8")
    catalog = []
    for row in rows:
        code = row["代码"]
        tree = ast.parse(code)
        functions = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
        entry = next(n for n in reversed(functions) if n.startswith("eeg_"))
        module = row["id"].lower().replace("-", "_")
        raw = code.encode("utf-8")
        (DEST / f"source/{module}.py").write_bytes(raw)
        catalog.append(
            {
                "id": row["id"],
                "source": {
                    "version": "feishu-2026-09-06",
                    "snapshot_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                    "code_sha256": hashlib.sha256(raw).hexdigest(),
                    "fields": {k: v for k, v in row.items() if k not in ("id", "代码")},
                },
                "implementation": {"module": module, "entry": entry},
                "validation": {"source_syntax": "passed", "integration": "not_enabled"},
            }
        )
    (DEST / "catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
