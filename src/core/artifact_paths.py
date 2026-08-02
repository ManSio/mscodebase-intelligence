"""
ArtifactPaths — единая точка вычисления путей всех артефактов MCP (Задача 4/5).

Все артефакты (LanceDB-индекс, graph.db, project memory, метрики, телеметрия,
progress.json, summaries_cache) хранятся ВНЕ пользовательского проекта — в
системной папке пользователя, с per-project изоляцией через хэш пути.

Зачем:
    «Артефакты внутри чужого проекта делают систему непригодной для работы
    с чужим кодом» (аудит владельца). Индексируя чужой репозиторий, MCP
    больше не пишет в него .codebase_indices/ и .codebase/graph.db.

Расположение (data root):
    Windows: %LOCALAPPDATA%/mscodebase
    macOS:   ~/Library/Caches/mscodebase
    Linux:   $XDG_CACHE_HOME/mscodebase | ~/.cache/mscodebase

Переопределение:
    MSCODEBASE_DATA_DIR=<абсолютный путь> — явный корень данных.
    BASE_INDEX_DIR=<абсолютный путь>     — legacy-аналог (уважается для
                                            обратной совместимости).

Per-project изоляция:
    <data_root>/projects/<hash8>/  где hash8 = md5(нормализованный путь)[:8].
    Хэш детерминированный и совпадает с тем, что раньше использовал
    `_generate_unique_db_path` — существующие данные переносятся без потерь.

Миграция:
    При первом создании <data_root>/projects/<hash8>/ модуль best-effort
    переносит legacy-артефакты из проекта: .codebase_indices/{lancedb_v2,
    intelligence, metrics, commit_memory, branches, summaries_cache, logs},
    .codebase/graph.db (+ -wal/-shm) и .mscodebase/telemetry. Перенос
    идемпотентен и безопасен: каждый элемент независим, при ошибке
    (например, файлы залочены mmap другого окна Zed) — пропускается с
    warning в отчёте, новая БД просто создастся с нуля.

Usage:
    from src.core.artifact_paths import get_db_path, get_graph_db_path
    db_path = get_db_path(project_path)
    graph_db = get_graph_db_path(project_path)
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
from pathlib import Path
from typing import Dict, List

from src.core.platform_utils import is_windows

__all__ = [
    "get_data_root",
    "project_hash",
    "get_project_dir",
    "get_index_dir",
    "get_db_path",
    "get_graph_db_path",
    "get_intelligence_dir",
    "get_metrics_dir",
    "get_commit_memory_dir",
    "get_branches_dir",
    "get_telemetry_dir",
    "get_progress_file",
    "get_summaries_cache_dir",
    "legacy_project_dirs",
    "migrate_legacy_artifacts",
]
logger = logging.getLogger("mscodebase_server.artifacts")

# Legacy-поддиректории внутри .codebase_indices/, которые переносятся в проектную папку.
_LEGACY_INDEX_SUBDIRS: tuple = (
    "lancedb_v2",
    "intelligence",
    "metrics",
    "commit_memory",
    "branches",
    "summaries_cache",
    "logs",
)


# ══════════════════════════════════════════════════════════════
# Data root
# ══════════════════════════════════════════════════════════════


def get_data_root() -> Path:
    """Возвращает корень хранения артефактов MCP (создаёт при отсутствии).

    Приоритет:
    1. MSCODEBASE_DATA_DIR (абсолютный путь) — явный override.
    2. BASE_INDEX_DIR (абсолютный) — legacy override для обратной совместимости.
    3. Платформенный default: %LOCALAPPDATA%/mscodebase | ~/.cache/mscodebase.
    """
    env = os.getenv("MSCODEBASE_DATA_DIR", "").strip()
    if env:
        root = Path(env).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        return root

    legacy = os.getenv("BASE_INDEX_DIR", "").strip()
    if legacy and Path(legacy).is_absolute():
        root = Path(legacy).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        return root

    if is_windows():
        base = Path(os.environ.get("LOCALAPPDATA", "")) / "mscodebase"
    else:
        xdg = os.environ.get("XDG_CACHE_HOME", "").strip()
        if xdg:
            base = Path(xdg) / "mscodebase"
        else:
            base = Path.home() / ".cache" / "mscodebase"
    base.mkdir(parents=True, exist_ok=True)
    return base


def project_hash(project_path: Path) -> str:
    """Детерминированный хэш проекта (md5 нормализованного пути, 8 символов).

    Совпадает с hash'ем из исторического `_generate_unique_db_path` —
    миграция данных между старым и новым расположением не требует
    переиндексации.
    """
    normalized = str(project_path.resolve()).lower().replace("\\", "/")
    return hashlib.md5(normalized.encode()).hexdigest()[:8]


# ══════════════════════════════════════════════════════════════
# Per-project директория
# ══════════════════════════════════════════════════════════════


def _compute_project_dir(project_path: Path) -> Path:
    """Чистый расчёт проектной папки (без mkdir/миграции)."""
    return get_data_root() / "projects" / project_hash(project_path)


def get_project_dir(project_path: Path) -> Path:
    """Возвращает проектную папку артефактов (создаёт при отсутствии).

    При ПЕРВОМ создании папки выполняется best-effort миграция legacy-
    артефактов из проекта (см. migrate_legacy_artifacts). Повторные вызовы
    идемпотентны.
    """
    d = _compute_project_dir(project_path)
    if not d.exists():
        d.mkdir(parents=True, exist_ok=True)
        _migrate_into(d, project_path)
    elif not d.is_dir():
        raise NotADirectoryError(
            f"Артефакт-папка {d} существует, но это не директория. "
            f"Удалите её и перезапустите MCP."
        )
    return d


# ══════════════════════════════════════════════════════════════
# Геттеры путей
# ══════════════════════════════════════════════════════════════


def get_index_dir(project_path: Path) -> Path:
    """Директория LanceDB-индекса (lancedb_v2) в системной папке."""
    d = get_project_dir(project_path) / "lancedb_v2"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_db_path(project_path: Path) -> Path:
    """Путь к LanceDB-базе проекта (эквивалент исторического _generate_unique_db_path)."""
    project_name = os.path.basename(project_path).lower()
    return get_index_dir(project_path) / f"index_{project_name}_{project_hash(project_path)}.db"


def get_graph_db_path(project_path: Path) -> Path:
    """Путь к PropertyGraph (SQLite) — вне проекта."""
    return get_project_dir(project_path) / "graph.db"


def get_intelligence_dir(project_path: Path) -> Path:
    """Project Memory / Incident History (JSON)."""
    d = get_project_dir(project_path) / "intelligence"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_metrics_dir(project_path: Path) -> Path:
    """Метрики индексации (job_history.json для адаптивного ETA)."""
    d = get_project_dir(project_path) / "metrics"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_commit_memory_dir(project_path: Path) -> Path:
    """Кэш семантической памяти коммитов."""
    d = get_project_dir(project_path) / "commit_memory"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_branches_dir(project_path: Path) -> Path:
    """Индексы git-веток (BranchAwareIndex)."""
    d = get_project_dir(project_path) / "branches"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_telemetry_dir(project_path: Path) -> Path:
    """Телеметрия (ежедневные JSON-снэпшоты)."""
    d = get_project_dir(project_path) / "telemetry"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_progress_file(project_path: Path) -> Path:
    """progress.json — file-contract для агента (см. AGENTS.md §0)."""
    return get_project_dir(project_path) / "progress.json"


def get_summaries_cache_dir(project_path: Path) -> Path:
    """Кэш LLM-описаний чанков (ChunkSummarizer)."""
    d = get_project_dir(project_path) / "summaries_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ══════════════════════════════════════════════════════════════
# Миграция legacy-артефактов
# ══════════════════════════════════════════════════════════════


def legacy_project_dirs(project_path: Path) -> List[Path]:
    """Возвращает legacy-директории артефактов внутри проекта (если существуют)."""
    result: List[Path] = []
    old_index = project_path / ".codebase_indices"
    if old_index.exists():
        result.append(old_index)
    old_codebase = project_path / ".codebase"
    if old_codebase.exists():
        result.append(old_codebase)
    old_mscodebase = project_path / ".mscodebase"
    if old_mscodebase.exists():
        result.append(old_mscodebase)
    return result


def _migrate_into(new_dir: Path, project_path: Path) -> Dict[str, str]:
    """Best-effort перенос legacy-артефактов из проекта в new_dir.

    Каждый элемент независим: ошибка (например, mmap-лок другого окна Zed)
    не прерывает остальные. Идемпотентно: переносится только то, чего нет
    в new_dir.
    """
    report: Dict[str, str] = {}

    old_index = project_path / ".codebase_indices"
    for sub in _LEGACY_INDEX_SUBDIRS:
        src = old_index / sub
        dst = new_dir / sub
        if src.exists() and not dst.exists():
            try:
                shutil.move(str(src), str(dst))
                report[f".codebase_indices/{sub}"] = str(dst)
            except Exception as _e:  # noqa: BLE001 — best-effort миграция
                logger.warning(
                    f"Artifact migration SKIPPED .codebase_indices/{sub}: {_e}"
                )
                report[f".codebase_indices/{sub}"] = f"SKIPPED: {_e}"

    old_codebase = project_path / ".codebase"
    for suffix in ("graph.db", "graph.db-wal", "graph.db-shm"):
        src = old_codebase / suffix
        dst = new_dir / suffix
        if src.exists() and not dst.exists():
            try:
                shutil.move(str(src), str(dst))
                report[f".codebase/{suffix}"] = str(dst)
            except Exception as _e:  # noqa: BLE001
                logger.warning(f"Artifact migration SKIPPED .codebase/{suffix}: {_e}")
                report[f".codebase/{suffix}"] = f"SKIPPED: {_e}"

    old_telemetry = project_path / ".mscodebase" / "telemetry"
    if old_telemetry.exists() and not (new_dir / "telemetry").exists():
        try:
            shutil.move(str(old_telemetry), str(new_dir / "telemetry"))
            report[".mscodebase/telemetry"] = str(new_dir / "telemetry")
        except Exception as _e:  # noqa: BLE001
            logger.warning(f"Artifact migration SKIPPED .mscodebase/telemetry: {_e}")
            report[".mscodebase/telemetry"] = f"SKIPPED: {_e}"

    if report:
        logger.info(f"Artifact migration for {project_path}: {report}")
    return report


def migrate_legacy_artifacts(project_path: Path) -> Dict[str, str]:
    """Явный запуск миграции legacy-артефактов проекта в системную папку.

    Обычно вызывать не нужно — get_project_dir() мигрирует при первом
    создании папки. Нужен для тестов и явных вызовов из стартовых путей.
    """
    new_dir = _compute_project_dir(project_path)
    new_dir.mkdir(parents=True, exist_ok=True)
    return _migrate_into(new_dir, project_path)
