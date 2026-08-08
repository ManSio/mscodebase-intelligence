"""Consistency Engine: состояния, переходы, thread-safety, guard."""

import threading

from src.core.consistency import (
    ConsistencyState,
    ConsistencyTracker,
    get_consistency_tracker,
)


def _fresh_tracker() -> ConsistencyTracker:
    """Новый трекер без глобального синглтона (изоляция тестов)."""
    return ConsistencyTracker()


def test_default_states_unknown():
    t = _fresh_tracker()
    for domain in ("source", "index", "graph", "symbols", "memory", "commit_memory"):
        entry = t.get(domain)
        assert entry["state"] == ConsistencyState.UNKNOWN.value


def test_transitions():
    t = _fresh_tracker()
    t.mark_stale("source", "file changed")
    assert t.get("source")["state"] == ConsistencyState.STALE.value
    t.mark_updating("index", "reindex started")
    assert t.get("index")["state"] == ConsistencyState.UPDATING.value
    t.mark_consistent("index", "reindex completed")
    assert t.is_consistent("index") is True
    t.mark_corrupted("graph", "db unreadable")
    assert t.get("graph")["state"] == ConsistencyState.CORRUPTED.value
    t.mark_partial("symbols", "partial update")
    assert t.get("symbols")["state"] == ConsistencyState.PARTIAL.value


def test_unknown_domain_ignored():
    t = _fresh_tracker()
    t.set("nonexistent", ConsistencyState.CONSISTENT)
    assert "nonexistent" not in t.get_all()


def test_require_guard():
    t = _fresh_tracker()
    # По умолчанию UNKNOWN — enrichment должен отложиться.
    ok, state = t.require("graph", ConsistencyState.CONSISTENT)
    assert ok is False
    assert state == ConsistencyState.UNKNOWN
    t.mark_consistent("graph")
    ok, _ = t.require("graph", ConsistencyState.CONSISTENT, ConsistencyState.UPDATING)
    assert ok is True


def test_age_sec_increases():
    import time

    t = _fresh_tracker()
    t.mark_consistent("index")
    time.sleep(0.05)
    age = t.get("index")["age_sec"]
    assert age is not None and age >= 0.05


def test_thread_safety_concurrent_updates():
    """N потоков пишут разные домены — ни одно обновление не теряется."""
    t = _fresh_tracker()
    domains = ["source", "index", "graph", "symbols", "memory", "commit_memory"]
    errors = []

    def _writer(domain: str):
        try:
            for _ in range(50):
                t.mark_stale(domain, "thread-write")
                t.mark_consistent(domain, "thread-write")
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=_writer, args=(d,)) for d in domains * 2]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    assert not errors
    # Финальное состояние консистентно (последняя запись каждого домена).
    for d in domains:
        assert t.get(d)["state"] == ConsistencyState.CONSISTENT.value


def test_global_singleton_identity():
    assert get_consistency_tracker() is get_consistency_tracker()
