#!/usr/bin/env python3
"""bench_v2.py — Эксперимент D: Context Composition vs Tool Composition.

Стратегии:
  A  — реальные последовательные MCP-вызовы (данные: strategy_a_data_v2.json,
       latency из intel_execution_timeline 2026-08-08)
  B  — compose-модель из данных A (intent-фильтр, dedup) — МОДЕЛЬ agent-facing latency
  C1 — РЕАЛЬНЫЙ существующий get_context (GetContextTool, in-process DI)
  C2 — РЕАЛЬНЫЙ расширенный get_edit_context (EditContextEngine, in-process DI)

Метрики (определения задокументированы):
  recall        = retrieved_required / total_required
  precision     = relevant_tokens / total_tokens (секция = ответ одного вызова / секция compose)
  wrong_rate    = tokens секций с wrong-паттерном (и без required) / total
  dup_rate      = tokens повторных вхождений факта (2-е+ секции) / total
  agent_latency = A: Σ реальных latency вызовов; B/C1/C2: 1×RT(400ms, реальный медианный) + exec
  server_latency= A: Σ реальных server latency; B: 0 (модель); C1/C2: реальный perf_counter
  tokens        = chars/4
  round_trips   = число вызовов (A: реальное; B/C1/C2: 1)
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── Snapshot артефакт-БД (та же реальная БД, temp-копия): ──
# PID-lock (.write_lock) живого MCP защищает оригинальную директорию БД.
# In-process C1/C2 работают на КОПИИ артефактов (read-only снэпшот): те же
# данные (graph.db, lancedb, intelligence), но без конфликта lock'ов.
from src.core import artifact_paths as _ap

_SNAP = Path(tempfile.mkdtemp(prefix="cg_snapshot_")) / "artifacts"
_src_project_dir = _ap.get_project_dir(ROOT)
if _src_project_dir.exists():
    shutil.copytree(_src_project_dir, _SNAP, dirs_exist_ok=True)
    for _lock in _SNAP.rglob(".write_lock*"):
        _lock.unlink(missing_ok=True)

_orig_get_project_dir = _ap.get_project_dir
_ap.get_project_dir = lambda _p: _SNAP  # все get_*_dir/path → на копию

# Snapshot-каталоги самоочищаются (иначе повторные прогоны заполняют диск —
# инцидент 2026-08-08: ~15 копий БД в %TEMP% на полном диске C:).
import atexit


def _cleanup_snapshot() -> None:
    shutil.rmtree(_SNAP.parent, ignore_errors=True)


atexit.register(_cleanup_snapshot)

TOK_PER_CHAR = 4.0
RT_MS = 400  # реальный медианный RT одиночного tool-вызова (timeline 2026-08-08: ~400-410ms)

A_TOOLS = {
    "find_bug_cause": ["get_symbol_info", "impact_analysis", "read_live_file", "git"],
    "modify_function": ["get_symbol_info", "impact_analysis", "read_live_file", "git", "memory"],
    "find_impact": ["impact_analysis", "get_symbol_info", "read_live_file"],
    "understand_architecture": ["get_symbol_info", "search_code", "read_live_file"],
    "find_test": ["get_symbol_info", "search_code", "memory", "git"],
    "git_history": ["git"],
    "find_caller_callee": ["get_symbol_info"],
    "prepare_change": ["get_symbol_info", "impact_analysis", "read_live_file", "git", "memory"],
    "verify_change": ["get_symbol_info", "read_live_file", "git"],
}


def tok(text: str) -> float:
    return len(text) / TOK_PER_CHAR


def _matches(text: str, pattern: str) -> bool:
    try:
        return re.search(pattern, text, re.IGNORECASE) is not None
    except re.error:
        return pattern.lower() in text.lower()


def evidence_metrics(text: str, sections: list, required: list, wrong: list) -> dict:
    """sections: список (label, text). Возвращает evidence-метрики."""
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
        # Wrong-evidence: секция с wrong-паттерном штрафуется ВСЕГДА (даже если
        # в ней есть корректные факты — опасный контекст = ложная уверенность).
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


def build_A(task: dict, data: dict) -> dict:
    sym = task["symbol"]
    rec = data["symbols"][sym]
    calls = A_TOOLS[task["klass"]]
    sections, texts, lat = [], [], 0.0
    for c in calls:
        if c == "memory":
            payload = data["memory"]["payload"]
            lat += data["memory"]["latency_ms"]
            sections.append(("memory", payload))
        else:
            cc = rec["calls"].get(c)
            if cc is None:
                continue
            payload = cc["payload"]
            lat += cc["latency_ms"]
            sections.append((c, payload))
        texts.append(sections[-1][1])
    full = "\n".join(texts)
    return {
        "round_trips": len(sections),
        "agent_latency_ms": round(lat, 1),
        "server_latency_ms": round(lat, 1),
        "tokens": round(tok(full)),
        "full": full,
        "sections": sections,
    }


def build_B(task: dict, data: dict) -> dict:
    """Compose-модель: те же данные, intent-фильтр + dedup (без повторных секций)."""
    from get_edit_context_v2 import INTENT_SECTIONS

    sym = task["symbol"]
    rec = data["symbols"][sym]
    keep = INTENT_SECTIONS[task["klass"]]
    parts = {}
    if "symbols" in keep:
        parts["symbols"] = rec["calls"]["get_symbol_info"]["payload"] + "\n" + (
            rec["calls"].get("search_code", {}).get("payload", "")
        )
    if "impact" in keep:
        parts["impact"] = rec["calls"]["impact_analysis"]["payload"]
    if "source" in keep:
        parts["source"] = rec["calls"]["read_live_file"]["payload"]
    if "git" in keep:
        parts["git"] = rec["calls"]["git"]["payload"]
    if "memory" in keep:
        parts["memory"] = data["memory"]["payload"]
    sections = list(parts.items())
    full = "\n".join(t for _l, t in sections)
    return {
        "round_trips": 1,
        "agent_latency_ms": round(RT_MS, 1),
        "server_latency_ms": 0.0,
        "tokens": round(tok(full)),
        "full": full,
        "sections": sections,
    }


async def run_C1(task: dict, services) -> dict:
    from src.mcp.tools.context_tool import GetContextTool

    tool = GetContextTool(services)
    import time

    t0 = time.perf_counter()
    out = await tool.execute(targets=[task["symbol"]])
    exec_ms = (time.perf_counter() - t0) * 1000
    sections = []
    if isinstance(out, str):
        sections.append(("error", out))
        full = out
    else:
        ctx = (out or {}).get("context", {})
        for target, item in ctx.items():
            for k, v in item.items():
                sections.append((f"{target}.{k}", str(v)))
        full = json.dumps(out, ensure_ascii=False)
    return {
        "round_trips": 1,
        "agent_latency_ms": round(RT_MS + exec_ms, 1),
        "server_latency_ms": round(exec_ms, 2),
        "tokens": round(tok(full)),
        "full": full,
        "sections": sections,
    }


async def run_C2(task: dict, services) -> dict:
    from get_edit_context_v2 import EditContextEngine

    engine = EditContextEngine(services, ROOT)
    out = await engine.compose(task["symbol"], task["file"], task["klass"])
    sections = [(sec, txt) for sec, txt in out["section_texts"].items()]
    return {
        "round_trips": 1,
        "agent_latency_ms": round(RT_MS + out["server_latency_ms"], 1),
        "server_latency_ms": out["server_latency_ms"],
        "tokens": out["tokens"],
        "full": out["payload"],
        "sections": sections,
    }


async def main() -> None:
    tasks_file = sys.argv[1] if len(sys.argv) > 1 else "tasks_v2.json"
    out_name = f"results_{Path(tasks_file).stem}.json"
    tasks = json.loads((HERE / tasks_file).read_text(encoding="utf-8"))["tasks"]
    data = json.loads((HERE / "strategy_a_data_v2.json").read_text(encoding="utf-8"))
    extra = HERE / "strategy_a_data_v3_extra.json"
    if extra.exists():
        data["symbols"].update(
            json.loads(extra.read_text(encoding="utf-8"))["symbols"]
        )

    from src.core.di_container import create_service_collection

    # Readiness-гейт обходится как в тестах проекта (test_next_step_hints.py:
    # tool.require_ready_project = AsyncMock()) — in-process харнесс без LSP-моста;
    # данные (SymbolIndex→LanceDB) — реальные, из живого READY-индекса.
    from unittest.mock import AsyncMock
    from src.mcp.tools.search_tools import GetSymbolInfoTool, ImpactAnalysisTool
    from src.mcp.tools.git_tools import GetFileHistoryTool

    GetSymbolInfoTool.require_ready_project = AsyncMock()
    ImpactAnalysisTool.require_ready_project = AsyncMock()
    GetFileHistoryTool.require_ready_project = AsyncMock()

    services = create_service_collection(ROOT)

    rows = []
    for task in tasks:
        required = task["required_facts"]
        wrong = task["wrong_patterns"]
        arm_results = {}
        for name, builder in (("A", build_A), ("B", build_B)):
            r = builder(task, data)
            r.update(evidence_metrics(r["full"], r["sections"], required, wrong))
            arm_results[name] = r
        arm_results["C1"] = await run_C1(task, services)
        arm_results["C1"].update(
            evidence_metrics(arm_results["C1"]["full"], arm_results["C1"]["sections"], required, wrong)
        )
        arm_results["C2"] = await run_C2(task, services)
        arm_results["C2"].update(
            evidence_metrics(arm_results["C2"]["full"], arm_results["C2"]["sections"], required, wrong)
        )
        rows.append({"task": task["id"], "klass": task["klass"], "symbol": task["symbol"], "arms": arm_results})

    header = f"{'task':<5}{'strat':<3}{'rt':<4}{'tokens':<8}{'agent_ms':<9}{'server_ms':<10}{'recall':<7}{'prec':<6}{'wrong':<7}{'dup':<6}"
    print(header)
    print("-" * len(header))
    for row in rows:
        for name in ("A", "B", "C1", "C2"):
            m = row["arms"][name]
            print(
                f"{row['task']:<5}{name:<3}{m['round_trips']:<4}{m['tokens']:<8}"
                f"{m['agent_latency_ms']:<9}{m['server_latency_ms']:<10}"
                f"{m['recall']:<7}{m['precision']:<6}{m['wrong_rate']:<7}{m['dup_rate']:<6}"
            )

    print("\n=== AVG ===")
    for metric in ("round_trips", "tokens", "agent_latency_ms", "server_latency_ms", "recall", "precision", "wrong_rate", "dup_rate"):
        line = f"{metric:<18}"
        for name in ("A", "B", "C1", "C2"):
            vals = [r["arms"][name][metric] for r in rows]
            line += f" {name}={sum(vals)/len(vals):>8.3f}"
        print(line)

    # Paired-анализ B vs C2 (устойчивость разницы, N=len(rows))
    import statistics as _st
    n = len(rows)
    d_recall = [r["arms"]["B"]["recall"] - r["arms"]["C2"]["recall"] for r in rows]
    d_tokens = [r["arms"]["B"]["tokens"] - r["arms"]["C2"]["tokens"] for r in rows]
    d_prec = [r["arms"]["B"]["precision"] - r["arms"]["C2"]["precision"] for r in rows]
    print("\n=== PAIRED B vs C2 (N=%d) ===" % n)
    for label, d in (("recall", d_recall), ("precision", d_prec), ("tokens", d_tokens)):
        mu = sum(d) / n
        sd = _st.stdev(d) if n > 1 else 0.0
        ci95 = 1.96 * sd / (n ** 0.5) if n > 1 else 0.0
        wins_b = sum(1 for x in d if x > 0)
        wins_c2 = sum(1 for x in d if x < 0)
        print(
            f"{label:<10} mean_delta(B-C2)={mu:+.3f}  sd={sd:.3f}  CI95=±{ci95:.3f}  "
            f"B>{label}: {wins_b}/{n}  C2>{label}: {wins_c2}/{n}"
        )

    (HERE / out_name).write_text(
        json.dumps({"tasks_file": tasks_file, "n": n, "rows": rows, "rt_ms": RT_MS,
                    "paired": {"recall": {"mean_delta": sum(d_recall)/n},
                               "tokens": {"mean_delta": sum(d_tokens)/n}}},
                   indent=2, ensure_ascii=False), encoding="utf-8"
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
