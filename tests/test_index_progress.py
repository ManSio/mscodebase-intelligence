"""
Тесты для системы отслеживания прогресса индексации.

Прогресс индексации в проде идёт через JobManager (src/core/intelligence/jobs.py):
- intel_trigger_reindex → layer.trigger_async_reindex → job.progress
- ProjectContext._capture_jobs агрегирует статусы задач в снэпшот.

Легаси-механизм src/core/progress_state.py (_create_progress_callback,
_last_progress) удалён — был dead code: в проде не вызывался, питал только
_get_last_progress() → всегда пустой счётчик jobs в intel_get_project_context.
Единый источник правды теперь — job_manager.
"""

import inspect
import time
from pathlib import Path
from unittest.mock import MagicMock

from src.core.intelligence.jobs import JobManager


class TestIndexerProgressCallback:
    """Тесты для progress callback в indexer (прод-контракт: index_project принимает callback)."""

    def test_indexer_accepts_callback(self):
        """Indexer принимает progress_callback параметр."""
        from src.core.indexing.indexer import Indexer

        indexer = Indexer(
            Path("/tmp/test.db"),
            MagicMock(),
            MagicMock(),
            project_path=Path("/tmp"),
        )

        # Проверяем что метод принимает callback
        sig = inspect.signature(indexer.index_project)
        assert "progress_callback" in sig.parameters

    def test_callback_is_optional(self):
        """progress_callback опциональный."""
        from src.core.indexing.indexer import Indexer

        # Check signature without instantiating (avoids DB locks)
        sig = inspect.signature(Indexer.index_project)
        param = sig.parameters["progress_callback"]
        assert param.default is None


class TestJobManager:
    """JobManager — единый источник прогресса фоновых задач."""

    def test_create_job_tracks_lifecycle(self):
        """create_job → pending, get_job возвращает задачу."""
        m = JobManager()
        job_id = m.create_job("full_reindex")

        job = m.get_job(job_id)

        assert job is not None
        assert job.status == "pending"
        assert job.progress == 0.0

    def test_list_jobs_returns_snapshot(self):
        """list_jobs возвращает копию списка задач (мутация снаружи безопасна)."""
        m = JobManager()
        m.create_job("full_reindex")
        m.create_job("full_reindex")

        jobs = m.list_jobs()
        assert len(jobs) == 2

        # Снимок: очистка полученного списка не трогает manager
        jobs.clear()
        assert len(m.list_jobs()) == 2

    def test_cleanup_removes_expired_terminal_jobs(self):
        """Завершённые задачи старше 1 часа удаляются (ленивый cleanup на чтении)."""
        m = JobManager()
        job_id = m.create_job("full_reindex")
        job = m.get_job(job_id)
        job.status = "completed"
        job.started_at = time.time() - 7200  # 2 часа назад

        m.list_jobs()

        assert m.get_job(job_id) is None

    def test_cleanup_keeps_running_jobs(self):
        """Активная задача не удаляется, даже если старше 1 часа."""
        m = JobManager()
        job_id = m.create_job("full_reindex")
        m.get_job(job_id).started_at = time.time() - 7200

        m.list_jobs()

        assert m.get_job(job_id) is not None

    def test_cleanup_keeps_recent_terminal_jobs(self):
        """Свежая завершённая задача не удаляется."""
        m = JobManager()
        job_id = m.create_job("full_reindex")
        m.get_job(job_id).status = "completed"

        m.list_jobs()

        assert m.get_job(job_id) is not None


class TestCaptureJobs:
    """ProjectContext._capture_jobs агрегирует статусы из job_manager."""

    def _capture(self, manager, monkeypatch):
        from src.core.intelligence.project_context import (
            ProjectContext,
            ProjectContextSnapshot,
        )

        monkeypatch.setattr("src.core.intelligence.jobs.job_manager", manager)

        return ProjectContext(Path("/tmp"), MagicMock())._capture_jobs(
            ProjectContextSnapshot(project_path="/tmp", project_name="test")
        )

    def test_counts_running_completed_failed(self, monkeypatch):
        """pending/running → running; completed → completed; failed → failed."""
        m = JobManager()
        r_id = m.create_job("full_reindex")
        m.get_job(r_id).status = "running"
        m.create_job("full_reindex")  # pending — тоже running
        c_id = m.create_job("full_reindex")
        m.get_job(c_id).status = "completed"
        f_id = m.create_job("full_reindex")
        m.get_job(f_id).status = "failed"

        snap = self._capture(m, monkeypatch)

        assert snap.jobs_running == 2
        assert snap.jobs_completed == 1
        assert snap.jobs_failed == 1

    def test_empty_jobs_defaults(self, monkeypatch):
        """Пустой manager → все счётчики 0, не падает."""
        snap = self._capture(JobManager(), monkeypatch)

        assert snap.jobs_running == 0
        assert snap.jobs_completed == 0
        assert snap.jobs_failed == 0
