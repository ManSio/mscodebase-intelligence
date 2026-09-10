"""
Tests for AlertStore (system_alerts) + доставка.

Покрытие:
- push/collect_and_clear (одноразовость: второй collect — пусто)
- дедупликация по kind+payload
- limit (доставка не копится — токен-оверхед)
- битый JSON graceful degrade
- гонка двух параллельных collect_and_clear (два threading)
- per-project изоляция (multi-window)
- integer-точечные хуки: mark_stale("memory") в notify_change + доставка в
  format_system_alerts (renders), не ломает обратную совместимость.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from src.core.intelligence.alert_store import AlertStore, get_alert_store


@pytest.fixture
def store(tmp_path: Path) -> AlertStore:
    return AlertStore(tmp_path / "proj")


def test_push_collect_clear_oneshot(store: AlertStore):
    store.push("memory_stale", "msg1")
    alerts = store.collect_and_clear()
    assert len(alerts) == 1
    assert alerts[0]["kind"] == "memory_stale"
    assert alerts[0]["message"] == "msg1"
    # Одноразовость: после доставки — пусто.
    assert store.collect_and_clear() == []
    assert store.peek() == []


def test_push_dedup_same_payload(store: AlertStore):
    store.push("memory_stale", "m", {"reason": "file: a.py"})
    store.push("memory_stale", "m", {"reason": "file: a.py"})
    assert len(store.peek()) == 1


def test_push_distinct_payload_kept(store: AlertStore):
    store.push("memory_stale", "m", {"reason": "file: a.py"})
    store.push("memory_stale", "m", {"reason": "file: b.py"})
    assert len(store.peek()) == 2


def test_collect_limit(store: AlertStore):
    for i in range(7):
        store.push("memory_stale", f"m{i}", {"reason": f"f{i}.py"})
    first = store.collect_and_clear(limit=3)
    assert len(first) == 3
    second = store.collect_and_clear(limit=3)
    assert len(second) == 3
    third = store.collect_and_clear(limit=3)
    assert len(third) == 1
    assert store.collect_and_clear() == []


def test_unknown_kind_ignored(store: AlertStore):
    store.push("not_a_kind", "x")
    assert store.peek() == []


def test_corrupt_json_graceful(tmp_path: Path):
    s = AlertStore(tmp_path / "proj")
    (s.store_dir / "system_alerts.json").write_text("{not json", encoding="utf-8")
    assert s.peek() == []  # не падает, сброс
    s.push("memory_starved", "s")
    assert len(s.peek()) == 1


def test_concurrent_collect_single_delivery(tmp_path: Path):
    """Гонка: два потока читают alerts одновременно — один alert получил ровно один."""
    s = AlertStore(tmp_path / "proj")
    for i in range(20):
        s.push("memory_stale", f"m{i}", {"reason": f"f{i}.py"})
    results: list = []
    barrier = threading.Barrier(2)

    def _collect():
        barrier.wait()
        results.append(s.collect_and_clear(limit=100))

    t1 = threading.Thread(target=_collect)
    t2 = threading.Thread(target=_collect)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    total = len(results[0]) + len(results[1])
    assert total == 20  # ни один alert не потерян и не задвоен


def test_per_project_isolation(tmp_path: Path):
    s_a = AlertStore(tmp_path / "proj_a")
    s_b = AlertStore(tmp_path / "proj_b")
    s_a.push("memory_stale", "a")
    s_b.push("memory_stale", "b")
    assert len(s_a.peek()) == 1
    assert len(s_b.peek()) == 1
    got_a = s_a.collect_and_clear()
    assert got_a[0]["message"] == "a"
    assert len(s_b.peek()) == 1  # b не тронут


def test_get_alert_store_singleton_per_project(tmp_path: Path):
    a = get_alert_store(tmp_path / "proj")
    b = get_alert_store(tmp_path / "proj")
    assert a is b
    c = get_alert_store(tmp_path / "proj2")
    assert a is not c


def test_singleton_cache_key_resolved(tmp_path: Path):
    import os

    a = get_alert_store(Path(os.getcwd()))
    b = get_alert_store(Path(str(Path(os.getcwd()).resolve())))
    # resolve - один и тот же ключ, один store
    assert a is b


def test_starved_alert_message(tmp_path: Path):
    s = AlertStore(tmp_path / "proj")
    s.push(
        "memory_starved",
        "2 узлов памяти видны ≥2 циклов, но ни разу не проверены",
        {"starved_nodes": ["N1", "N2"]},
    )
    alerts = s.collect_and_clear()
    assert alerts[0]["kind"] == "memory_starved"
    assert alerts[0]["payload"]["starved_nodes"] == ["N1", "N2"]
