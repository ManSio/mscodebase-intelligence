#!/usr/bin/env python3
"""
Experiment 1: Multi-RAG Component Ablation Study (v2 — REAL component isolation)

Tests each retrieval component in isolation and combinations:
- Vector-only (dense embeddings)
- BM25-only (sparse/keyword)
- FTS5-only (full-text SQLite)
- Graph-only (symbol graph via SymbolIndex)
- Hybrid combinations: Vector+BM25, Vector+BM25+FTS5, Vector+BM25+Graph, Full (all)
- quality = production path (search_with_mode)

Design: experiments/context_engine/multi_rag_design.md (2026-08-11)

v1-дефект (исправлен): все fast-руки вызывали search_with_mode("fast") и были
неразличимы. v2 изолирует компоненты monkey-patch'ем методов Searcher
(_bm25_search_async / _vector_search_async / _fts5_search_async /
_expand_graph_context / _apply_multi_reranker_async) на время вызова.

Metrics: recall, precision, wrong_rate, dup_rate, latency, tokens
Uses tasks_v3.json ground truth (30 tasks, 9 classes)
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, List

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── Snapshot артефакт-БД ──
from src.core import artifact_paths as _ap
import shutil
import tempfile

_SNAP = Path(tempfile.mkdtemp(prefix="cg_snapshot_")) / "artifacts"
_src_project_dir = _ap.get_project_dir(ROOT)
if _src_project_dir.exists():
    shutil.copytree(_src_project_dir, _SNAP, dirs_exist_ok=True)
    for _lock in _SNAP.rglob(".write_lock*"):
        _lock.unlink(missing_ok=True)

_orig_get_project_dir = _ap.get_project_dir
_ap.get_project_dir = lambda _p: _SNAP

import atexit


def _cleanup_snapshot() -> None:
    shutil.rmtree(_SNAP.parent, ignore_errors=True)


atexit.register(_cleanup_snapshot)

TOK_PER_CHAR = 4.0

# ── Experiment Arms (retrieval strategies) ──
# Каждая рука — булев набор компонентов; изоляция через _patch_components().
# quality = прод-путь целиком (search_with_mode); deep удалён — код-дубль quality
# (engine.py L948-972, см. multi_rag_design.md §1).
EXPERIMENT_ARMS = {
    "vector_only":       {"bm25": False, "vector": True,  "fts5": False, "graph": False, "rerank": False},
    "bm25_only":         {"bm25": True,  "vector": False, "fts5": False, "graph": False, "rerank": False},
    "fts5_only":         {"bm25": False, "vector": False, "fts5": True,  "graph": False, "rerank": False},
    "graph_only":        {"bm25": False, "vector": False, "fts5": False, "graph": True,  "rerank": False, "symbol_graph": True},
    "vector_bm25":       {"bm25": True,  "vector": True,  "fts5": False, "graph": False, "rerank": False},
    "vector_fts5":       {"bm25": False, "vector": True,  "fts5": True,  "graph": False, "rerank": False},
    "vector_graph":      {"bm25": False, "vector": True,  "fts5": False, "graph": True,  "rerank": False},
    "bm25_fts5":         {"bm25": True,  "vector": False, "fts5": True,  "graph": False, "rerank": False},
    "vector_bm25_fts5":  {"bm25": True,  "vector": True,  "fts5": True,  "graph": False, "rerank": False},
    "vector_bm25_graph": {"bm25": True,  "vector": True,  "fts5": False, "graph": True,  "rerank": False},
    "full_no_rerank":    {"bm25": True,  "vector": True,  "fts5": True,  "graph": True,  "rerank": False},
    "quality":           {"bm25": True,  "vector": True,  "fts5": True,  "graph": True,  "rerank": True, "prod_mode": True},
}


def tok(text: str) -> float:
    return len(text) / TOK_PER_CHAR


def _matches(text: str, pattern: str) -> bool:
    try:
        return re.search(pattern, text, re.IGNORECASE) is not None
    except re.error:
        return pattern.lower() in text.lower()


def _json_safe(obj: Any) -> Any:
    """Рекурсивно приводит numpy-типы (int32/float64) к Python для json.dumps."""
    import numpy as np

    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.ndarray,)):
        return [_json_safe(v) for v in obj.tolist()]
    return obj


def evidence_metrics(text: str, sections: list, required: list, wrong: list) -> dict:
    """Calculate evidence metrics for a result."""
    total = tok(text)
    retrieved = [f for f in required if _matches(text, f["pattern"])]
    recall = len(retrieved) / len(required) if required else 0.0

    relevant = wrong_t = irrelevant = dup = 0.0
    seen_facts = set()
    for _label, sec in sections:
        sec_t = tok(sec)
        if sec_t == 0:
            continue
        has_req = [f["id"] for f in required if _matches(sec, f["pattern"])]
        has_wrong = any(_matches(sec, w["pattern"]) for w in wrong)
        if has_wrong:
            wrong_t += sec_t
        if has_req:
            relevant += sec_t
            new = [fid for fid in has_req if fid not in seen_facts]
            if len(new) < len(has_req):
                dup += sec_t
            seen_facts.update(has_req)
        elif not has_wrong:
            irrelevant += sec_t

    denom = relevant + wrong_t + irrelevant
    return {
        "recall": round(recall, 3),
        "precision": round(relevant / denom, 3) if denom else 0.0,
        "wrong_rate": round(wrong_t / total, 3) if total else 0.0,
        "dup_rate": round(dup / total, 3) if total else 0.0,
        "retrieved_facts": [f["id"] for f in retrieved],
    }


# ── Component isolation (v2): monkey-patch на время вызова ──

async def _noop_results(*_args, **_kwargs) -> list:
    """Заглушка отключённого компонента ретривала: async → [] ."""
    return []


async def _passthrough_reranker(_query, results, _top_n):
    """Заглушка реранкера: вернуть вход без изменений."""
    return results


class _ComponentPatch:
    """Список (obj, attr, original) для restore после вызова руки."""

    def __init__(self) -> None:
        self._items: List[tuple] = []

    def add(self, obj: Any, attr: str, original: Any) -> None:
        self._items.append((obj, attr, original))

    def restore(self) -> None:
        for obj, attr, original in reversed(self._items):
            setattr(obj, attr, original)


def _patch_components(searcher: Any, cfg: dict) -> _ComponentPatch:
    """Отключает компоненты ретривала, помеченные False в конфиге руки."""
    patch = _ComponentPatch()
    if not cfg.get("bm25"):
        patch.add(searcher, "_bm25_search_async", searcher._bm25_search_async)
        searcher._bm25_search_async = _noop_results
    if not cfg.get("vector"):
        patch.add(searcher, "_vector_search_async", searcher._vector_search_async)
        searcher._vector_search_async = _noop_results
    if not cfg.get("fts5"):
        patch.add(searcher, "_fts5_search_async", searcher._fts5_search_async)
        searcher._fts5_search_async = _noop_results
    if not cfg.get("rerank"):
        patch.add(searcher, "_apply_multi_reranker_async", searcher._apply_multi_reranker_async)
        searcher._apply_multi_reranker_async = _passthrough_reranker
    return patch


def _ref_parts(item: Any) -> tuple:
    """Нормализует SymbolRef/dict в (file, line, symbol)."""
    if isinstance(item, dict):
        return (
            item.get("file_path") or item.get("file") or "?",
            item.get("line", 0),
            item.get("symbol") or item.get("name") or "?",
        )
    return (
        getattr(item, "file_path", "?") or "?",
        getattr(item, "line", 0),
        getattr(item, "symbol", "?") or "?",
    )


async def run_graph_only_arm(searcher: Any, task: dict, limit: int = 10) -> dict:
    """Graph-only: прямой запрос SymbolIndex по имени символа (без ретривала).

    Секции: definition + callers + callees, формат `{file}:{line} {symbol}`.
    Если SymbolIndex недоступен — пустой результат (замер покрытия графа).
    """
    t0 = time.perf_counter()
    sym = task["symbol"]
    si = None
    indexer = getattr(searcher, "indexer", None)
    if indexer is not None:
        si = getattr(indexer, "_symbol_index", None) or getattr(indexer, "symbol_index", None)

    sections: List[tuple] = []
    if si is not None:
        try:
            for d in (si.find_definitions(sym) or [])[:2]:
                f, ln, _s = _ref_parts(d)
                sections.append((f"{f}:{ln}", f"definition of {sym} at {f}:{ln}"))
        except Exception:
            pass
        for meth in ("get_callers", "get_callees"):
            try:
                for r in (getattr(si, meth)(sym) or [])[:limit]:
                    f, ln, s = _ref_parts(r)
                    label = "caller" if meth == "get_callers" else "callee"
                    sections.append((f"{f}:{ln}", f"{label} {s} at {f}:{ln}"))
            except Exception:
                pass

    exec_ms = (time.perf_counter() - t0) * 1000
    full = "\n".join(t for _l, t in sections)
    return {
        "results": [],
        "agent_latency_ms": round(exec_ms, 1),
        "server_latency_ms": round(exec_ms, 1),
        "tokens": round(tok(full)),
        "full": full,
        "sections": sections,
        "result_count": len(sections),
    }


async def run_search_arm(searcher: Any, query: str, arm_config: dict, limit: int = 10) -> dict:
    """Run search with a specific arm configuration (component-isolated).

    Все руки идут через hybrid_search_async(expand=False) — единый фьюжн RRF,
    без query expansion (замазал бы изоляцию) и без кэша search_with_mode.
    Пост-обработка (bucket/co-change/MMR/exact-boost/dedupe) — константа.
    """
    t0 = time.perf_counter()
    results: List[dict] = []
    server_ms = 0.0

    if arm_config.get("prod_mode"):
        # quality = прод-путь целиком (search_with_mode: hybrid + graph + rerank)
        result = searcher.search_with_mode(
            query=query, mode="quality", limit=limit,
            layer=None, intent_hint="auto", explain=False,
        )
        results = result.get("results", [])
        server_ms = result.get("timing_ms", {}).get("search_ms",
                      result.get("timing_ms", {}).get("total_ms", 0))
    else:
        patch = _patch_components(searcher, arm_config)
        try:
            # Изоляция кэша эмбеддингов per-arm: кэш-хит в hybrid_search_async
            # (engine.py L521-541) пропускает dense-поиск — без очистки vector-тир
            # молча пропадал бы во всех руках после первой (найдено 2026-08-11).
            try:
                with searcher._embedding_cache_lock:
                    searcher._embedding_cache.clear()
            except Exception:
                pass
            results = await searcher.hybrid_search_async(
                query, limit=limit, use_rrf=True, expand=False
            )
            if arm_config.get("graph") and not arm_config.get("symbol_graph"):
                results = searcher._expand_graph_context(results, query)
        finally:
            patch.restore()

    exec_ms = (time.perf_counter() - t0) * 1000

    # Format sections for evidence metrics
    sections = []
    for r in results:
        meta = r.get("metadata", {}) or {}
        file = meta.get("file", "?")
        chunk = meta.get("chunk_index", "?")
        text = r.get("text", "")[:2000]
        sections.append((f"{file}:{chunk}", text))

    full = "\n".join(t for _l, t in sections)

    return {
        "results": results,
        "server_latency_ms": round(server_ms, 1),
        "agent_latency_ms": round(exec_ms, 1),
        "tokens": round(tok(full)),
        "full": full,
        "sections": sections,
        "result_count": len(results),
    }


async def run_experiment_arm(searcher: Any, task: dict, arm_name: str, arm_config: dict) -> dict:
    """Run a single arm on a single task."""
    query = task["symbol"]
    required = task["required_facts"]
    wrong = task["wrong_patterns"]

    if arm_config.get("symbol_graph"):
        result = await run_graph_only_arm(searcher, task, limit=10)
    else:
        result = await run_search_arm(searcher, query, arm_config, limit=10)
    result.update(evidence_metrics(result["full"], result["sections"], required, wrong))
    return result


async def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Multi-RAG ablation (v2, real isolation)")
    ap.add_argument("tasks_file", nargs="?", default="tasks_v3.json")
    ap.add_argument("--arms", default="", help="подмножество рук через запятую (default: все)")
    ap.add_argument("--tasks", default="", help="подмножество задач через запятую, напр. T1,T2,T3 (default: все)")
    args = ap.parse_args()

    tasks_file = args.tasks_file
    out_name = f"multi_rag_ablation_{Path(tasks_file).stem}.json"

    tasks = json.loads((HERE / tasks_file).read_text(encoding="utf-8"))["tasks"]
    if args.tasks:
        wanted = {t.strip() for t in args.tasks.split(",") if t.strip()}
        tasks = [t for t in tasks if t["id"] in wanted]

    selected_arms = list(EXPERIMENT_ARMS.keys())
    if args.arms:
        selected_arms = [a.strip() for a in args.arms.split(",") if a.strip() in EXPERIMENT_ARMS]

    # Initialize searcher
    from src.core.di_container import create_service_collection
    from unittest.mock import AsyncMock
    from src.mcp.tools.search_tools import GetSymbolInfoTool, ImpactAnalysisTool
    from src.mcp.tools.git_tools import GetFileHistoryTool

    GetSymbolInfoTool.require_ready_project = AsyncMock()
    ImpactAnalysisTool.require_ready_project = AsyncMock()
    GetFileHistoryTool.require_ready_project = AsyncMock()

    services = create_service_collection(ROOT)

    # Searcher живёт на per-project Indexer (registry + factory из DI,
    # di_container.py _create_indexer_for_path → Indexer.set_searcher).
    from src.core.di_container import IndexerFactoryKey
    from src.core.indexing.project_indexer_registry import ProjectIndexerRegistry
    from typing import Callable, cast

    # resolve(IndexerFactoryKey) возвращает фабрику _create_indexer_for_path;
    # тайп-чекер видит sentinel-класс — кастуем к сигнатуре фабрики.
    factory = cast(Callable[[Path], Any], services.resolve(IndexerFactoryKey))
    registry = services.resolve(ProjectIndexerRegistry)
    indexer = registry.get_indexer(ROOT, factory=factory)
    searcher = indexer.searcher
    assert searcher is not None, "Indexer.searcher не установлен"

    print(f"Indexer: {len(registry.get_all_paths())} project(s), searcher={type(searcher).__name__}")

    print(f"Running Multi-RAG Ablation on {len(tasks)} tasks...")
    print(f"Arms: {selected_arms}")

    rows = []
    for i, task in enumerate(tasks):
        print(f"\nTask {i+1}/{len(tasks)}: {task['id']} ({task['klass']}) symbol={task['symbol']}")
        arm_results = {}

        for arm_name in selected_arms:
            arm_config = EXPERIMENT_ARMS[arm_name]
            try:
                r = await run_experiment_arm(searcher, task, arm_name, arm_config)
                arm_results[arm_name] = r
                print(f"  {arm_name:20s} recall={r['recall']:.3f} prec={r['precision']:.3f} "
                      f"wrong={r['wrong_rate']:.3f} tokens={r['tokens']} results={r['result_count']} "
                      f"lat={r['agent_latency_ms']:.0f}ms")
            except Exception as e:
                print(f"  {arm_name:20s} ERROR: {e}")
                arm_results[arm_name] = {
                    "recall": 0.0, "precision": 0.0, "wrong_rate": 1.0,
                    "dup_rate": 0.0, "tokens": 0, "server_latency_ms": 0,
                    "agent_latency_ms": 0, "result_count": 0, "error": str(e)
                }

        rows.append({
            "task": task["id"],
            "klass": task["klass"],
            "symbol": task["symbol"],
            "arms": arm_results
        })

    # Print summary table
    print("\n" + "=" * 120)
    header = f"{'task':<5}{'arm':<20}{'recall':<7}{'prec':<6}{'wrong':<7}{'dup':<6}{'tokens':<8}{'lat_ms':<8}{'results'}"
    print(header)
    print("-" * len(header))

    for row in rows:
        for arm_name in selected_arms:
            m = row["arms"].get(arm_name, {})
            print(
                f"{row['task']:<5}{arm_name:<20}"
                f"{m.get('recall', 0):<7.3f}{m.get('precision', 0):<6.3f}"
                f"{m.get('wrong_rate', 0):<7.3f}{m.get('dup_rate', 0):<6.3f}"
                f"{m.get('tokens', 0):<8}{m.get('agent_latency_ms', 0):<8.0f}{m.get('result_count', 0)}"
            )

    print("\n=== AVG ===")
    for metric in ("recall", "precision", "wrong_rate", "dup_rate", "tokens", "agent_latency_ms", "result_count"):
        line = f"{metric:<18}"
        for arm_name in selected_arms:
            vals = [r["arms"].get(arm_name, {}).get(metric, 0) for r in rows]
            avg = sum(vals) / len(vals) if vals else 0
            line += f" {arm_name}={avg:>8.3f}"
        print(line)

    # Paired analysis: each combination vs its components
    print("\n=== PAIRED ANALYSIS: Combinations vs Components ===")
    import statistics as _st

    n = len(rows)
    comparisons = [
        ("vector_bm25", "vector_only", "BM25 adds to Vector"),
        ("vector_bm25", "bm25_only", "Vector adds to BM25"),
        ("vector_bm25_fts5", "vector_bm25", "FTS5 adds to V+BM25"),
        ("vector_bm25_graph", "vector_bm25", "Graph adds to V+BM25"),
        ("full_no_rerank", "vector_bm25_fts5", "Graph adds to V+BM25+FTS5"),
        ("quality", "full_no_rerank", "Reranker adds to Full"),
        ("bm25_only", "fts5_only", "BM25 vs FTS5 (single, H5)"),
    ]
    # Smoke/подмножество рук: считаем только пары, где обе руки в прогоне
    comparisons = [c for c in comparisons if c[0] in selected_arms and c[1] in selected_arms]

    for arm_a, arm_b, label in comparisons:
        d_recall = [r["arms"].get(arm_a, {}).get("recall", 0) - r["arms"].get(arm_b, {}).get("recall", 0) for r in rows]
        d_prec = [r["arms"].get(arm_a, {}).get("precision", 0) - r["arms"].get(arm_b, {}).get("precision", 0) for r in rows]
        d_tokens = [r["arms"].get(arm_a, {}).get("tokens", 0) - r["arms"].get(arm_b, {}).get("tokens", 0) for r in rows]
        d_wrong = [r["arms"].get(arm_a, {}).get("wrong_rate", 0) - r["arms"].get(arm_b, {}).get("wrong_rate", 0) for r in rows]

        print(f"\n{label}: {arm_a} vs {arm_b}")
        for label_d, d in (("recall", d_recall), ("precision", d_prec), ("tokens", d_tokens), ("wrong_rate", d_wrong)):
            mu = sum(d) / n if n > 0 else 0
            sd = _st.stdev(d) if n > 1 else 0.0
            ci95 = 1.96 * sd / (n ** 0.5) if n > 1 else 0.0
            wins_a = sum(1 for x in d if x > 0)
            wins_b = sum(1 for x in d if x < 0)
            print(f"  {label_d:<10} Δ={mu:+.3f}  sd={sd:.3f}  CI95=±{ci95:.3f}  {arm_a}>{label_d}: {wins_a}/{n}  {arm_b}>{label_d}: {wins_b}/{n}")

    # Save results
    (HERE / out_name).write_text(
        json.dumps(_json_safe({
            "tasks_file": tasks_file,
            "n": n,
            "arms": selected_arms,
            "rows": rows,
            "timestamp": time.time(),
        }), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nSaved: experiments/context_engine/{out_name}")


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        asyncio.run(main())
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
