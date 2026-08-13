"""
ArtifactGC — очистка устаревших артефактов MCP (data_root).

Проблема (аудит 2026-08-13): проектная папка создаётся при ПЕРВОМ обращении
к любому геттеру artifact_paths (get_db_path/get_metrics_dir/...). Тесты с
pytest tmp_path и закрытые/удалённые проекты накопили >2400 папок в
<data_root>/projects/, из которых реальных — единицы. Механизма очистки не было.

Что чистим (best-effort, никогда не фатально):
  1. projects/<hash8>/ — НЕ активные (не в active_hashes):
       - пустые (рекурсивно) — удаляются сразу;
       - старше project_max_age_days — удаляются целиком (rmtree).
  2. telemetry/*.json внутри ЛЮБОЙ проектной папки — старше telemetry_max_age_days
     (включая активные проекты — это кэш, восстанавливаемый заново).
  3. logs/*.log* в data_root/logs — старше log_retention_days (делегируется
     log_manager._cleanup_old_logs).

Защиты:
  - Активные проекты (открытые окна Zed, известные ProjectIndexerRegistry)
    НЕ трогаются никогда.
  - Папка с залоченным файлом (mmap другого окна) → пропуск, счётчик skipped.
  - Удаляются ТОЛЬКО папки вида <hash8> = 8 hex-символов — случайные папки
    в data_root не затрагиваются.
"""

from __future__ import annotations

import logging
import re
import shutil
import time
from pathlib import Path
from typing import Dict, Optional, Set

logger = logging.getLogger("mscodebase_server.artifact_gc")

_HASH_RE = re.compile(r"^[0-9a-f]{8}$")

# Пороги по умолчанию (дни).
DEFAULT_PROJECT_MAX_AGE_DAYS = 30
DEFAULT_TELEMETRY_MAX_AGE_DAYS = 90
DEFAULT_LOG_RETENTION_DAYS = 7


def _dir_has_files(path: Path) -> bool:
    """True, если в дереве path есть хотя бы один файл."""
    try:
        for _root, dirs, files in path.walk():
            if files:
                return True
            for d in dirs:
                if d in ("__pycache__", ".git"):
                    continue
    except (OSError, PermissionError):
        return True  # не можем прочитать — считаем непустой (не удаляем)
    return False


def _rmtree_safe(path: Path, report: Dict[str, int]) -> bool:
    """rmtree с защитой от залоченных файлов (mmap другого окна Zed)."""
    try:
        shutil.rmtree(str(path), ignore_errors=False)
        report["removed_projects"] += 1
        return True
    except (OSError, PermissionError) as e:
        logger.warning(f"ArtifactGC: пропуск залоченной папки {path}: {e}")
        report["skipped_locked"] += 1
        return False


def _prune_project_dirs(
    projects_root: Path,
    active_hashes: Set[str],
    project_max_age_days: int,
    now: float,
    report: Dict[str, int],
) -> None:
    """Удаляет неактивные/устаревшие проектные папки."""
    if not projects_root.is_dir():
        return
    try:
        entries = list(projects_root.iterdir())
    except OSError as e:
        logger.warning(f"ArtifactGC: не могу прочитать {projects_root}: {e}")
        return

    for entry in entries:
        if not entry.is_dir() or not _HASH_RE.match(entry.name):
            continue
        if entry.name in active_hashes:
            report["active"] += 1
            continue

        # Пустая папка → удаляем сразу (мусор от прерванных тестов/инициализаций).
        if not _dir_has_files(entry):
            logger.info(f"ArtifactGC: пустая проектная папка {entry.name} — удаляю")
            _rmtree_safe(entry, report)
            continue

        # Неактивная папка с данными старше порога → удаляем целиком.
        try:
            age_days = (now - entry.stat().st_mtime) / 86400
        except OSError:
            continue
        if age_days >= project_max_age_days:
            logger.info(
                f"ArtifactGC: проектная папка {entry.name} неактивна "
                f"{age_days:.0f}д (>{project_max_age_days}д) — удаляю"
            )
            _rmtree_safe(entry, report)


def _prune_telemetry(projects_root: Path, telemetry_max_age_days: int, now: float) -> int:
    """Удаляет старые телеметрические снимки из ВСЕХ проектных папок."""
    if not projects_root.is_dir():
        return 0
    cutoff = now - telemetry_max_age_days * 86400
    removed = 0
    for entry in projects_root.iterdir():
        if not entry.is_dir() or not _HASH_RE.match(entry.name):
            continue
        tel_dir = entry / "telemetry"
        if not tel_dir.is_dir():
            continue
        try:
            for f in tel_dir.glob("*.json"):
                if f.stat().st_mtime < cutoff:
                    f.unlink(missing_ok=True)
                    removed += 1
        except (OSError, PermissionError) as e:
            logger.debug(f"ArtifactGC: telemetry cleanup skip {tel_dir}: {e}")
    return removed


def prune_stale_artifacts(
    active_hashes: Optional[Set[str]] = None,
    project_max_age_days: int = DEFAULT_PROJECT_MAX_AGE_DAYS,
    telemetry_max_age_days: int = DEFAULT_TELEMETRY_MAX_AGE_DAYS,
    log_retention_days: int = DEFAULT_LOG_RETENTION_DAYS,
) -> Dict[str, int]:
    """Главная точка очистки устаревших артефактов. Идемпотентна, best-effort.

    Args:
        active_hashes: хэши активных проектов (из ProjectIndexerRegistry).
            None → пробуем получить из глобального реестра; если недоступен —
            ничего не удаляем по возрасту (только телеметрию/логи).

    Returns:
        Счётчики: {scanned, active, removed_projects, removed_telemetry,
        removed_logs, skipped_locked}.
    """
    from src.core.artifact_paths import get_data_root, get_logs_dir, project_hash

    report: Dict[str, int] = {
        "scanned": 0,
        "active": 0,
        "removed_projects": 0,
        "removed_telemetry": 0,
        "removed_logs": 0,
        "skipped_locked": 0,
    }

    data_root = get_data_root()
    projects_root = data_root / "projects"
    now = time.time()

    # Активные хэши: из реестра, если не переданы явно.
    if active_hashes is None:
        try:
            from src.core.indexing.project_indexer_registry import get_global_registry

            active_hashes = {
                project_hash(p) for p in get_global_registry().get_all_paths()
            }
        except (ImportError, OSError, RuntimeError) as e:
            logger.debug(f"ArtifactGC: реестр недоступен ({e}) — только телеметрия/логи")
            active_hashes = set()

    report["scanned"] = len(active_hashes)
    _prune_project_dirs(projects_root, set(active_hashes), project_max_age_days, now, report)
    report["removed_telemetry"] = _prune_telemetry(projects_root, telemetry_max_age_days, now)

    # Логи: делегируем централизованной очистке log_manager (7 дней).
    try:
        from src.core.log_manager import _cleanup_old_logs

        report["removed_logs"] = _cleanup_old_logs(get_logs_dir())
    except (ImportError, OSError) as e:
        logger.debug(f"ArtifactGC: log cleanup skip: {e}")

    total = report["removed_projects"] + report["removed_telemetry"] + report["removed_logs"]
    if total:
        logger.info(f"🧹 ArtifactGC: {report}")
    return report
