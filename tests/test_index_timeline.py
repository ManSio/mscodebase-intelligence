"""Тесты для временной шкалы индексации и фильтрации по времени."""

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Добавляем корень проекта в sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.search.engine import _filter_by_time
from src.core.search.utils import _parse_iso_datetime


# ─── Фикстуры ───────────────────────────────────────────────────────────────


@pytest.fixture
def sample_results():
    """Тестовые результаты поиска с разными indexed_at."""
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)
    last_week = now - timedelta(days=7)
    last_month = now - timedelta(days=30)

    return [
        {
            "text": "recent code",
            "text_full": "recent code full",
            "metadata": {
                "file": "recent.py",
                "chunk_index": 0,
                "indexed_at": now.isoformat(),
            },
        },
        {
            "text": "yesterday code",
            "text_full": "yesterday code full",
            "metadata": {
                "file": "yesterday.py",
                "chunk_index": 0,
                "indexed_at": yesterday.isoformat(),
            },
        },
        {
            "text": "last week code",
            "text_full": "last week code full",
            "metadata": {
                "file": "week.py",
                "chunk_index": 0,
                "indexed_at": last_week.isoformat(),
            },
        },
        {
            "text": "last month code",
            "text_full": "last month code full",
            "metadata": {
                "file": "month.py",
                "chunk_index": 0,
                "indexed_at": last_month.isoformat(),
            },
        },
        {
            "text": "no timestamp",
            "text_full": "no timestamp full",
            "metadata": {
                "file": "no_ts.py",
                "chunk_index": 0,
                "indexed_at": "",
            },
        },
    ]


# ─── Тесты _parse_iso_datetime ──────────────────────────────────────────────


class TestParseIsoDatetime:
    """Тесты парсинга ISO datetime."""

    def test_full_iso_format(self):
        dt = _parse_iso_datetime("2026-06-30T14:30:00")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 6
        assert dt.day == 30
        assert dt.hour == 14
        assert dt.minute == 30

    def test_iso_with_timezone(self):
        dt = _parse_iso_datetime("2026-06-30T14:30:00+03:00")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_date_only(self):
        dt = _parse_iso_datetime("2026-06-30")
        assert dt is not None
        assert dt.year == 2026

    def test_none_input(self):
        assert _parse_iso_datetime(None) is None

    def test_empty_string(self):
        assert _parse_iso_datetime("") is None

    def test_invalid_format(self):
        assert _parse_iso_datetime("not-a-date") is None


# ─── Тесты _filter_by_time ──────────────────────────────────────────────────


class TestFilterByTime:
    """Тесты фильтрации по времени."""

    def test_no_filters_returns_all(self, sample_results):
        """Без фильтров возвращаются все результаты."""
        result = _filter_by_time(sample_results)
        assert len(result) == len(sample_results)

    def test_since_filter(self, sample_results):
        """Фильтр since исключает старые чанки."""
        now = datetime.now(timezone.utc)
        # Используем 3 дня назад — должны остаться recent + yesterday
        since_val = (now - timedelta(days=2)).isoformat()

        result = _filter_by_time(sample_results, since=since_val)
        files = {r["metadata"]["file"] for r in result}
        assert "recent.py" in files
        assert "yesterday.py" in files
        assert "week.py" not in files
        assert "month.py" not in files

    def test_before_filter(self, sample_results):
        """Фильтр before исключает новые чанки."""
        now = datetime.now(timezone.utc)
        # 6 дней назад — должны остаться week + month
        before_val = (now - timedelta(days=6)).isoformat()

        result = _filter_by_time(sample_results, before=before_val)
        files = {r["metadata"]["file"] for r in result}
        assert "week.py" in files
        assert "month.py" in files
        assert "recent.py" not in files

    def test_both_filters(self, sample_results):
        """Комбинация since и before — диапазон."""
        now = datetime.now(timezone.utc)
        since = (now - timedelta(days=2)).isoformat()
        before = (now - timedelta(hours=12)).isoformat()

        result = _filter_by_time(sample_results, since=since, before=before)
        # Ожидаем только yesterday (между 2 днями и 12 часами)
        assert len(result) == 1
        assert result[0]["metadata"]["file"] == "yesterday.py"

    def test_empty_results(self):
        """Пустой список результатов."""
        result = _filter_by_time([], since="2026-01-01")
        assert result == []

    def test_chunks_without_indexed_at_excluded(self, sample_results):
        """Чанки без indexed_at исключаются при фильтрации."""
        result = _filter_by_time(sample_results, since="2020-01-01")
        files = {r["metadata"]["file"] for r in result}
        assert "no_ts.py" not in files

    def test_chunks_without_indexed_at_included_without_filter(self, sample_results):
        """Чанки без indexed_at включаются если нет фильтра."""
        result = _filter_by_time(sample_results)
        files = {r["metadata"]["file"] for r in result}
        assert "no_ts.py" in files


# ─── Тесты Searcher сигнатуры ──────────────────────────────────────────────


class TestSearcherTimeFilter:
    """Тесты что Searcher поддерживает since/before параметры."""

    def test_search_has_since_param(self):
        """Метод search принимает since."""
            from src.core.search.engine import Searcher
            import inspect
            sig = inspect.signature(Searcher.search)
        assert "since" in sig.parameters
        assert "before" in sig.parameters

    def test_hybrid_search_has_since_param(self):
        """Метод hybrid_search принимает since."""
            from src.core.search.engine import Searcher
            import inspect
            sig = inspect.signature(Searcher.hybrid_search)
        assert "since" in sig.parameters
        assert "before" in sig.parameters

    def test_hybrid_search_async_has_since_param(self):
        """Метод hybrid_search_async принимает since."""
            from src.core.search.engine import Searcher
            import inspect
            sig = inspect.signature(Searcher.hybrid_search_async)
        assert "since" in sig.parameters
        assert "before" in sig.parameters


# ─── Тесты граничных случаев ────────────────────────────────────────────────


class TestEdgeCases:
    """Тесты граничных случаев."""

    def test_invalid_since_format_filters_by_valid_only(self, sample_results):
        """Невалидный формат since — чанки с валидным indexed_at проходят."""
        # При невалидном since _parse_iso_datetime вернёт None
        # Фильтр не применяется — возвращаем все с валидным indexed_at
        result = _filter_by_time(sample_results, since="invalid-date")
        # Невалидный since → фильтр не применяется → все результаты
        # Но чанки без indexed_at исключаются при любом фильтре
        assert len(result) >= 4  # Все кроме no_ts.py

    def test_future_since_excludes_all(self, sample_results):
        """since в будущем исключает все чанки."""
        future = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()
        result = _filter_by_time(sample_results, since=future)
        assert len(result) == 0

    def test_past_before_excludes_all(self, sample_results):
        """before в прошлом исключает все чанки."""
        past = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
        result = _filter_by_time(sample_results, before=past)
        assert len(result) == 0
