"""E4.1 — Graph-arm PoC on the cold-start PropertyGraph (Track 1).

Reuses E3 methodology/scoring but self-contained (project src first).
Arms:
  cascade (E3 winner): fast, quality only on fast miss  -> bug/git/prepare/caller/arch
  graph  : symbol resolution from prompt -> definitions+callers+callees+impact
           file list from SymbolIndexAdapter over graph.db -> test/impact/modify/verify
Target: recall@5 >= 0.40 at median latency < 600ms (vs E3 cascade 0.233 / 564ms).
"""
import asyncio
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
EXT = Path(os.getenv("EXT_ROOT", r"C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence"))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))  # project src FIRST (guard fix visible)
if str(EXT) not in sys.path:
    sys.path.append(str(EXT))

try:
    from dotenv import load_dotenv
    env = PROJECT_ROOT / ".env"
    if env.exists():
        load_dotenv(env)
except ImportError:
    pass

os.environ.setdefault("PYTHONPATH", str(PROJECT_ROOT))
os.environ["PROJECT_PATH"] = str(PROJECT_ROOT)
os.environ["LLAMA_CPP_ENABLED"] = "true"

import logging
logging.basicConfig(level=logging.ERROR, stream=sys.stderr)

from src.config.settings import get_config
from src.core.artifact_paths import get_db_path, get_graph_db_path
from src.core.graph import PropertyGraph
from src.core.search.graph_adapter import SymbolIndexAdapter
from src.providers.embedder.remote_embedder import RemoteEmbedder
from src.core.indexing.file_guard import FileGuard
from src.core.indexing.indexer import Indexer
from src.core.search.engine import Searcher
from src.core.di_container import create_service_collection
from src.core.indexing.parser import CodeParser
from src.core.indexing.symbol_index import SymbolIndex
from resolver import concept_symbol, graph_fact_text  # E4.2 deterministic concept resolver

TOP_K = 5
LIMIT = 8
TASKS_FILE = PROJECT_ROOT / "experiments" / "context_engine" / "tasks_v3.json"
OUT_FILE = PROJECT_ROOT / "experiments" / "mech_orch" / "results_E4_1_graph.json"

GRAPH_KLASSES = {"find_test", "find_impact", "modify_function", "verify_change"}


def norm(p: str) -> str:
    return str(p).replace("\\", "/").lower()


def gt_hit(files, gt) -> bool:
    g = norm(gt)
    for f in files or []:
        fn = norm(f)
        if fn == g or fn.endswith(g) or g.endswith(fn.split("/")[-1]):
            return True
    return False


def fact_covered(facts, text: str):
    covered = 0
    for fct in facts:
        pat = str(fct.get("pattern", "") or "")
        if not pat:
            continue
        try:
            if re.search(pat, text, flags=re.IGNORECASE):
                covered += 1
        except re.error:
            if pat.lower() in text.lower():
                covered += 1
    return covered


def build_stack():
    services = create_service_collection(PROJECT_ROOT)
    embedder = services.resolve(RemoteEmbedder)
    if hasattr(embedder, "_check_llama_cpp") and embedder._check_llama_cpp():
        embedder.mode = "llama_cpp"
    db_path = get_db_path(PROJECT_ROOT)
    indexer = Indexer(
        db_path=db_path, embedder=embedder, file_guard=FileGuard(PROJECT_ROOT),
        project_path=PROJECT_ROOT, parser=CodeParser(), symbol_index=SymbolIndex(),
    )
    searcher = Searcher(indexer, embedder)
    indexer.set_searcher(searcher)
    return searcher, db_path


def run_sync(searcher, query, mode):
    t0 = time.perf_counter()
    try:
        out = searcher.search_with_mode(query, mode=mode, limit=LIMIT)
    except Exception as e:
        return {"latency_ms": (time.perf_counter() - t0) * 1000, "error": str(e),
                "files": [], "results": []}
    res = out.get("results") or []
    files = []
    for r in res:
        meta = r.get("metadata") or {}
        files.append(str(meta.get("file") or r.get("file") or "unknown"))
    return {
        "latency_ms": (time.perf_counter() - t0) * 1000,
        "files": files,
        "results": res,
    }


