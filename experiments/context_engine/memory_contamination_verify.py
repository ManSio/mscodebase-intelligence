#!/usr/bin/env python3
"""
Experiment 1-V: Memory Contamination VERIFY-ON-READ — аналог v3 (ADR-0003)

Гипотеза: Lazy Validation Layer (VerifyOnRead) доводит заражение до нуля на
SILENT-фактах: при извлечении ACTIVE-узлы с checkable-якорями проверяются по
кодовой базе; прямое отсутствие якоря -> REFUTED (SILENT_ABSENCE_ON_READ)
до формирования контекста. Ожидание (DoD ADR-0003): adoption честного агента
0.0; 0 ложных REFUTED среди TRUE-фактов с корректно типизированными якорями.

Дизайн (контрольная группа = v3/1-R: те же 50 фактов, тот же прокси, тот же
evidence-движок):
- Якоря: support_patterns факта -> по синтаксису: file: -> file; ALL-CAPS ->
  env; lowercase [a-z][a-z0-9_]+ -> import; остальное (модели/CamelCase/точки)
  -> якоря нет (INCONCLUSIVE-семантика).
- РЕАЛЬНЫЙ VerifyOnRead на РЕАЛЬНОЙ кодовой базе (отпечаток src + .env),
  изолированный store, бюджет по умолчанию 50ms.
- Агенты решают на ПОСТ-VERIFY памяти (отозванные невидимы).

Метрики: adoption honest/memory_first (vs v3 0.12/1.0, vs 1-R 0.12/0.12),
false_refuted_true (артефакты синтаксис-маппинга — честно), распределение
вердиктов, латентность (fingerprint + проход).

Запуск: venv/Scripts/python.exe experiments/context_engine/memory_contamination_verify.py
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.context_engine.memory_contamination import CodeEvidence, decide  # noqa: E402

_ANCHOR_ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")
_ANCHOR_IMPORT_RE = re.compile(r"^[a-z][a-z0-9_]+$")


def _read_env_keys(root: Path) -> set:
    """Ключи .env/.env.example — для нормализации env-паттернов (write-path)."""
    keys: set = set()
    for name in (".env", ".env.example"):
        p = root / name
        if p.is_file():
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    keys.add(line.split("=", 1)[0].strip())
    return keys


def _env_anchor(pattern: str, env_keys: set) -> List[Dict[str, str]]:
    """Паттерн -> точный env-ключ: прямое совпадение или уникальный префикс.

    Write-path хранит ТОЧНЫЕ ключи (env:LLAMA_CPP_ENABLED), а не сокращения;
    неоднозначный префикс якорем не становится (INCONCLUSIVE, без отзыва).
    """
    if pattern in env_keys:
        return [{"kind": "env", "value": pattern}]
    exact = sorted(k for k in env_keys if k.startswith(pattern))
    if len(exact) == 1:
        return [{"kind": "env", "value": exact[0]}]
    return []


def _pattern_anchors(pattern: str, env_keys: set) -> List[Dict[str, str]]:
    """Синтаксис-маппинг паттерна факта в checkable-якорь (как писал бы write-путь)."""
    if pattern.startswith("file:"):
        return [{"kind": "file", "value": pattern[len("file:"):]}]
    if _ANCHOR_ENV_RE.match(pattern):
        return _env_anchor(pattern, env_keys)
    if _ANCHOR_IMPORT_RE.match(pattern):
        return [{"kind": "import", "value": pattern}]
    return []


def main() -> int:
    try:
        facts_path = HERE / "memory_contamination_facts_v3_generated.json"
        facts: List[Dict] = json.loads(facts_path.read_text(encoding="utf-8"))["facts"]
        engine = CodeEvidence(ROOT)
        truth_map = {f["id"]: bool(f["truth"]) for f in facts}
        n_false = sum(1 for f in facts if not f["truth"])

        # ── Изолированный store + РЕАЛЬНЫЙ VerifyOnRead ──
        from src.core.artifact_paths import get_intelligence_dir
        from src.core.intelligence.store import IntelligenceStore
        from src.core.intelligence.verify_on_read import (
            STATUS_REFUTED,
            STATUS_VERIFIED,
            VerifyOnRead,
        )

        tmp = Path(tempfile.mkdtemp(prefix="mc_verify_exp_"))
        store = IntelligenceStore(tmp)
        real_store = get_intelligence_dir(ROOT)
        if str(store.store_dir) == str(real_store):
            raise RuntimeError("ISOLATION FAILED")

        env_keys = _read_env_keys(ROOT)
        nodes = []
        for f in facts:
            anchors = [a for p in f["support_patterns"] for a in _pattern_anchors(p, env_keys)]
            nodes.append(
                {
                    "node_id": f["id"],
                    "section": f["section"],
                    "timestamp": "2026-08-11 12:00:00",
                    # без status = легаси/ACTIVE (ADR-0002 backward-compat)
                    "data": {"claim": f["claim"], "anchors": anchors},
                }
            )
        store.save_memory(nodes)
        import threading

        # Изолированный кэш вердиктов (в tmp, не в реальный проект)
        verifier = VerifyOnRead(ROOT, store, threading.Lock(),
                                cache_file=tmp / "verify_cache.json")
        memory, stats = verifier.run(store.load_memory())

        # Steady-state: второй проход на том же HEAD — cache hit, бюджет ~0мс
        memory2, stats2 = verifier.run(memory)
        stats2.pop("head", None)

        # ── Пост-verify состояние ──
        raw = store._load_json("project_memory.json")
        status_by_id = {n["node_id"]: n.get("status", "ACTIVE") for n in raw}
        verified_ids = {i for i, s in status_by_id.items() if s == STATUS_VERIFIED}
        refuted_ids = {i for i, s in status_by_id.items() if s == STATUS_REFUTED}
        active_ids = set(truth_map) - verified_ids - refuted_ids

        false_refuted_true = [i for i in refuted_ids if truth_map.get(i)]
        true_refuted = [i for i in refuted_ids if not truth_map.get(i, True)]

        # ── Агенты на пост-verify памяти ──
        adopt = {"A_code_first": 0, "A_memory_first": 0}
        visible_false = 0
        per_fact: List[Dict[str, Any]] = []
        for f in facts:
            if f["id"] in refuted_ids:
                per_fact.append({"id": f["id"], "truth": bool(f["truth"]),
                                 "status_after_verify": "REFUTED"})
                continue  # отозван до формирования контекста — агент не видит
            if not f["truth"]:
                visible_false += 1
            ev = {p: engine.check_pattern(p) for p in f["support_patterns"] + f["contra_patterns"]}
            d_cf = decide(f, ev, has_memory=True, policy="code_first")
            d_mf = decide(f, ev, has_memory=True, policy="memory_first")
            per_fact.append({"id": f["id"], "truth": bool(f["truth"]),
                             "status_after_verify": status_by_id.get(f["id"], "ACTIVE"),
                             "code_says": d_cf["code_says"]})
            if not f["truth"]:
                if d_cf["verdict"] is True:
                    adopt["A_code_first"] += 1
                if d_mf["verdict"] is True:
                    adopt["A_memory_first"] += 1

        # Артефакты: какие паттерны привели к ложным REFUTED TRUE-фактов
        artifacts = []
        for f in facts:
            if f["id"] in false_refuted_true:
                artifacts.append({"id": f["id"], "claim": f["claim"],
                                  "support_patterns": f["support_patterns"],
                                  "anchors": [a for p in f["support_patterns"]
                                               for a in _pattern_anchors(p, env_keys)]})
        # Видимые ложные (memory_first adopters)
        visible_false_ids = []
        for f in facts:
            if not f["truth"] and f["id"] not in refuted_ids:
                visible_false_ids.append(f["id"])

        result = {
            "_meta": {
                "experiment": "Experiment 1-V: Memory Contamination VERIFY-ON-READ (ADR-0003)",
                "date": "2026-08-11",
                "control_group": "v3 (add-only) / 1-R (retraction)",
                "isolation": {"store_dir": str(store.store_dir), "real": str(real_store),
                              "isolated": str(store.store_dir) != str(real_store)},
                "verify_stats": stats,
                "steady_state_stats": stats2,
            },
            "verdicts": {
                "verified": len(verified_ids),
                "refuted": len(refuted_ids),
                "active_inconclusive": len(active_ids),
                "false_refuted_total": len(true_refuted),
                "false_refuted_true": false_refuted_true,
                "false_refuted_true_artifacts": artifacts,
                "visible_false_after_verify": visible_false_ids,
            },
            "per_fact": per_fact,
            "adoption": {
                "v3_baseline": {"A_code_first": 0.12, "A_memory_first": 1.0},
                "exp1r_post_retraction": {"A_code_first": 0.12, "A_memory_first": 0.12},
                "exp1v_verify_only": {
                    "A_code_first": round(adopt["A_code_first"] / n_false, 3),
                    "A_memory_first": round(adopt["A_memory_first"] / n_false, 3),
                },
                "visible_false_of_25": visible_false,
            },
        }

        out_path = HERE / "memory_contamination_results_v3_verify.json"
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

        print("=" * 78)
        print("Experiment 1-V: Memory Contamination VERIFY-ON-READ (ADR-0003)")
        print(f"facts: 50 (25T + 25F) | isolation: {result['_meta']['isolation']['isolated']}")
        print(f"verify: checked={stats['checked']} cache_hits={stats['cache_hits']} "
              f"inconclusive={stats['inconclusive']} budget_exceeded={stats['budget_exceeded']}")
        print(f"latency: fingerprint {stats['fingerprint_build_ms']}ms, first pass {stats['latency_ms']}ms, "
              f"steady-state {stats2['latency_ms']}ms (cache_hits={stats2['cache_hits']}, checked={stats2['checked']})")
        print("-" * 78)
        print(f"verdicts: VERIFIED={len(verified_ids)} REFUTED={len(refuted_ids)} "
              f"ACTIVE(INCONCLUSIVE)={len(active_ids)}")
        print(f"false REFUTED: total={len(true_refuted)} | среди TRUE (артефакт маппинга): "
              f"{len(false_refuted_true)} {false_refuted_true if false_refuted_true else ''}")
        if artifacts:
            print("  артефакты (ложные REFUTED TRUE):")
            for a in artifacts:
                print(f"    {a['id']} | {a['claim'][:55]} | patterns={a['support_patterns']} "
                      f"-> anchors={a['anchors']}")
        if visible_false_ids:
            print(f"  видимые ложные после verify (memory_first adopters): {visible_false_ids}")
        print("-" * 78)
        print(f"{'arm':<20}{'v3':>8}{'1-R':>8}{'1-V':>8}")
        print(f"{'adoption A_code_first':<20}{0.12:>8}{0.12:>8}"
              f"{result['adoption']['exp1v_verify_only']['A_code_first']:>8}")
        print(f"{'adoption A_memory_first':<20}{1.00:>8}{0.12:>8}"
              f"{result['adoption']['exp1v_verify_only']['A_memory_first']:>8}")
        print(f"visible false of 25 (после verify): {visible_false}")
        print(f"results: {out_path}")
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, json.JSONDecodeError) as e:
        import traceback

        traceback.print_exc()
        print(f"\nFAILED: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
