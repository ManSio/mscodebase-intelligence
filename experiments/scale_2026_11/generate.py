"""Generate the scale panel from the index, deterministically.

Frozen spec: `frozen/PLAN.md`. Same commit -> same panel; a different commit
gets a different sample. Gold is a file that must define the symbol exactly once:
a symbol with two definitions is an ambiguity task, and this generator does not
create those (XERJ A01-A04 already cover that class).

Run:
    python experiments/scale_2026_11/generate.py
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

OUT = HERE / "tasks.jsonl"
COUNTS = {"name": 160, "qualified": 40, "negative": 40}
SKIP_FILES = ("tests/", "docs/", "experiments/", "scripts/", ".venv/")
NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{4,40}$")
QUALIFIED_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.[a-z_][a-z0-9_]{3,40}$")


def _commit() -> str:
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                         capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        raise SystemExit("not a git repo: pin the panel to a commit")
    return out.stdout.strip()


def _definitions() -> dict[str, list[tuple[str, int]]]:
    """symbol -> [(relative file, line)] from the property graph.

    The symbol index is a view over the graph (`SymbolIndexAdapter`), so its
    in-memory dicts are empty until a query; the graph is the source of truth.

    Two filters keep the panel honest, both measured on 2026-11-10:
    - the graph can hold nodes whose file is not in this project
      (`src/sources/manifest/extract.py`), so the file must exist under ROOT;
    - the graph can hold phantom "functions" that are really calls
      (`callable` in `di_container.py`), so the source line must literally
      define the name.
    """
    from src.core.di_container import (
        IndexerFactoryKey,
        ProjectIndexerRegistry,
        create_service_collection,
    )

    services = create_service_collection(ROOT)
    indexer = services.resolve(ProjectIndexerRegistry).get_indexer(
        ROOT, factory=services.resolve(IndexerFactoryKey)
    )
    graph = indexer._symbol_index.graph
    base = str(ROOT).replace("\\", "/").rstrip("/")

    found: dict[str, list[tuple[str, int]]] = {}
    for node in graph.find_nodes(limit=50000):
        if node.label not in ("Function", "Class"):
            continue
        path = str(node.file_path or "").replace("\\", "/")
        if not path.startswith(base):
            continue
        path = path[len(base):].lstrip("/")
        source = ROOT / path
        if not source.is_file():
            continue
        if not _defines(source, node.name):
            continue
        line = int((node.properties or {}).get("line") or 0)
        found.setdefault(node.name, []).append((path, line))
    return found


def _defines(source: Path, name: str) -> bool:
    short = name.split(".")[-1]
    try:
        text = source.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return bool(re.search(rf"^\s*(async\s+def|def|class)\s+{re.escape(short)}\b",
                          text, re.M))


def main() -> int:
    commit = _commit()
    rng = random.Random(int(hashlib.sha256(commit.encode()).hexdigest(), 16))

    defs = _definitions()
    usable = {
        symbol: refs
        for symbol, refs in defs.items()
        if len(refs) == 1
        and not any(part in refs[0][0] for part in SKIP_FILES)
    }
    names = sorted(s for s in usable if NAME_RE.match(s))
    qualified = sorted(s for s in usable if QUALIFIED_RE.match(s))
    rng.shuffle(names)
    rng.shuffle(qualified)

    tasks: list[dict] = []
    for symbol in names[:COUNTS["name"]]:
        file, _line = usable[symbol][0]
        tasks.append({
            "id": f"G-N-{symbol}",
            "bucket": "name",
            "kind": "positive",
            "question": f"where is `{symbol}` defined",
            "gold": [file],
            "anchor": False,
        })
    for symbol in qualified[:COUNTS["qualified"]]:
        file, _line = usable[symbol][0]
        tasks.append({
            "id": f"G-Q-{symbol}",
            "bucket": "qualified",
            "kind": "positive",
            "question": f"where is `{symbol}` defined",
            "gold": [file],
            "anchor": False,
        })
    for index in range(COUNTS["negative"]):
        token = f"zz_{rng.getrandbits(32):08x}"
        tasks.append({
            "id": f"G-X-{index:03d}",
            "bucket": "negative",
            "kind": "negative",
            "question": f"where is `{token}` defined",
            "gold": [],
            "anchor": False,
        })

    # Anchors: the existing 41-task panel, unchanged, for calibration (S3).
    sys.path.insert(0, str(ROOT / "experiments" / "xerj_2026_11" / "evidence_gate"))
    from run_gate import _panel_tasks  # noqa: E402

    for task in _panel_tasks():
        tasks.append({
            "id": task["id"],
            "bucket": f"anchor:{task['panel']}/{task['kind']}",
            "kind": task["kind"],
            "question": task["question"],
            "gold": task["gold"],
            "anchor": True,
            "root": str(task["root"]),
        })

    if not (COUNTS["name"] == sum(t["bucket"] == "name" for t in tasks)):
        raise SystemExit("generator produced fewer name tasks than requested")

    OUT.write_text(
        "\n".join(json.dumps(t, ensure_ascii=False) for t in tasks) + "\n",
        encoding="utf-8", newline="",
    )
    print(f"commit={commit[:12]} tasks={len(tasks)} -> {OUT.name}")
    for bucket in sorted({t["bucket"] for t in tasks}):
        print(f"  {bucket:<22} {sum(t['bucket'] == bucket for t in tasks)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
