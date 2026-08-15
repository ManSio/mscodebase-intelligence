#!/usr/bin/env python3
"""
Experiment 1-R: Memory Contamination RETRACTION — аналог v3 (ADR-0002)

Гипотеза: системный отзыв (intel_retract_memory_node, ADR-0002) превращает
`would_refute` честного агента (correction_capability=1.0 в v1/v2/v3) в РЕАЛЬНОЕ
действие над хранилищем: отозванный факт исчезает из контекста СЛЕДУЮЩИХ сессий
(load_memory фильтрует REFUTED) → даже «ленивый» memory_first агент в сессии 2
не может принять уже отозванный факт.

Дизайн (контрольная группа = v3: те же 50 фактов, тот же детерминированный
прокси-агент, тот же evidence-движок — Правило контрольной группы §1):
- Сессия 1 (честный агент A_code_first): читает полную память, решает per-fact;
  would_refute=True → intel_retract_memory_node (реальный прод-путь layer,
  с валидацией причины и статуса).
- Сессия 2 (свежее чтение): ОБА агента (code_first и memory_first) решают на
  ПОСТ-РЕТРАКЦИОННОЙ памяти (store.load_memory фильтрует REFUTED — реальный путь).
- Метрики: adoption_rate S1 vs S2 (обе политики), persistent contamination
  (ложные факты, оставшиеся ACTIVE), tokens_memory до/после, системная
  реализуемость would_refute (refuted_via_tool / would_refute).
- Парити-чек: adoption S1 (A_code_first) обязан совпасть с v3 (0.12) — иначе
  аналог неверен. Уточнение ADR Temporal («adoption должен упасть с 0.12 к 0»):
  честный агент не может отозвать SILENT-факты (код молчит) — ожидается, что
  adoption честного останется 0.12, а упадут memory_first (1.0→0.12),
  persistent contamination (25→3, -88%) и токены контекста (~-44%).

Запуск: venv/Scripts/python.exe experiments/context_engine/memory_contamination_retraction.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TOK_PER_CHAR = 4.0

from experiments.context_engine.memory_contamination import CodeEvidence, decide, tok  # noqa: E402


class RetractionHarness:
    """Изолированный IntelligenceStore (tempdir) + РЕАЛЬНЫЙ layer для ретракции.

    seed() пишет узлы БЕЗ поля status — легаси-формат, который по ADR-0002
    интерпретируется как ACTIVE (backward-compat проверяется вживую).
    """

    def __init__(self, root: Path) -> None:
        from src.core.artifact_paths import get_intelligence_dir
        from src.core.intelligence.layer import ProjectIntelligenceLayer
        from src.core.intelligence.store import IntelligenceStore

        self._tmp = Path(tempfile.mkdtemp(prefix="mc_retr_exp_"))
        self.store = IntelligenceStore(self._tmp)
        self.real_store_dir = get_intelligence_dir(root)
        if str(self.store.store_dir) == str(self.real_store_dir):
            raise RuntimeError(
                f"ISOLATION FAILED: store_dir {self.store.store_dir} == real project store dir. ABORT."
            )
        # Прод-путь отзыва: layer со store, подменённым на изолированный
        # (indexer/searcher/symbol_index не используются memory-методами).
        self.layer = ProjectIntelligenceLayer(root, None, None, None)  # type: ignore[arg-type]
        self.layer.store = self.store

    def seed(self, facts: List[Dict]) -> None:
        nodes = [
            {
                "node_id": f["id"],
                "section": f["section"],
                "timestamp": "2026-08-11 12:00:00",
                # БЕЗ status — легаси: load_memory должен трактовать как ACTIVE
                "data": {"claim": f["claim"]},
            }
            for f in facts
        ]
        self.store.save_memory(nodes)

    def memory_context(self) -> str:
        memory = self.store.load_memory()  # реальный путь: REFUTED скрыты
        lines = []
        for section, nodes in memory.items():
            for n in nodes:
                claim = n.get("data", {}).get("claim", "")
                lines.append(f"[{section}] {n.get('node_id')}: {claim}")
        return "\n".join(lines)


def _evidence_for(engine: CodeEvidence, fact: Dict) -> Dict[str, Dict[str, Any]]:
    return {p: engine.check_pattern(p) for p in fact["support_patterns"] + fact["contra_patterns"]}


def _validate(facts: List[Dict], engine: CodeEvidence) -> Dict[str, Any]:
    """Та же валидация, что в v3 (контрольная группа обязана совпасть)."""
    validation: Dict[str, Any] = {"valid": [], "invalid": [], "ambiguous": []}
    for f in facts:
        ev = _evidence_for(engine, f)
        support = any(ev[p]["found"] for p in f["support_patterns"])
        contra = any(ev[p]["found"] for p in f["contra_patterns"])
        if f.get("silent"):
            if support:
                validation["invalid"].append({"id": f["id"], "reason": "SILENT fact: support pattern found (not silent)"})
            else:
                validation["valid"].append(f["id"])
            continue
        if f["truth"] and not support:
            validation["invalid"].append({"id": f["id"], "reason": "TRUE fact: no support pattern found"})
        elif not f["truth"] and not contra:
            validation["invalid"].append({"id": f["id"], "reason": "FALSE fact: no contra pattern found"})
        else:
            validation["valid"].append(f["id"])
            if f["truth"] and contra:
                validation["ambiguous"].append({"id": f["id"], "reason": "TRUE fact has contra found"})
            if not f["truth"] and support:
                validation["ambiguous"].append({"id": f["id"], "reason": "FALSE fact has support found"})
    return validation


def _retract(layer, node_id: str, reason: str) -> str:
    return asyncio.run(layer.intel_retract_memory_node(node_id, reason))


def main() -> int:
    try:
        facts_path = HERE / "memory_contamination_facts_v3_generated.json"
        facts: List[Dict] = json.loads(facts_path.read_text(encoding="utf-8"))["facts"]

        engine = CodeEvidence(ROOT)
        validation = _validate(facts, engine)
        valid_facts = [f for f in facts if f["id"] in validation["valid"]]

        harness = RetractionHarness(ROOT)
        harness.seed(valid_facts)
        n = len(valid_facts)
        n_false = sum(1 for f in valid_facts if not f["truth"])
        n_silent_false = sum(1 for f in valid_facts if f.get("silent"))

        ctx_s1 = harness.memory_context()
        tokens_s1 = tok(ctx_s1)

        # ── Сессия 1: честный агент (code_first) + РЕТРАКЦИЯ (прод-путь) ──
        s1_rows: List[Dict] = []
        refuted: List[Dict] = []
        t0 = time.perf_counter()
        for f in valid_facts:
            ev = _evidence_for(engine, f)
            d = decide(f, ev, has_memory=True, policy="code_first")
            row = {
                "id": f["id"],
                "truth": bool(f["truth"]),
                "silent": bool(f.get("silent")),
                "code_says": d["code_says"],
                "verdict": d["verdict"],
                "adopted": d["verdict"] is True,
                "would_refute": d["would_refute"],
            }
            if d["would_refute"]:
                pattern = d["contra_found"][0] if d["contra_found"] else "code-evidence"
                resp = _retract(harness.layer, f["id"], f"CONTRADICT: {pattern}")
                row["retract_ok"] = "REFUTED" in resp
                refuted.append({"id": f["id"], "pattern": pattern, "resp": resp})
            s1_rows.append(row)
        latency_s1_ms = round((time.perf_counter() - t0) * 1000.0, 1)

        # ── Сессия 2: свежее чтение ПОСТ-РЕТРАКЦИОННОЙ памяти (обе политики) ──
        ctx_s2 = harness.memory_context()
        tokens_s2 = tok(ctx_s2)
        mem_after = harness.store.load_memory()
        visible_ids = {node["node_id"] for sec in mem_after.values() for node in sec}

        s2_rows: List[Dict] = []
        for f in valid_facts:
            if f["id"] not in visible_ids:
                continue  # отозван — агент сессии 2 его не видит
            ev = _evidence_for(engine, f)
            d_cf = decide(f, ev, has_memory=True, policy="code_first")
            d_mf = decide(f, ev, has_memory=True, policy="memory_first")
            s2_rows.append(
                {
                    "id": f["id"],
                    "truth": bool(f["truth"]),
                    "silent": bool(f.get("silent")),
                    "code_says": d_cf["code_says"],
                    "arms": {
                        "A_code_first": d_cf["verdict"],
                        "A_memory_first": d_mf["verdict"],
                    },
                }
            )

        # ── Агрегация ──
        def _adoption(rows: List[Dict], arm: str) -> Optional[float]:
            """Доля ложных фактов, принятых агентом (verdict=True), от n_false."""
            false_rows = [r for r in rows if not r["truth"]]
            adopted = sum(
                1 for r in false_rows
                if (r[arm] if arm == "verdict" else r["arms"][arm]) is True
            )
            return round(adopted / n_false, 3) if n_false else None

        adopt_s1_cf = _adoption(s1_rows, "verdict")
        adopt_s2_cf = _adoption(s2_rows, "A_code_first")
        adopt_s2_mf = _adoption(s2_rows, "A_memory_first")

        # Persistent contamination: ложные факты, оставшиеся ACTIVE после сессии 1
        truth_map = {f["id"]: bool(f["truth"]) for f in valid_facts}
        all_raw = harness.store._load_json("project_memory.json")
        false_active = sum(
            1 for node in all_raw
            if not truth_map.get(node.get("node_id"), False)
            and node.get("status", "ACTIVE") != "REFUTED"
        )
        false_refuted = sum(
            1 for node in all_raw
            if not truth_map.get(node.get("node_id"), False)
            and node.get("status") == "REFUTED"
        )
        assert false_active + false_refuted == n_false, "счётчик ложных фактов не сходится"
        refuted_with_reason = all(
            node.get("retract_reason") for node in all_raw if node.get("status") == "REFUTED"
        )

        would_refute_n = sum(1 for r in s1_rows if r["would_refute"])
        systemic_capability = round(len(refuted) / would_refute_n, 3) if would_refute_n else None

        # Парити-чек с v3
        v3_parity = "OK" if adopt_s1_cf == 0.12 else f"MISMATCH (v3=0.12, got {adopt_s1_cf})"

        result = {
            "_meta": {
                "experiment": "Experiment 1-R: Memory Contamination RETRACTION (ADR-0002 analog of v3)",
                "date": "2026-08-11",
                "control_group": "v3 (memory_contamination_facts_v3_generated.json, same 50 facts)",
                "parity_with_v3_A_code_first_adoption": v3_parity,
                "isolation": {
                    "store_dir": str(harness.store.store_dir),
                    "real_project_store_dir": str(harness.real_store_dir),
                    "isolated": str(harness.store.store_dir) != str(harness.real_store_dir),
                },
                "validation": {k: len(v) for k, v in validation.items()},
            },
            "session1": {
                "agent": "A_code_first + retraction (real intel_retract_memory_node)",
                "rows": s1_rows,
                "refuted": refuted,
                "adoption_rate_false": adopt_s1_cf,
                "correction_capability_systemic": systemic_capability,
                "would_refute_attempted": would_refute_n,
                "refuted_via_tool": len(refuted),
                "latency_ms": latency_s1_ms,
            },
            "session2": {
                "agent": "fresh read of post-retraction memory, both policies",
                "visible_nodes": len(visible_ids),
                "visible_false": sum(1 for r in s2_rows if not r["truth"]),
                "rows": s2_rows,
                "adoption_rate_false_A_code_first": adopt_s2_cf,
                "adoption_rate_false_A_memory_first": adopt_s2_mf,
            },
            "memory_after": {
                "total_raw_nodes": len(all_raw),
                "refuted_nodes": sum(1 for node in all_raw if node.get("status") == "REFUTED"),
                "false_active_remaining": false_active,
                "false_refuted": false_refuted,
                "persistent_false_reduction": round((n_false - false_active) / n_false, 3) if n_false else None,
                "refuted_all_have_reason": refuted_with_reason,
                "tokens_memory_session1": round(tokens_s1, 1),
                "tokens_memory_session2": round(tokens_s2, 1),
                "tokens_memory_reduction": round((tokens_s1 - tokens_s2) / tokens_s1, 3) if tokens_s1 else None,
            },
            "references": {
                "v3_adoption_A_code_first": 0.12,
                "v3_adoption_A_memory_first": 1.0,
                "v3_persistent_false_in_memory": n_false,
                "v3_tokens_memory_total_50_facts": 66500.0,
            },
        }

        out_path = HERE / "memory_contamination_results_v3_retraction.json"
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

        # ── Консольный свод ──
        print("=" * 78)
        print("Experiment 1-R: Memory Contamination RETRACTION (ADR-0002, analog of v3)")
        print(f"valid facts: {n} ({n - n_false}T + {n_false}F, silent-false {n_silent_false})  |  "
              f"invalid: {len(validation['invalid'])}  |  parity: {v3_parity}")
        print(f"isolation: {result['_meta']['isolation']}")
        print("-" * 78)
        print(f"{'':<18}{'adopt(F)':>10}{'corr_cap':>10}{'persist.F':>10}{'tokens':>10}")
        print(f"{'v3 (control, add-only)':<18}{'0.12 / 1.0':>10}{'1.0(would)':>10}{str(n_false):>10}{'66500.0':>10}")
        print(f"{'S1 honest+retract':<18}{str(adopt_s1_cf):>10}{str(systemic_capability):>10}{str(false_active):>10}{str(round(tokens_s1,1)):>10}")
        print(f"{'S2 code_first':<18}{str(adopt_s2_cf):>10}{'-':>10}{'':>10}{str(round(tokens_s2,1)):>10}")
        print(f"{'S2 memory_first':<18}{str(adopt_s2_mf):>10}{'-':>10}{'':>10}{'':>10}")
        print("-" * 78)
        print(f"retraction: {len(refuted)}/{would_refute_n} would_refute реализовано системно "
              f"(correction_capability_systemic={systemic_capability})")
        print(f"persistent false in memory: {n_false} -> {false_active} "
              f"(-{round((n_false - false_active) / n_false * 100)}%)")
        print(f"tokens_memory: {round(tokens_s1,1)} -> {round(tokens_s2,1)} "
              f"(-{round((tokens_s1 - tokens_s2) / tokens_s1 * 100)}%)")
        print(f"all refuted have reason: {refuted_with_reason}")
        print(f"results: {out_path}")
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, json.JSONDecodeError) as e:
        import traceback

        traceback.print_exc()
        print(f"\nFAILED: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
