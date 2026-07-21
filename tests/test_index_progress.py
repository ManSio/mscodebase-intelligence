"""
Тесты для системы отслеживания прогресса индексации.
"""

import time
from unittest.mock import MagicMock, patch

import pytest


class TestProgressCallback:
    """Тесты для progress callback механизма."""

    def test_callback_updates_progress(self):
        """Callback обновляет _last_progress."""
        from src.mcp.server import _create_progress_callback, _last_progress, _progress_lock

        # Очищаем перед тестом
        with _progress_lock:
            _last_progress.clear()

        cb = _create_progress_callback("test_project")
        cb("file.py", 5, 10, "scanning")

        with _progress_lock:
            assert "test_project" in _last_progress
            assert _last_progress["test_project"]["files_done"] == 5
            assert _last_progress["test_project"]["files_total"] == 10
            assert _last_progress["test_project"]["percent"] == 50.0

    def test_callback_complete_phase(self):
        """Callback с phase=complete устанавливает 100%."""
        from src.mcp.server import _create_progress_callback, _last_progress, _progress_lock

        with _progress_lock:
            _last_progress.clear()

        cb = _create_progress_callback("test_project")
        cb("file.py", 10, 10, "complete")

        with _progress_lock:
            assert _last_progress["test_project"]["percent"] == 100.0
            assert _last_progress["test_project"]["phase"] == "complete"

    def test_callback_handles_zero_total(self):
        """Callback не падает при total=0."""
        from src.mcp.server import _create_progress_callback, _last_progress, _progress_lock

        with _progress_lock:
            _last_progress.clear()

        cb = _create_progress_callback("test_project")
        cb("file.py", 0, 0, "scanning")

        with _progress_lock:
            assert _last_progress["test_project"]["percent"] == 0.0

    def test_callback_error_does_not_crash(self):
        """Ошибка в callback не прерывает работу."""
        import src.mcp.server as server_module
        from src.mcp.server import _create_progress_callback

        # Подменяем _last_progress на объект который бросит ошибку
        # ВАЖНО: не удерживаем _progress_lock во время вызова callback — иначе deadlock!
        original = server_module._last_progress
        server_module._last_progress = None  # type: ignore

        try:
            cb = _create_progress_callback("test_project")
            # Не должно упасть — callback оборачивает в try/except
            cb("file.py", 1, 10, "scanning")
        finally:
            # Восстанавливаем
            server_module._last_progress = original

    def test_callback_tracks_timestamp(self):
        """Callback записывает timestamp."""
        from src.mcp.server import _create_progress_callback, _last_progress, _progress_lock

        with _progress_lock:
            _last_progress.clear()

        before = time.time()
        cb = _create_progress_callback("test_project")
        cb("file.py", 1, 10, "scanning")
        after = time.time()

        with _progress_lock:
            ts = _last_progress["test_project"]["timestamp"]
            assert before <= ts <= after


class TestCleanupOldProgress:
    """Тесты для очистки старых записей прогресса."""

    def test_cleanup_removes_expired_entries(self):
        """Записи старше 1 часа удаляются."""
        from src.mcp.server import _cleanup_old_progress, _last_progress, _progress_lock

        with _progress_lock:
            _last_progress.clear()
            _last_progress["old_project"] = {
                "phase": "complete",
                "files_done": 10,
                "files_total": 10,
                "percent": 100.0,
                "timestamp": time.time() - 7200,  # 2 часа назад
            }
            _last_progress["new_project"] = {
                "phase": "scanning",
                "files_done": 5,
                "files_total": 10,
                "percent": 50.0,
                "timestamp": time.time(),
            }

        _cleanup_old_progress()

        with _progress_lock:
            assert "old_project" not in _last_progress
            assert "new_project" in _last_progress

    def test_cleanup_keeps_recent_entries(self):
        """Свежие записи не удаляются."""
        from src.mcp.server import _cleanup_old_progress, _last_progress, _progress_lock

        with _progress_lock:
            _last_progress.clear()
            _last_progress["recent"] = {
                "phase": "complete",
                "files_done": 10,
                "files_total": 10,
                "percent": 100.0,
                "timestamp": time.time() - 300,  # 5 минут назад
            }

        _cleanup_old_progress()

        with _progress_lock:
            assert "recent" in _last_progress

    def test_cleanup_empty_progress(self):
        """Очистка не падает на пустом прогрессе."""
        from src.mcp.server import _cleanup_old_progress, _last_progress, _progress_lock

        with _progress_lock:
            _last_progress.clear()

        # Не должно упасть
        _cleanup_old_progress()

        with _progress_lock:
            assert len(_last_progress) == 0


class TestIndexerProgressCallback:
    """Тесты для progress callback в indexer."""

    def test_indexer_accepts_callback(self):
        """Indexer принимает progress_callback параметр."""
        from src.core.indexing.indexer import Indexer
        from pathlib import Path

        indexer = Indexer(
            Path("/tmp/test.db"),
            MagicMock(),
            MagicMock(),
            project_path=Path("/tmp")
        )

        # Проверяем что метод принимает callback
        import inspect
        sig = inspect.signature(indexer.index_project)
        assert "progress_callback" in sig.parameters

    def test_callback_is_optional(self):
        """progress_callback опциональный."""
        from src.core.indexing.indexer import Indexer
        from pathlib import Path

        indexer = Indexer(
            Path("/tmp/test.db"),
            MagicMock(),
            MagicMock(),
            project_path=Path("/tmp")
        )

        import inspect
        sig = inspect.signature(indexer.index_project)
        param = sig.parameters["progress_callback"]
        assert param.default is None


class TestProgressLockThreadSafety:
    """Тесты потокобезопасности."""

    def test_lock_protects_concurrent_access(self):
        """Lock защищает от concurrent access."""
        from src.mcp.server import _progress_lock, _last_progress

        errors = []

        def writer():
            try:
                for i in range(100):
                    with _progress_lock:
                        _last_progress["test"] = {"value": i}
            except Exception as e:
                errors.append(e)

        import threading
        threads = [threading.Thread(target=writer) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
