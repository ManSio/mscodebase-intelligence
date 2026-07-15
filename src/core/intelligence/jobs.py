"""
MSCodeBase Intelligence Jobs — Фоновые задачи для MCP-инструментов

Содержит:
- BackgroundJob — датакласс фоновой задачи
- JobManager — управление жизненным циклом фоновых задач
- job_manager — глобальный экземпляр JobManager
"""

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger("MSCodeBase.Intelligence.Jobs")


# =====================================================================
# ДАТАКЛАСС ФОНОВОЙ ЗАДАЧИ
# =====================================================================


@dataclass
class BackgroundJob:
    """Фоновая задача с отслеживанием прогресса."""

    job_id: str
    type: str
    status: str  # "pending", "running", "completed", "failed"
    progress: float
    started_at: float
    ended_at: Optional[float] = None
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    project_size: Optional[int] = None  # кол-во файлов (для ETA-истории)


# =====================================================================
# МЕНЕДЖЕР ЗАДАЧ
# =====================================================================


class JobManager:
    """Управляет тяжелыми фоновыми задачами для предотвращения таймаутов Zed.

    Использует двухфазную схему:
    1. Запуск задачи — возвращает job_id мгновенно
    2. Опрос статуса — agent Zed периодически проверяет прогресс
    """

    def __init__(self):
        self.jobs: Dict[str, BackgroundJob] = {}

    def create_job(self, job_type: str) -> str:
        """Создаёт новую фоновую задачу."""
        job_id = str(uuid.uuid4())[:8]
        self.jobs[job_id] = BackgroundJob(
            job_id=job_id,
            type=job_type,
            status="pending",
            progress=0.0,
            started_at=time.time(),
        )
        logger.debug(f"Создана фоновая задача {job_id}: {job_type}")
        return job_id

    def get_job(self, job_id: str) -> Optional[BackgroundJob]:
        """Возвращает задачу по ID."""
        return self.jobs.get(job_id)

    def cleanup_old_jobs(self, max_age_seconds: int = 3600):
        """Удаляет старые завершённые задачи (защита от memory leak)."""
        now = time.time()
        to_remove = [
            jid
            for jid, job in self.jobs.items()
            if job.status in ("completed", "failed")
            and now - job.started_at > max_age_seconds
        ]
        for jid in to_remove:
            del self.jobs[jid]

        if to_remove:
            logger.debug(f"Удалено {len(to_remove)} старых задач")


# Глобальный менеджер задач
job_manager = JobManager()
