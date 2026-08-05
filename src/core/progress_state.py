"""
ProgressState — потокобезопасное состояние прогресса индексации (ARCH-03 follow-up).

Перенесено из src/mcp/server.py (v3.3.12): core-слой больше не импортирует
mcp-слой для чтения прогресса. mcp/server.py реэкспортирует имена для
обратной совместимости (тесты, скрипты).

Замечание (открытая нить): _create_progress_callback в проде не вызывается
(index_project получает собственный callback из intelligence/layer.py),
поэтому _last_progress в рантайме обычно пуст. get_last_progress() при этом
остаётся thread-safe accessor'ом для диагностики и job-статистики.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("mscodebase_server.progress_state")

_last_progress: Dict[str, Any] = {}
_progress_lock = threading.Lock()
_progress_updates = 0  # счётчик обновлений для периодического cleanup (Item 4)


def get_last_progress() -> Dict[str, Any]:
    """Thread-safe accessor for progress tracking (used by core.intelligence)."""
    with _progress_lock:
        return dict(_last_progress)


def _create_progress_callback(project_name: str) -> Callable:
    """Создаёт callback для отслеживания прогресса индексации.

    Возвращает callable который обновляет внутренний счётчик прогресса
    и логирует каждые 10 файлов. Потокобезопасен через _progress_lock.
    """

    def progress_callback(file_name: str, done: int, total: int, phase: str):
        global _progress_updates
        try:
            now = time.time()
            with _progress_lock:
                existing = _last_progress.get(project_name, {})
                if "started_at" not in existing or existing.get("phase") == "complete":
                    started_at = now
                else:
                    started_at = existing["started_at"]

            progress_info = {
                "project": project_name,
                "phase": phase,
                "files_done": done,
                "files_total": total,
                "current_file": file_name,
                "percent": (done / total * 100) if total > 0 else 0,
                "timestamp": now,
                "started_at": started_at,
            }
            with _progress_lock:
                _last_progress[project_name] = progress_info
                # Periodic cleanup: раз в 100 обновлений, не на каждом —
                # иначе O(n) на каждый update при >10 активных проектах
                _progress_updates += 1
                if _progress_updates % 100 == 0 and len(_last_progress) > 10:
                    _cleanup_old_progress()

            if done % 10 == 0 or phase in (
                "complete",
                "rebuilding_bm25",
                "error_security",
            ):
                logger.info(
                    f"📊 Progress [{project_name}]: "
                    f"{done}/{total} ({progress_info['percent']:.0f}%) — {phase}"
                )
        except Exception as _e:
            logger.warning(f"Progress callback failed: {_e}")
    return progress_callback


def _cleanup_old_progress():
    """Удаляет записи прогресса старше 1 часа (защита от memory leak)."""
    now = time.time()
    expired = [
        k for k, v in _last_progress.items() if now - v.get("timestamp", 0) > 3600
    ]
    for k in expired:
        del _last_progress[k]
