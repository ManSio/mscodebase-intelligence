"""Тесты усиленного synthetic monitoring качества поиска (аудит Bot_snow #15).

Было: `_check_search_quality` считал тест сданным при «список не пуст» — но
Searcher.search() возвращает СТРОКУ, и даже сообщение «ничего не найдено»
имело len>0 → тест проходил всегда. Плюс мусорные чанки (пустые __init__.py
с fallback_lines, error-dicts от vector_search) проходили как «результаты».

Стало: hybrid_search() → List[dict]; тест сдан только при ≥1 реальном
результате (файл + непустой текст). Три разных запроса вместо «index file» ×3.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from src.core.intelligence.health import HealthReport

REAL_RESULT = {
    "text": "def f():\n    pass",
    "metadata": {"file": "src/a.py", "chunk_index": 0, "layer": "core"},
}


class FakeSearcher:
    def __init__(self, responses):
        self._responses = responses  # каждый элемент — СПИСОК результатов (как hybrid_search)

    def hybrid_search(self, query, limit=3, **kwargs):
        # По-очереди выдаём ответы (иначе один и тот же на 3 запроса).
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]


def _make_report(searcher, total_chunks=100) -> HealthReport:
    indexer = SimpleNamespace(searcher=searcher)
    indexer.get_status = lambda: {"total_chunks": total_chunks}
    return HealthReport(project_path=Path("."), indexer=indexer)


class TestIsQualityResult:
    def test_real_result_passes(self):
        assert HealthReport._is_quality_result(REAL_RESULT) is True

    def test_file_path_variant_passes(self):
        assert (
            HealthReport._is_quality_result(
                {"text": "x = 1", "file_path": "b.py"}
            )
            is True
        )

    def test_empty_text_is_garbage(self):
        """Пустой/whitespace текст (пустые __init__.py c fallback_lines)."""
        assert (
            HealthReport._is_quality_result(
                {"text": "", "metadata": {"file": "init.py"}}
            )
            is False
        )
        assert (
            HealthReport._is_quality_result(
                {"text": "   \n  ", "metadata": {"file": "init.py"}}
            )
            is False
        )

    def test_error_dict_is_garbage(self):
        assert HealthReport._is_quality_result({"error": "lance error"}) is False

    def test_missing_file_is_garbage(self):
        assert HealthReport._is_quality_result({"text": "x = 1"}) is False

    def test_non_dict_is_garbage(self):
        assert HealthReport._is_quality_result("not a dict") is False


class TestCheckSearchQuality:
    def test_passes_on_real_results(self):
        report = _make_report(FakeSearcher([[REAL_RESULT]]))
        report._check_search_quality()

        assert report.metrics["search_quality_passed"] == 3
        assert not [w for w in report.warnings if w["component"] == "search_quality"]

    def test_fails_on_garbage_chunks(self):
        """Мусорные чанки при непустой популяции — «broken collector» (регрессия #15 + EXP-4)."""
        garbage = {"text": "", "metadata": {"file": "init.py"}}
        report = _make_report(FakeSearcher([[garbage]]))
        report._check_search_quality()

        assert report.metrics["search_quality_passed"] == 0
        assert report.metrics["search_quality_eligible_seen"] == 100
        search_warnings = [w for w in report.warnings if w["component"] == "search_quality"]
        assert search_warnings, "Ожидалось предупреждение о мусорных результатах"
        assert "0 реальных результатов" in search_warnings[0]["message"]
        assert "100 eligible" in search_warnings[0]["message"], \
            "warning обязан нести population manifest (EXP-4)"

    def test_empty_population_is_healthy_idle(self):
        """Пустой индекс (0 eligible): synthetic-запросы не имеют смысла —
        НЕ «broken collector», а ожидаемый idle (EXP-4: различимость).
        Warnings нет (дублировал бы issue «Индекс пуст» из _check_index_integrity)."""
        report = _make_report(FakeSearcher([[]]), total_chunks=0)
        report._check_search_quality()

        assert report.metrics["search_quality_eligible_seen"] == 0
        assert report.metrics["search_quality_skipped"] == "empty_index"
        assert not [w for w in report.warnings if w["component"] == "search_quality"], \
            "0 eligible + 0 собрано = healthy idle, не warning"

    def test_eligible_seen_unknown_falls_back(self):
        """get_status недоступен → eligible_seen=-1, проверка идёт как раньше."""
        searcher = FakeSearcher([[REAL_RESULT]])
        indexer = SimpleNamespace(searcher=searcher)
        # get_status отсутствует — имитация сломанного/старого indexer
        report = HealthReport(project_path=Path("."), indexer=indexer)
        report._check_search_quality()

        assert report.metrics["search_quality_eligible_seen"] == -1
        assert report.metrics["search_quality_passed"] == 3

    def test_fails_when_searcher_raises(self):
        class RaisingSearcher:
            def hybrid_search(self, query, limit=3, **kwargs):
                raise RuntimeError("embedder down")

        report = _make_report(RaisingSearcher())
        report._check_search_quality()

        assert report.metrics["search_quality_passed"] == 0
        search_warnings = [w for w in report.warnings if w["component"] == "search_quality"]
        assert search_warnings, "Ожидалось предупреждение об ошибке поиска"
        assert "с ошибкой" in search_warnings[0]["message"]

    def test_metrics_set(self):
        report = _make_report(FakeSearcher([REAL_RESULT]))
        report._check_search_quality()
        assert report.metrics["search_quality_total_tests"] == 3
        assert "search_quality_passed" in report.metrics
