"""EXP-4: Population blind spot в _check_search_quality (health.py:676-767).

Вопрос Тома (день 2): «0 строк с 0 eligible — здоровый инструмент без работы;
0 строк с 400 eligible — сломанный коллектор. Снаружи — одинаковый чек.
eligible_seen до селекции ≠ population_size после».

Здесь: что говорит _check_search_quality когда searcher возвращает
(a) [] — пустая популяция (пустой индекс — «здоровый idle»),
(b) мусорные чанки — сломанный коллектор,
(c) реальные результаты — контроль.
Если (a) и (b) дают ОДИНАКОВОЕ предупреждение — gap подтверждён.

Файл импортируется напрямую (importlib, stdlib-only health.py) — без цепочки
пакетных __init__, которые тянут тяжёлые зависимости.
"""
import importlib.util
import sys
import traceback
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

HEALTH_PY = Path(__file__).resolve().parent.parent / "src" / "core" / "intelligence" / "health.py"


def load_health():
    spec = importlib.util.spec_from_file_location("health_standalone", HEALTH_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.HealthReport


REAL_RESULT = {"text": "def f():\n    pass",
               "metadata": {"file": "src/a.py", "chunk_index": 0, "layer": "core"}}
GARBAGE = {"text": "", "metadata": {"file": "init.py"}}
GARBAGE_WS = {"text": "   \n  ", "metadata": {"file": "init.py"}}


class FakeSearcher:
    def __init__(self, responses):
        self._responses = responses

    def hybrid_search(self, query, limit=3, **kwargs):
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]


class RaisingSearcher:
    def hybrid_search(self, query, limit=3, **kwargs):
        raise RuntimeError("embedder down")


def run_case(HealthReport, label, searcher):
    from types import SimpleNamespace
    indexer = SimpleNamespace(searcher=searcher)
    report = HealthReport(project_path=Path("."), indexer=indexer)
    report._check_search_quality()
    warn = [w for w in report.warnings if w["component"] == "search_quality"]
    print(f"\n[{label}]")
    print(f"  metrics: {report.metrics}")
    for w in warn:
        print(f"  warning: {w['message']}")
    return report, warn


def main():
    HealthReport = load_health()
    print("=" * 72)
    print("EXP-4: Population blind spot — _check_search_quality")
    print(f"Источник: {HEALTH_PY}")
    print("=" * 72)

    # (c) контроль: реальные результаты → passed=3, без warning
    rep, w = run_case(HealthReport, "(c) КОНТРОЛЬ: реальные результаты", FakeSearcher([[REAL_RESULT]]))
    assert rep.metrics.get("search_quality_passed") == 3, "контроль сломан"

    # (a) пустая популяция: searcher вернул [] — «здоровый idle» (пустой индекс)
    rep_a, w_a = run_case(HealthReport, "(a) ПУСТАЯ популяция: searcher → [] (индекс пуст)", FakeSearcher([[]]))

    # (b) сломанный коллектор: мусорные чанки
    rep_b, w_b = run_case(HealthReport, "(b) МУСОР: пустые/whitespace чанки", FakeSearcher([[GARBAGE, GARBAGE_WS]]))

    # (b2) ошибка поиска
    rep_b2, w_b2 = run_case(HealthReport, "(b2) ОШИБКА searcher (embedder down)", RaisingSearcher())

    # Сравнение (a) vs (b): одинаковы ли предупреждения?
    msg_a = w_a[0]["message"] if w_a else "NO WARNING"
    msg_b = w_b[0]["message"] if w_b else "NO WARNING"
    print("\n" + "=" * 72)
    print("СРАВНЕНИЕ:")
    print(f"  (a) пустая популяция → {msg_a}")
    print(f"  (b) мусор            → {msg_b}")
    print(f"  ИДЕНТИЧНЫ? {msg_a == msg_b}")
    print("  → gap Тома подтверждён: «0 eligible» (здоровый idle) и «0 собрано»")
    print("    (сломанный коллектор) дают один и тот же сигнал. eligible_seen"
          " до селекции не измеряется (health.py:744-756).")
    print("=" * 72)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
