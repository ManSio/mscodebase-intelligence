#!/usr/bin/env python3
"""
Experiment 1: Memory Contamination (IntelligenceStore) — v1

Проверка гипотезы (experiments/second_brain_research.md §4 Experiment 1):
персистентная память (project_memory.json + incidents.json) вносит stale/false
контекст. Ключевой вопрос владельца (2026-08-11): когда агент натыкается на
противоречие Memory vs Code — какой источник становится ground truth, и может
ли агент ОТОЗВАТЬ ложный факт из памяти (correction_capability)?

Дизайн:
- 20 фактов (10 TRUE + 10 FALSE) с известной истинностью по реальному коду;
  FALSE-факты сконструированы так, что контраргумент реально существует в src/
  (паттерны валидированы grep-ом 2026-08-11; слова-ловушки исключены).
- Руки: A (с памятью) / B (без памяти). Память руки A — ИЗОЛИРОВАННЫЙ
  IntelligenceStore(tempdir): store_dir = hash(tempdir) != hash(проекта);
  assert на различие ДО записи. Те же API, что в проде (save_memory/save_incidents
  → load_memory/load_incidents = intel_get_project_memory).
- Агент = детерминированный прокси (живого LLM в проекте нет). Идёт в код:
  точный evidence-поиск паттернов по src/**/*.py + .env. Решение по политике:
  - B (no-memory):        CONTRADICT → не(claim); SUPPORT → claim; SILENT → UNKNOWN
  - A code_first:         CONTRADICT → не(claim) + would_refute (коррекция);
                          SUPPORT → claim; SILENT → claim (память выиграла)
  - A memory_first:       всегда claim (worst case: агент игнорирует код)
  Выбор ground truth фиксируется per-fact (choice: MEMORY|CODE|NONE).
- Ограничение (честная калибровка): без живого LLM измеряем «защитную
  способность системы» (может ли код опровергнуть память), не психологию LLM.

Метрики: correct_rate, adoption_rate, correction_capability, code_contradictability,
memory_confidence_effect, false_confirmation_rate, unknown_rate, tokens, latency.

Запуск: venv/Scripts/python.exe experiments/context_engine/memory_contamination.py
"""
from __future__ import annotations

import atexit
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TOK_PER_CHAR = 4.0
SNIPPET_CHARS = 90  # контекст найденного паттерна (как «прочитанный код»)

# ── Изолированный store (tempdir, НЕ трогает реальный проект) ──
_TMP = Path(tempfile.mkdtemp(prefix="mc_exp_"))


def _cleanup_tmp() -> None:
    shutil.rmtree(_TMP, ignore_errors=True)


atexit.register(_cleanup_tmp)


def tok(text: str) -> float:
    return len(text) / TOK_PER_CHAR