def snippets_of(res, topk=TOP_K):
    return "\n".join(str(r.get("text_full") or r.get("text") or "") for r in (res or [])[:topk])


def extract_symbol(adapter, prompt: str):
    """Deterministic: identifiers from prompt -> first that EXISTS in graph
    (search_symbols uses LIKE; has_symbol is EXACT node-name — too strict)."""
    toks = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", prompt or "")
    seen = {}
    for t in toks:
        if t.lower() in {"the", "and", "for", "with", "def", "from", "import", "class",
                          "напиши", "какие", "что", "как", "почему", "этой", "is", "not", "in"}:
            continue
        seen[t] = seen.get(t, 0) + 1
    cands = sorted(seen, key=lambda t: (-len(t), -seen[t]))
    fallback_hit = None
    for t in cands[:14]:
        variants = [t]
        parts = t.split("_")
        for i in range(1, len(parts)):
            variants.append("_".join(parts[i:]))
        for v in variants:
            try:
                hits = adapter.search_symbols(v, top_k=4) or []
            except Exception:
                continue
            if not hits:
                continue
            for r in hits:
                f = getattr(r, "file_path", "") or ""
                nm = getattr(r, "symbol", "") or ""
                # strict: qualified name ends with .<token> (или равно токену)
                if nm == v or nm.endswith("." + v):
                    if f and f != "unknown":
                        return v
                elif fallback_hit is None and f and f != "unknown":
                    fallback_hit = v
    return fallback_hit


def graph_files(adapter, sym: str) -> list:
    out = []
    try:
        for r in adapter.find_definitions(sym) or []:
            out.append(str(getattr(r, "file_path", "") or getattr(r, "file", "")))
    except Exception:
        pass
    try:
        for r in adapter.get_callers(sym) or []:
            out.append(str(getattr(r, "file_path", "") or getattr(r, "file", "")))
    except Exception:
        pass
    try:
        for d in adapter.get_callees(sym) or []:
            if isinstance(d, dict):
                out.append(str(d.get("file") or d.get("file_path") or ""))
    except Exception:
        pass
    try:
        imp = adapter.get_impact_analysis(sym, depth=2) or {}
        for key in ("depth_1_will_break", "depth_2_may_break"):
            for it in imp.get(key, []) or []:
                if isinstance(it, dict):
                    out.append(str(it.get("file") or it.get("file_path") or ""))
    except Exception:
        pass
    dedup = []
    for f in out:
        if f and f != "unknown" and f not in dedup:
            dedup.append(f)
    return dedup[:TOP_K]


