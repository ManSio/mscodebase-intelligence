"""Тесты для JobHistoryStore — адаптивный ETA на основе истории индексаций."""

from pathlib import Path

import pytest

from src.core.intelligence.layer import JobHistoryStore


@pytest.fixture
def temp_project(tmp_path: Path) -> Path:
    """Временный проект для тестов."""
    project = tmp_path / "test_project"
    project.mkdir(parents=True, exist_ok=True)
    return project


def test_append_and_load(temp_project: Path):
    """Запись и чтение истории работают корректно."""
    store = JobHistoryStore(temp_project)
    store.append_record(100, 35.0)
    store.append_record(120, 40.0)

    history = store.load_history()
    assert len(history) == 2
    assert history[0]["project_size"] == 100
    assert history[0]["duration_sec"] == 35.0
    assert "timestamp" in history[0]


def test_history_file_location(temp_project: Path):
    """История сохраняется в .codebase_indices/metrics/job_history.json."""
    store = JobHistoryStore(temp_project)
    store.append_record(50, 20.0)

    expected = temp_project / ".codebase_indices" / "metrics" / "job_history.json"
    assert expected.exists()


def test_rolling_average_similar_size(temp_project: Path):
    """Rolling average по размеру проекта (+-20%)."""
    store = JobHistoryStore(temp_project)
    # Похожие проекты: 100, 110, 90 файлов
    store.append_record(100, 30.0)
    store.append_record(110, 40.0)
    store.append_record(90, 50.0)
    # Другой проект: 500 файлов (не должен влиять)
    store.append_record(500, 200.0)

    # Для проекта в 105 файлов среднее по 3-м похожим = (30+40+50)/3 = 40
    avg = store.get_estimated_duration(105)
    assert 39.0 <= avg <= 41.0


def test_rolling_average_fallback_no_history(temp_project: Path):
    """Fallback на дефолт, если истории нет."""
    store = JobHistoryStore(temp_project)
    avg = store.get_estimated_duration(100, fallback=120.0)
    assert avg == 120.0


def test_rolling_average_fallback_no_similar(temp_project: Path):
    """Fallback на среднее всех, если похожих проектов нет."""
    store = JobHistoryStore(temp_project)
    store.append_record(500, 200.0)
    store.append_record(600, 220.0)

    # Для проекта в 100 файлов похожих нет → среднее по всем = 210
    avg = store.get_estimated_duration(100, fallback=120.0)
    assert 209.0 <= avg <= 211.0


def test_history_truncated_to_50(temp_project: Path):
    """История обрезается до 50 последних записей."""
    store = JobHistoryStore(temp_project)
    for i in range(60):
        store.append_record(100 + i, float(i))

    history = store.load_history()
    assert len(history) == 50
    # Последняя запись — 59-я (индекс с 0)
    assert history[-1]["project_size"] == 159


def test_corrupted_history_recovers(temp_project: Path):
    """При повреждённом JSON возвращается []."""
    metrics_dir = temp_project / ".codebase_indices" / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    history_file = metrics_dir / "job_history.json"
    history_file.write_text("{ broken json", encoding="utf-8")

    store = JobHistoryStore(temp_project)
    assert store.load_history() == []
    # И запись всё ещё работает
    store.append_record(10, 5.0)
    assert len(store.load_history()) == 1
