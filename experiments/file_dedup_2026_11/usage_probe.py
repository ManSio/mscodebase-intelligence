"""P3 of E72: file dedup must not break "where is X used".

Probes are built from the symbol index, not written by hand: a function with at
least two distinct call lines inside one file is a question where two rows of
one file are the correct answer. Frozen in `frozen/PLAN.md`.

Run:
    python experiments/file_dedup_2026_11/usage_probe.py \
        --corpus D:\\Project\\bench-ext\\sa-B --need 20
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "xerj_2026_11"))
sys.path.insert(0, str(ROOT / "experiments" / "xerj_2026_11" / "evidence_gate"))
sys.stdout.reconfigure(encoding="utf-8")

from run_gate import _files, _norm, _tools_for  # noqa: E402

DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)", re.M)


def _def_names(corpus: Path) -> list[str]:
    listing = subprocess.run(["git", "ls-files", "*.py"], cwd=corpus,
                             capture_output=True, text=True,
                             encoding="utf-8").stdout.splitlines()
    names = set()
    for rel in listing:
        try:
            text = (corpus / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        names.update(DEF_RE.findall(text))
    return sorted(names)


def _probes(tool, corpus: Path, need: int) -> list[dict]:
    index = tool.resolve_symbol_index(explicit_project_root=str(corpus))
    out = []
    for name in sorted(_def_names(corpus), key=lambda n: hashlib.sha1(n.encode()).hexdigest()):
        try:
            refs = index.get_callers(name) or []
        except Exception:  # noqa: BLE001 - a missing call graph is a skip, not a crash
            continue
        per_file: dict[str, set] = defaultdict(set)
        for ref in refs:
            if getattr(ref, "is_definition", False):
                continue
            file = str(getattr(ref, "file_path", "") or "").replace("\\", "/")
            if file:
                per_file[file].add(int(getattr(ref, "line", 0) or 0))
        file = next((f for f, lines in sorted(per_file.items()) if len(lines) >= 2), "")
        if not file:
            continue
        out.append({"name": name, "file": _norm([file], corpus)[0]})
        if len(out) >= need:
            break
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--need", type=int, default=20)
    parser.add_argument("--limit", type=int, default=8)
    args = parser.parse_args()

    corpus = Path(args.corpus)
    tool = _tools_for({corpus})[str(corpus)]
    probes = _probes(tool, corpus, args.need)
    print(f"corpus={corpus.name} probes={len(probes)}", flush=True)
    if not probes:
        print("no probes: the call graph returned nothing, so P3 is not measured", flush=True)
        return 2

    kept = 0
    for probe in probes:
        query = f"where is {probe['name']} used"
        os.environ.pop("MSCODEBASE_FILE_DEDUP", None)
        before = Counter(_norm(_files(asyncio.run(tool.execute(
            query=query, limit=args.limit, project_root=str(corpus)))), corpus))
        os.environ["MSCODEBASE_FILE_DEDUP"] = "file"
        after = Counter(_norm(_files(asyncio.run(tool.execute(
            query=query, limit=args.limit, project_root=str(corpus)))), corpus))
        os.environ.pop("MSCODEBASE_FILE_DEDUP", None)
        ok = before[probe["file"]] >= 2 and after[probe["file"]] >= 2
        kept += ok
        print(f"  {probe['name']:<34} {probe['file']:<44} "
              f"before={before[probe['file']]} after={after[probe['file']]} "
              f"{'kept' if ok else 'LOST'}", flush=True)

    print(f"\nP3 kept {kept}/{len(probes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
