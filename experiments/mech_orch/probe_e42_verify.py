"""E4.2 probe — verify_change resolution fix against the REAL graph.db (no embedder).

Avoids the heavy E4.1 live run (llama.cpp 8080 held by the live MCP): graph
navigation needs only the cold-start PropertyGraph (read-only), not the
embedder. Proves the two verify_change misses (T9/T29) now resolve to the
correct GT file via the concept resolver + graph definition lookup.

Usage: python experiments/mech_orch/probe_e42_verify.py
"""
import json
import re
import sys
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from resolver import concept_symbol, graph_fact_text  # noqa: E402
from src.core.artifact_paths import get_graph_db_path  # noqa: E402
from src.core.graph import PropertyGraph  # noqa: E402
from src.core.search.graph_adapter import SymbolIndexAdapter  # noqa: E402

TASKS = PROJECT_ROOT / "experiments" / "context_engine" / "tasks_v3.json"
WAIT_KLASS = {"verify_change"}


def norm(p: str) -> str:
    return str(p).replace("\\", "/").lower()


def gt_hit(files, gt) -> bool:
    g = norm(gt)
    return any(
        norm(f) == g or norm(f).endswith(g) or g.endswith(norm(f).split("/")[-1])
        for f in files or []
    )


def main():
    tasks = json.loads(TASKS.read_text(encoding="utf-8"))["tasks"]
    adapter = SymbolIndexAdapter(
        PropertyGraph(get_graph_db_path(PROJECT_ROOT)), mode=SymbolIndexAdapter.MODE_PURE
    )
    print(f"[*] graph symbols: {adapter.get_symbol_count() if hasattr(adapter, 'get_symbol_count') else 'n/a'}")
    fail = 0
    for t in tasks:
        if t.get("klass") not in WAIT_KLASS:
            continue
        prompt = t.get("prompt", "")
        gt = t.get("file", "")
        facts = t.get("required_facts", [])
        sym = concept_symbol(prompt, t["klass"])  # deterministic, no embedder
        if not sym:
            print(f"{t['id']:4} verify_change NO-CONCEPT (still lexical case) -> {t['id']}")
            fail += 1
            continue
        try:
            defs = adapter.find_definitions(sym) or []
        except Exception as e:
            print(f"{t['id']:4} find_definitions err: {e}")
            fail += 1
            continue
        files = [getattr(r, "file_path", "") or "" for r in defs]
        hit = gt_hit(files, gt)
        blob = graph_fact_text(adapter, sym)
        fc = sum(1 for f in facts if re.search(str(f.get("pattern", "") or ""), blob, re.IGNORECASE)
                 if str(f.get("pattern", "") or ""))
        fc_n = len([f for f in facts if str(f.get("pattern", "") or "")])
        status = "HIT" if hit else "MISS"
        if not hit:
            fail += 1
        print(f"{t['id']:4} verify_change sym={sym:22} files={files} -> {status} gt={gt} facts={fc}/{fc_n}")
    print(f"\n=== E4.2 graph-layer probe: verify_change {'ALL HIT' if fail == 0 else f'{fail} FAIL'} ===")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
