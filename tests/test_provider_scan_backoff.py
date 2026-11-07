"""Provider scanner backoff (2026-11-07).

До фикса: фиксированные 13 с × 20 итераций при живом llama.cpp и «пустом»
LM Studio → ~20 одинаковых предупреждений и постоянные health-пробы.
Теперь интервал удваивается до 5 минут, а итераций 8 (~22 мин бюджета).
"""

from __future__ import annotations

from src.providers.embedder import remote_embedder as re_mod


def test_backoff_doubles_until_cap():
    interval = 13
    seen = []
    for _ in range(10):
        interval = re_mod._next_scan_interval(interval)
        seen.append(interval)
    assert seen[0] == 26
    assert seen[-1] == re_mod._PROVIDER_SCAN_BACKOFF_MAX
    assert all(i <= re_mod._PROVIDER_SCAN_BACKOFF_MAX for i in seen)


def test_backoff_is_monotonic():
    interval = 30
    previous = interval
    for _ in range(6):
        interval = re_mod._next_scan_interval(interval)
        assert interval >= previous
        previous = interval


def test_scanner_budget_about_twenty_minutes():
    """8 итераций с backoff должны покрывать ~20 минут поиска провайдера."""
    interval = re_mod._PROVIDER_SCAN_INTERVAL
    total = 0
    for _ in range(8):
        total += interval
        interval = re_mod._next_scan_interval(interval)
    assert total >= 15 * 60, total