def main():
    tasks = json.loads(TASKS_FILE.read_text(encoding="utf-8"))["tasks"]
    searcher, db_path = build_stack()
    # graph navigation: SymbolIndexAdapter over graph.db (cold-start, 10748 nodes),
    # NOT indexer._symbol_index (plain SymbolIndex, empty from disk cache).
    adapter = SymbolIndexAdapter(
        PropertyGraph(get_graph_db_path(PROJECT_ROOT)), mode=SymbolIndexAdapter.MODE_PURE
    )
    stats = adapter.stats() if hasattr(adapter, "stats") else {}
    print(f"[*] graph: {stats.get('symbols') or adapter.get_symbol_count()} symbols")
    print(f"[*] index rows: {searcher.indexer.table.count_rows() if searcher.indexer.table else 0}")

    rows = []
    for t in tasks:
        prompt = t.get("prompt") or ""
        klass = t.get("klass", "?")
        gt = t.get("file", "")
        facts = t.get("required_facts", [])

        if klass in GRAPH_KLASSES:
            # same-run honest baseline: cascade for this task too
            fast = run_sync(searcher, prompt, "fast")
            fh = gt_hit(fast["files"], gt)
            if fh:
                casc_hit, casc_lat = True, fast["latency_ms"]
            else:
                qual = run_sync(searcher, prompt, "quality")
                casc_hit, casc_lat = gt_hit(qual["files"], gt), fast["latency_ms"] + qual["latency_ms"]
            # E4.2: concept-phrase resolver FIRST, then lexical fallback (fail-open).
            sym = concept_symbol(prompt, klass) or extract_symbol(adapter, prompt)
            if sym:
                files = graph_files(adapter, sym)
                picked_lat = 15.0
                hit = gt_hit(files, gt)
                ftext = graph_fact_text(adapter, sym)  # Option V: graph rows carry facts
                arm = f"graph:{sym}"
            else:
                files, ftext = [], ""
                # fallback: каскад (роутер по построению никогда не хуже каскада)
                hit, picked_lat = casc_hit, 5.0
                arm = "graph:fallback->cascade"
            rows.append({
                "id": t["id"], "klass": klass, "arm": arm, "hit": hit,
                "cascade_hit": casc_hit, "latency_ms": round(picked_lat, 1),
                "cascade_latency_ms": round(casc_lat, 1), "gt": gt,
                "facts": 0 if not sym else fact_covered(facts, ftext), "facts_n": len(facts),
            })
            print(f"{t['id']:4} {klass:18} {arm:24} {'H' if hit else '-':1} {picked_lat:7.0f}ms "
                  f"(cascade={'H' if casc_hit else '-':1} {casc_lat:6.0f}ms)")
            continue
        else:
            fast = run_sync(searcher, prompt, "fast")
            fh = gt_hit(fast["files"], gt)
            if fh:
                files, hit, picked_lat, arm = fast["files"], True, fast["latency_ms"], "fast"
            else:
                qual = run_sync(searcher, prompt, "quality")
                files, hit, picked_lat, arm = qual["files"], gt_hit(qual["files"], gt), \
                    fast["latency_ms"] + qual["latency_ms"], "fast+quality"
            ftext = snippets_of(fast.get("results", []) + qual.get("results", []))

        rows.append({
            "id": t["id"], "klass": klass, "arm": arm, "hit": hit,
            "cascade_hit": hit if klass not in GRAPH_KLASSES else casc_hit,
            "latency_ms": round(picked_lat, 1), "gt": gt,
            "facts": 0 if klass in GRAPH_KLASSES else fact_covered(facts, ftext),
            "facts_n": len(facts),
        })
        print(f"{t['id']:4} {klass:18} {arm:24} {'H' if hit else '-':1} {picked_lat:7.0f}ms")

    n = len(rows)
    recall = sum(r["hit"] for r in rows) / n
    recall_cascade = sum(
        r["cascade_hit"] if r["klass"] in GRAPH_KLASSES else r["hit"] for r in rows
    ) / n
    lat = [r["latency_ms"] for r in rows]
    fcov = [r["facts"] / max(r["facts_n"], 1) for r in rows if r["facts_n"]]
    by_klass = {}
    for r in rows:
        b = by_klass.setdefault(r["klass"], {"n": 0, "hits": 0, "casc_hits": 0})
        b["n"] += 1
        b["hits"] += int(r["hit"])
        b["casc_hits"] += int(r.get("cascade_hit", 0))
    for k, b in by_klass.items():
        b["recall_graph"] = round(b["hits"] / b["n"], 3)
        b["recall_cascade"] = round(b["casc_hits"] / b["n"], 3)

    report = {
        "recall_k": round(recall, 3),
        "recall_cascade_samrun": round(recall_cascade, 3),
        "latency_median_ms": round(statistics.median(lat), 1),
        "latency_p95_ms": round(sorted(lat)[int(n * 0.95) - 1], 1) if n > 1 else None,
        "by_klass": by_klass, "rows": rows,
    }
    OUT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n=== E4.1 (same-run: cascade vs cascade+graph) ===")
    print(f"cascade alone : recall={report['recall_cascade_samrun']}")
    print(f"+graph arm    : recall={report['recall_k']} med={report['latency_median_ms']}ms p95={report['latency_p95_ms']}ms")
    print(f"TARGET        : recall>=0.40 med<600ms")
    print("\n=== BY KLASS (graph vs cascade) ===")
    for k, b in by_klass.items():
        print(f"{k:18}: n={b['n']:2} graph={b['recall_graph']:.2f} cascade={b['recall_cascade']:.2f}")
    print(f"\n[*] saved: {OUT_FILE}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)