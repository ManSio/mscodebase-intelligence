"""Тесты Startup Diagnostics — человекочитаемая диагностика при старте (Задача 3/5).

Покрывают read-only инспекцию PID-lock-файла и директории LanceDB:
free / held_alive / stale / corrupt для lock-а; missing / empty / healthy /
corrupt для БД; и сборку человеческого отчёта с действиями (без Rust-трейсов).

Ключевое свойство (из докстринга модуля): диагностика STRICTLY READ-ONLY —
тесты гарантируют, что inspect_* НЕ создаёт, НЕ удаляет и НЕ изменяет файлы
(никаких побочных эффектов на реальном индексе).
"""

from __future__ import annotations

import json
import os

import pytest

from src.core.indexing.database_lock import DatabaseLock
from src.core.indexing.startup_diagnostics import (
    LOCK_FILENAME,
    build_startup_report,
    inspect_db,
    inspect_pid_lock,
)

DEAD_PID = 999_999_999  # заведомо несуществующий PID (Windows/Unix)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "lancedb_v2"


@pytest.fixture
def lock_path(db_path):
    return db_path / LOCK_FILENAME


# ══════════════════════════════════════════════════════════
# inspect_pid_lock
# ══════════════════════════════════════════════════════════


class TestInspectPidLock:
    def test_missing_lock_is_free(self, lock_path):
        status = inspect_pid_lock(lock_path)
        assert status.state == "free"
        assert status.holder_pid is None

    def test_lock_with_dead_pid_is_stale(self, lock_path):
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(
            json.dumps({"pid": DEAD_PID, "started": 1000.0, "role": "worker"}),
            encoding="utf-8",
        )
        status = inspect_pid_lock(lock_path)
        assert status.state == "stale"
        assert status.holder_pid == DEAD_PID

    def test_lock_with_alive_pid_is_held(self, lock_path):
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(
            json.dumps({"pid": os.getpid(), "started": 1000.0, "role": "worker"}),
            encoding="utf-8",
        )
        status = inspect_pid_lock(lock_path)
        assert status.state == "held_alive"
        assert status.holder_pid == os.getpid()

    def test_corrupt_lock_json(self, lock_path):
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text("{not json", encoding="utf-8")
        status = inspect_pid_lock(lock_path)
        assert status.state == "corrupt"

    def test_lock_without_pid_is_corrupt(self, lock_path):
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(json.dumps({"started": 1000.0}), encoding="utf-8")
        status = inspect_pid_lock(lock_path)
        assert status.state == "corrupt"

    def test_inspect_does_not_create_files(self, db_path, lock_path):
        # Read-only гарантия: инспекция отсутствующего lock-а не создаёт файлы.
        inspect_pid_lock(lock_path)
        assert not db_path.exists()
        assert not lock_path.exists()

    def test_inspect_does_not_delete_lock(self, lock_path):
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(
            json.dumps({"pid": DEAD_PID, "started": 1000.0, "role": "worker"}),
            encoding="utf-8",
        )
        inspect_pid_lock(lock_path)  # не должно снять/удалить чужой stale-lock
        assert lock_path.exists()


# ══════════════════════════════════════════════════════════
# inspect_db
# ══════════════════════════════════════════════════════════


class TestInspectDb:
    def test_missing_dir_is_missing(self, db_path):
        status = inspect_db(db_path)
        assert status.state == "missing"
        assert not db_path.exists()  # не создаёт директорию

    def test_empty_dir_without_table(self, db_path):
        db_path.mkdir(parents=True, exist_ok=True)
        status = inspect_db(db_path)
        assert status.state == "empty"

    def test_corrupt_dir_returns_human_text(self, db_path):
        # Директория есть, но содержимое битое — inspect_db должен вернуть
        # человеческий текст с действием, а не Rust-трейс.
        db_path.mkdir(parents=True, exist_ok=True)
        (db_path / "codebase_chunks.lance").mkdir(parents=True, exist_ok=True)
        (db_path / "codebase_chunks.lance" / "broken").write_text(
            "not a lance file", encoding="utf-8"
        )
        status = inspect_db(db_path)
        assert status.state == "corrupt"
        assert "lance-io" not in status.message
        assert "intel_reset_index" in status.message or "удалите папку" in status.message


# ══════════════════════════════════════════════════════════
# build_startup_report — человеческий отчёт с действиями
# ══════════════════════════════════════════════════════════


class TestBuildStartupReport:
    def test_all_free_healthy_no_issues(self, db_path):
        report = build_startup_report(db_path)
        assert report.lock.state == "free"
        assert report.db.state == "missing"
        # missing + free — это нормальный первый запуск: есть issue про автоиндексацию
        assert any("автоиндексация" in i.lower() for i in report.issues)

    def test_missing_db_issue_mentions_autoindex(self, db_path):
        report = build_startup_report(db_path)
        joined = " ".join(report.issues).lower()
        assert "автоиндексация" in joined

    def test_held_alive_adds_close_second_window_issue(self, db_path, lock_path):
        db_path.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(
            json.dumps({"pid": os.getpid(), "started": 1000.0, "role": "worker"}),
            encoding="utf-8",
        )
        report = build_startup_report(db_path, lock_path=lock_path)
        assert report.lock.state == "held_alive"
        assert any("второе окно" in i or "второй экземпляр" in i for i in report.issues)

    def test_corrupt_db_adds_reset_issue(self, db_path):
        db_path.mkdir(parents=True, exist_ok=True)
        (db_path / "codebase_chunks.lance").mkdir(parents=True, exist_ok=True)
        (db_path / "codebase_chunks.lance" / "broken").write_text("x", encoding="utf-8")
        report = build_startup_report(db_path)
        assert report.db.state == "corrupt"
        assert any("intel_reset_index" in i for i in report.issues)

    def test_human_report_has_no_rust_paths(self, db_path):
        db_path.mkdir(parents=True, exist_ok=True)
        (db_path / "codebase_chunks.lance").mkdir(parents=True, exist_ok=True)
        (db_path / "codebase_chunks.lance" / "broken").write_text("x", encoding="utf-8")
        report = build_startup_report(db_path)
        text = report.to_human()
        assert "local.rs" not in text
        assert "lance-io" not in text
        assert "Диагностика индекса" in text

    def test_reuses_database_lock_semantics(self, lock_path):
        # inspect_pid_lock должен согласованно видеть lock, созданный DatabaseLock
        lock = DatabaseLock(lock_path, wait_timeout=0.2)
        lock.acquire()
        try:
            status = inspect_pid_lock(lock_path)
            assert status.state == "held_alive"
            assert status.holder_pid == os.getpid()
        finally:
            lock.release()
        status_after = inspect_pid_lock(lock_path)
        assert status_after.state == "free"