def _snippet_around(text: str, idx: int) -> str:
    start = max(0, idx - SNIPPET_CHARS // 2)
    end = min(len(text), idx + SNIPPET_CHARS // 2)
    return text[start:end].replace("\n", " ").strip()


class CodeEvidence:
    """Детерминированный «агент идёт в код»: точный evidence-поиск паттернов.

    Паттерны: plain substring (case-insensitive) по содержимому файлов корпуса;
    префиксы "file:"/"dir:" — существование пути от корня проекта.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self._corpus: List[Dict[str, Any]] = []
        self._scan_ms = 0.0
        self._build_corpus()

    def _build_corpus(self) -> None:
        t0 = time.perf_counter()
        src_dir = self.root / "src"
        for p in sorted(src_dir.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            try:
                self._corpus.append({"path": p, "text": p.read_text(encoding="utf-8", errors="replace")})
            except OSError:
                continue
        env = self.root / ".env"
        if env.exists():
            self._corpus.append({"path": env, "text": env.read_text(encoding="utf-8", errors="replace")})
        self._scan_ms = (time.perf_counter() - t0) * 1000.0

    def check_pattern(self, pattern: str) -> Dict[str, Any]:
        """Возвращает {"found": bool, "snippet": str|None}."""
        if pattern.startswith("file:"):
            target = self.root / pattern[len("file:"):]
            return {"found": target.is_file(), "snippet": f"[file] {target}" if target.is_file() else None}
        if pattern.startswith("dir:"):
            target = self.root / pattern[len("dir:"):]
            return {"found": target.is_dir(), "snippet": f"[dir] {target}" if target.is_dir() else None}
        needle = pattern.lower()
        for doc in self._corpus:
            idx = doc["text"].lower().find(needle)
            if idx >= 0:
                return {"found": True, "snippet": f"{doc['path'].relative_to(self.root)}: {_snippet_around(doc['text'], idx)}"}
        return {"found": False, "snippet": None}


class MemoryHarness:
    """Заполняет изолированный IntelligenceStore фактами (те же API, что прод)."""

    def __init__(self, root: Path) -> None:
        from src.core.artifact_paths import get_intelligence_dir
        from src.core.intelligence.store import IntelligenceStore

        self.store = IntelligenceStore(Path(_TMP))
        self.real_store_dir = get_intelligence_dir(root)
        if str(self.store.store_dir) == str(self.real_store_dir):
            raise RuntimeError(
                f"ISOLATION FAILED: store_dir {self.store.store_dir} == real project store dir. ABORT."
            )

    def seed(self, facts: List[Dict]) -> None:
        nodes = []
        for f in facts:
            nodes.append(
                {
                    "node_id": f["id"],
                    "section": f["section"],
                    "timestamp": "2026-08-11 12:00:00",
                    "data": {"claim": f["claim"]},
                }
            )
        incidents = [
            {
                "incident_id": f["id"],
                "timestamp": "2026-08-11 12:00:00",
                "component": "memory_contamination_exp",
                "symptom": f["claim"],
                "root_cause": "seed",
                "fix": "n/a",
                "success": True,
            }
            for f in facts
        ]
        self.store.save_memory(nodes)
        self.store.save_incidents(incidents)

    def memory_context(self) -> str:
        """Формат, аналогичный intel_get_project_memory (секции + узлы)."""
        memory = self.store.load_memory()
        lines = []
        for section, nodes in memory.items():
            for n in nodes:
                claim = n.get("data", {}).get("claim", "")
                lines.append(f"[{section}] {n.get('node_id')}: {claim}")
        incidents = self.store.load_incidents()
        for inc in incidents:
            lines.append(f"[incident {inc.get('incident_id')}] {inc.get('symptom', '')}")
        return "\n".join(lines)


def decide(fact: Dict, evidence: Dict[str, Dict[str, Any]], has_memory: bool, policy: str) -> Dict[str, Any]:
    """Детерминированное решение агента. Вердикт — ответ на claim: «истинно ли утверждение?».

    CONTRADICT → код опровергает claim → вердикт False;
    SUPPORT    → код подтверждает claim → вердикт True;
    SILENT     → код молчит: B → UNKNOWN (None); A → вердикт как память (True).
    """
    contra_found = [p for p in fact["contra_patterns"] if evidence[p]["found"]]
    support_found = [p for p in fact["support_patterns"] if evidence[p]["found"]]

    if contra_found:
        code_says = "CONTRADICT"
    elif support_found:
        code_says = "SUPPORT"
    else:
        code_says = "SILENT"

    if not has_memory:  # Рука B: только код
        if code_says == "CONTRADICT":
            verdict, choice, refute = False, "CODE", False
        elif code_says == "SUPPORT":
            verdict, choice, refute = True, "CODE", False
        else:
            verdict, choice, refute = None, "NONE", False  # UNKNOWN
        return {"code_says": code_says, "verdict": verdict, "choice": choice,
                "would_refute": refute, "contra_found": contra_found, "support_found": support_found}

    # Рука A: память есть. Политика решения при противоречии.
    if code_says == "CONTRADICT":
        if policy == "code_first":
            verdict, choice, refute = False, "CODE", True  # отозвал факт
        else:  # memory_first — агент игнорирует код
            verdict, choice, refute = True, "MEMORY", False
    elif code_says == "SUPPORT":
        # Оба источника согласны; choice отражает источник ground truth политики.
        verdict = True
        choice = "CODE" if policy == "code_first" else "MEMORY"
        refute = False
    else:  # SILENT — память единственный источник
        verdict, choice, refute = True, "MEMORY", False
    return {"code_says": code_says, "verdict": verdict, "choice": choice,
            "would_refute": refute, "contra_found": contra_found, "support_found": support_found}


def main() -> int:
    try:
        # Факты — из argv (репликация: другой набор данных, та же логика)
        facts_arg = sys.argv[1] if len(sys.argv) > 1 else "memory_contamination_facts.json"
        facts_path = Path(facts_arg) if Path(facts_arg).is_absolute() else HERE / facts_arg
        facts: List[Dict] = json.loads(facts_path.read_text(encoding="utf-8"))["facts"]
        out_path = HERE / (facts_path.stem.replace("facts", "results") + ".json")

        evidence_engine = CodeEvidence(ROOT)
        harness = MemoryHarness(ROOT)
        harness.seed(facts)
        memory_ctx = harness.memory_context()

        # Валидация паттернов фактов: TRUE обязан иметь support, FALSE — contra;
        # SILENT-факты валидны если support НЕ найден (иначе они не silent).
        validation: Dict[str, Any] = {"valid": [], "invalid": [], "ambiguous": []}
        for f in facts:
            ev = {p: evidence_engine.check_pattern(p) for p in f["support_patterns"] + f["contra_patterns"]}
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

        valid_facts = [f for f in facts if f["id"] in validation["valid"]]

        # ── Прогон агента ──
        policies = ["B", "A_code_first", "A_memory_first"]
        per_fact = []
        for f in valid_facts:
            t0 = time.perf_counter()
            ev = {p: evidence_engine.check_pattern(p) for p in f["support_patterns"] + f["contra_patterns"]}
            arms = {}
            for pol in policies:
                has_mem = pol != "B"
                policy = "code_first" if pol == "A_code_first" else "memory_first"
                arms[pol] = decide(f, ev, has_mem, policy)
            latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
            # Токены: A — память-контекст + сниппеты evidence; B — только сниппеты.
            snippets = " ".join(
                r["snippet"] for r in ev.values() if r.get("snippet") and r["found"]
            )
            per_fact.append(
                {
                    "id": f["id"], "truth": bool(f["truth"]), "section": f["section"],
                    "claim": f["claim"], "arms": arms,
                    "tokens_memory": tok(memory_ctx), "tokens_evidence": tok(snippets),
                    "latency_ms": latency_ms,
                }
            )

        # ── Агрегация ──
        n = len(valid_facts)
        n_true = sum(1 for f in valid_facts if f["truth"])
        n_false = n - n_true
        n_silent = sum(1 for f in valid_facts if f.get("silent"))
        agg: Dict[str, Any] = {"n_valid": n, "n_true": n_true, "n_false": n_false,
                               "n_silent_false": n_silent, "arms": {}}

        for pol in policies:
            rows = [pf for pf in per_fact]
            correct = sum(1 for pf in rows if pf["arms"][pol]["verdict"] == pf["truth"])
            unk = sum(1 for pf in rows if pf["arms"][pol]["verdict"] is None)
            false_rows = [pf for pf in rows if not pf["truth"]]
            true_rows = [pf for pf in rows if pf["truth"]]
            adoption = sum(1 for pf in false_rows if pf["arms"][pol]["verdict"] is True)
            contradict = sum(1 for pf in false_rows if pf["arms"][pol]["code_says"] == "CONTRADICT")
            refuted = sum(
                1 for pf in false_rows
                if pf["arms"][pol]["code_says"] == "CONTRADICT" and pf["arms"][pol]["would_refute"]
            )
            silent_false = sum(1 for pf in false_rows if pf["arms"][pol]["code_says"] == "SILENT")
            false_conf = sum(1 for pf in true_rows if pf["arms"][pol]["verdict"] is False)
            mem_tok = sum(pf["tokens_memory"] for pf in rows) if pol != "B" else 0.0
            ev_tok = sum(pf["tokens_evidence"] for pf in rows)
            agg["arms"][pol] = {
                "correct_rate": round(correct / n, 3) if n else None,
                "unknown_rate": round(unk / n, 3) if n else None,
                "adoption_rate": round(adoption / n_false, 3) if n_false else None,
                "code_contradictability": round(contradict / n_false, 3) if n_false else None,
                "correction_capability": round(refuted / contradict, 3) if contradict else None,
                "correction_gap": n_false - contradict,
                "memory_confidence_effect": silent_false,
                "false_confirmation_rate": round(false_conf / n_true, 3) if n_true else None,
                "tokens_memory_total": round(mem_tok, 1),
                "tokens_evidence_total": round(ev_tok, 1),
            }

        # ── Вывод ──
        result = {
            "_meta": {
                "experiment": "Experiment 1 — Memory Contamination (IntelligenceStore)",
                "date": "2026-08-11",
                "scan_ms_total": round(evidence_engine._scan_ms, 1),
                "isolation": {
                    "store_dir": str(harness.store.store_dir),
                    "real_project_store_dir": str(harness.real_store_dir),
                    "isolated": str(harness.store.store_dir) != str(harness.real_store_dir),
                },
            },
            "validation": validation,
            "per_fact": per_fact,
            "aggregates": agg,
        }
        out_path = HERE / (facts_path.stem.replace("facts", "results") + ".json")
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

        # Консольный свод
        print("=" * 78)
        print("Experiment 1: Memory Contamination (IntelligenceStore)")
        print(f"valid facts: {n} ({n_true}T + {n_false}F)  |  invalid: {len(validation['invalid'])}  "
              f"|  ambiguous: {len(validation['ambiguous'])}")
        print(f"isolation: {result['_meta']['isolation']}")
        print(f"code scan: {result['_meta']['scan_ms_total']}ms")
        print("-" * 78)
        hdr = f"{'arm':<16}{'correct':>9}{'adopt(F)':>10}{'contra':>8}{'corr_cap':>10}{'conf_eff':>10}{'unk':>7}{'tokens':>9}"
        print(hdr)
        for pol in policies:
            a = agg["arms"][pol]
            print(
                f"{pol:<16}{a['correct_rate']:>9}{a['adoption_rate']:>10}"
                f"{a['code_contradictability']:>8}{a['correction_capability']:>10}"
                f"{a['memory_confidence_effect']:>10}{a['unknown_rate']:>7}"
                f"{a['tokens_memory_total'] + a['tokens_evidence_total']:>9.1f}"
            )
        print("-" * 78)
        print(f"results: {out_path}")
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, json.JSONDecodeError) as e:
        import traceback
        traceback.print_exc()
        print(f"\nFAILED: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
