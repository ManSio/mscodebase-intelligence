"""Read-only второго сервера: отказ типизирован и виден в health и автоиндексе.

Логи 2026-11-17: 621 `База занята другим процессом MCP` и 280 `PID lock held`,
а `get_health_report` показывал `issues: []`. Агент не мог понять, почему запись
и индексация не работают.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.core.error_envelope import ErrorCode
from src.core.indexing import auto_index_state
from src.core.indexing.db_manager import LanceDBManager
from src.core.intelligence.health import HealthReport


def _manager(root: Path) -> LanceDBManager:
    project = root / "project"
    project.mkdir(parents=True, exist_ok=True)
    return LanceDBManager(
        db_path=root / "index.lancedb",
        embedder=None,
        project_path=project,
        embedding_dim=768,
    )


def test_second_manager_write_is_typed_and_actionable(tmp_path):
    owner = _manager(tmp_path)
    try:
        second = _manager(tmp_path)
        try:
            with pytest.raises(Exception) as exc:
                with second.begin_write():
                    pass
            err = exc.value
            assert getattr(err, "code", "") == ErrorCode.DATABASE_LOCKED.value
            assert getattr(err, "recoverable", False) is True
            detail = getattr(err, "detail", "")
            assert "занята другим процессом" in detail
        finally:
            if second._pid_lock_acquired:
                second._db_lock.release()
    finally:
        if owner._pid_lock_acquired:
            owner._db_lock.release()


class _LockedDb:
    _startup_issue = "База занята другим процессом MCP — работаю read-only."


class _Indexer:
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.project_path = Path(".")


def test_health_reports_read_only_as_issue(tmp_path):
    report = HealthReport(tmp_path, indexer=_Indexer(_LockedDb()))
    report._check_write_capability()

    assert report.metrics["write_capable"] is False
    assert any(item["component"] == "database_lock" for item in report.issues)
    message = next(i["message"] for i in report.issues if i["component"] == "database_lock")
    assert "read-only" in message


def test_health_reports_write_capable_without_lock(tmp_path):
    class _Free:
        _startup_issue = None

    report = HealthReport(tmp_path, indexer=_Indexer(_Free()))
    report._check_write_capability()

    assert report.metrics["write_capable"] is True
    assert report.issues == []


def test_auto_index_skip_reason_reaches_health(tmp_path, monkeypatch):
    monkeypatch.setattr(auto_index_state, "_SKIPPED_REASON", "", raising=False)
    auto_index_state.mark_skipped("database locked by another MCP process")

    report = HealthReport(tmp_path, indexer=_Indexer(_LockedDb()))
    report._check_write_capability()

    assert report.metrics["auto_index"].startswith("skipped:")
    assert "database locked" in report.metrics["auto_index"]


def test_auto_index_block_reason_reads_the_lock():
    from src.mcp.server_factory import auto_index_block_reason

    assert auto_index_block_reason(_Indexer(_LockedDb())) != ""
    assert auto_index_block_reason(_Indexer(type("Free", (), {"_startup_issue": None})())) == ""
    assert auto_index_block_reason(object()) == ""
