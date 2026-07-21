"""Тесты для Watchdog — устранение ложной critical-ошибки при idle."""

import time

from src.core.indexing.indexer import Indexer


def _make_indexer():
    """Создаёт Indexer с минимальной инициализацией для теста watchdog."""
    from src.core.indexing.watchdog import Watchdog
    idx = Indexer.__new__(Indexer)
    idx._watchdog = Watchdog()
    return idx


def test_idle_is_alive_not_false():
    """При чистом idle watchdog НЕ должен сообщать alive=False (было '56 лет')."""
    idx = _make_indexer()
    status = idx.watchdog_status()
    assert status["alive"] is True
    assert status["idle_sec"] == 0.0


def test_heartbeat_marks_ever_beat():
    """После первого удара _watchdog_ever_beat = True."""
    idx = _make_indexer()
    idx.watchdog_heartbeat("parse:test.py")
    assert idx._watchdog._ever_beat is True
    status = idx.watchdog_status()
    assert status["alive"] is True
    assert status["label"] == "parse:test.py"


def test_stuck_indexer_detected():
    """Если heartbeat давно не бился (>60s) — alive=False (реальный завис)."""
    idx = _make_indexer()
    idx._watchdog._ever_beat = True
    idx._watchdog._heartbeat = time.time() - 120  # 2 минуты назад
    status = idx.watchdog_status()
    assert status["alive"] is False
    assert status["idle_sec"] >= 119.0


def test_recent_heartbeat_alive():
    """Свежий удар (<60s) — alive=True."""
    idx = _make_indexer()
    idx._watchdog._ever_beat = True
    idx._watchdog._heartbeat = time.time() - 5
    status = idx.watchdog_status()
    assert status["alive"] is True
    assert status["idle_sec"] < 60.0
