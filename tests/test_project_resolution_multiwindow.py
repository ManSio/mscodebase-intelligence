"""Регрессионные тесты multi-window изоляции резолвера проекта (INC-MULTI-WINDOW).

История бага: SQLite `multi_workspace_state.active_workspace_id` глобальный
на весь Zed — одна строка на namespace (key = window_id), но резолв берёт
`rowid DESC LIMIT 1` БЕЗ фильтра по окну. Два окна Zed резолвили ОДИН
проект → PID-lock конфликт (database_lock.py) → ProjectState.FAILED
во втором окне и привязка MCP к чужому проекту.

Фикс: CWD-first. Zed запускает отдельный MCP-процесс на окно и ставит
CWD = корень окна — CWD единственный per-process сигнал.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

import src.core.project_resolution as pr
from src.core.project_resolution import (
    _check_sqlite_schema_health,
    resolve_project_root,
)


@pytest.fixture()
def _cwd_restorer():
    """Восстанавливает CWD после теста, меняющего os.chdir."""
    old = Path.cwd()
    yield
    os.chdir(old)


def _make_project(tmp_path: Path, name: str) -> Path:
    p = tmp_path / name
    p.mkdir()
    return p


class TestCwdFirstIsolation:
    """Главная регрессия: каждое «окно» резолвит СВОЙ CWD."""

    def test_two_windows_resolve_own_cwd(self, tmp_path, _cwd_restorer):
        """Два окна (два CWD) — два разных проекта, без обращения к SQLite."""
        project_a = _make_project(tmp_path, "project_a")
        project_b = _make_project(tmp_path, "project_b")

        os.chdir(project_a)
        assert resolve_project_root().resolve() == project_a.resolve()

        os.chdir(project_b)
        assert resolve_project_root().resolve() == project_b.resolve()

    def test_cwd_wins_over_global_active_workspace(self, tmp_path, _cwd_restorer, monkeypatch):
        """Регрессия бага: CWD побеждает глобальный active_workspace_id.

        FakeConn имитирует SQLite Zed, где «активный workspace» = project_b.
        Раньше (SQLite-first) оба окна резолвили project_b → PID-lock конфликт.
        """
        project_a = _make_project(tmp_path, "project_a")
        project_b = _make_project(tmp_path, "project_b")

        class FakeCursor:
            def execute(self, *a, **k):
                pass

            def fetchone(self):
                # scoped_kv_store row: (key, value) — активный = project_b
                return ("5", '{"active_workspace_id":5}')

        class FakeConn:
            def cursor(self):
                return FakeCursor()

        monkeypatch.setattr(pr, "_get_sqlite_connection", lambda: FakeConn())
        monkeypatch.setattr(pr, "_resolve_env_project_root", lambda: None)
        monkeypatch.delenv("ZED_WORKTREE_ROOT", raising=False)

        os.chdir(project_a)
        assert resolve_project_root().resolve() == project_a.resolve()

        os.chdir(project_b)
        assert resolve_project_root().resolve() == project_b.resolve()

    def test_zed_literal_project_path_is_ignored(self, tmp_path, _cwd_restorer, monkeypatch):
        """PROJECT_PATH="$ZED_WORKTREE_ROOT" (литерал Zed, не раскрыт) → None → CWD."""
        project = _make_project(tmp_path, "project_a")
        monkeypatch.setenv("PROJECT_PATH", "$ZED_WORKTREE_ROOT")
        monkeypatch.delenv("ZED_WORKTREE_ROOT", raising=False)
        monkeypatch.setattr(pr, "_get_sqlite_connection", lambda: None)

        os.chdir(project)
        assert resolve_project_root().resolve() == project.resolve()

    def test_provided_wins_over_cwd(self, tmp_path, _cwd_restorer):
        """Явный provided (аргумент вызова) важнее CWD."""
        project_a = _make_project(tmp_path, "project_a")
        project_b = _make_project(tmp_path, "project_b")

        os.chdir(project_a)
        assert resolve_project_root(str(project_b)).resolve() == project_b.resolve()


class TestCwdSelfIndexGuard:
    def test_cwd_equal_ext_root_is_skipped(self, tmp_path, _cwd_restorer, monkeypatch):
        """CWD == ext_root (dev/test-режим) — CWD отклоняется, fallback работает."""
        monkeypatch.setattr(pr, "ext_root", tmp_path)  # CWD == ext_root
        monkeypatch.setattr(pr, "_get_sqlite_connection", lambda: None)
        env_fallback = tmp_path / "env-project"
        monkeypatch.setattr(pr, "_resolve_env_project_root", lambda: env_fallback)
        monkeypatch.delenv("ZED_WORKTREE_ROOT", raising=False)

        os.chdir(tmp_path)
        assert resolve_project_root() == env_fallback  # CWD пропущен guard'ом


class TestSqliteSchemaHealth:
    def test_current_schema_ok(self):
        """Реальная схема Zed (workspace_id/paths/timestamp) — без предупреждений."""
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE scoped_kv_store (namespace TEXT, key TEXT, value TEXT)")
        conn.execute(
            "CREATE TABLE workspaces (workspace_id TEXT, paths TEXT, paths_order TEXT, "
            "remote_connection_id TEXT, timestamp TEXT)"
        )
        assert _check_sqlite_schema_health(conn) is None
        conn.close()

    def test_old_schema_detected(self):
        """Устаревшая схема (workspace/data) — предупреждение, а не молчание."""
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE scoped_kv_store (namespace TEXT, key TEXT, value TEXT)")
        conn.execute("CREATE TABLE workspaces (workspace TEXT, data TEXT)")
        assert _check_sqlite_schema_health(conn) is not None
        conn.close()

    def test_missing_table_detected(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE scoped_kv_store (namespace TEXT, key TEXT, value TEXT)")
        assert _check_sqlite_schema_health(conn) is not None
        conn.close()

    def test_none_connection(self):
        assert _check_sqlite_schema_health(None) is not None
