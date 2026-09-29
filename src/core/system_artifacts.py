"""
SystemArtifacts — единый модуль для идентификации системных файлов и директорий.

Определяет, какие файлы являются внутренними артефактами системы, а какие —
пользовательским кодом. Предотвращает feedback loop (индексирование собственных
описаний чанков) и защищает служебные данные от случайного попадания в индекс.

Архитектура (5 уровней защиты):
  Layer 1 — Directory Guard:   системные директории (.mscodebase/, .codebase_indices/)
  Layer 2 — Artifact Guard:    известные служебные файлы по имени/расширению
  Layer 3 — Feedback Guard:    файлы, созданные самим индексатором
  Layer 4 — Embedding Guard:   финальная проверка перед эмбеддингом
  Layer 5 — Measurement Hygiene: собственные замеры (probe/result JSON, experiments/**/results|work)

Использование:
    if SystemArtifacts.is_system_path(path):
        # не индексировать, не чанковать, не эмбеддить
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Set

__all__ = [
    "SystemArtifacts",
]
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# Layer 1: Directory Guard — системные директории
# ══════════════════════════════════════════════════════════════

_SYSTEM_DIRS: Set[str] = {
    # Основная системная директория (новый стандарт)
    ".mscodebase",
    # Старая системная директория (backward compat)
    ".codebase_indices",
    ".codebase_index",
    ".codebase_models",
    # IDE / build
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "__pycache__",
    "dist",
    "build",
    "target",
    ".tox",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "htmlcov",
    ".coverage",
    ".zed",
    ".idea",
    ".vscode",
    "out",
}

_SYSTEM_DIRS_LOWER: Set[str] = {d.lower() for d in _SYSTEM_DIRS}


# ══════════════════════════════════════════════════════════════
# Layer 2: Artifact Guard — известные служебные файлы
# ══════════════════════════════════════════════════════════════

_ARTIFACT_PATTERNS: Set[str] = {
    # Метаданные индексации (feedback loop guard)
    "chunk_summaries.json",
    "incidents.json",
    "project_memory.json",
    "commits.json",
    ".index_guard.json",
    # LanceDB / векторная БД
    "*.lance",
    "*.lance_versions",
    # Symbol index
    "symbol_index",
    # Cache
    "summaries_cache",
}


# ══════════════════════════════════════════════════════════════
# Layer 3: Feedback Guard — файлы, созданные самим индексатором
# ══════════════════════════════════════════════════════════════

_FEEDBACK_PATTERNS: Set[str] = {
    # Создаётся ChunkSummarizer при генерации LLM-описаний
    "chunk_summaries.json",
    # Метаданные проекта (ProjectMemory, BugCorrelation)
    "project_memory.json",
    "incidents.json",
    "commits.json",
    # Guard-файл состояния индекса
    ".index_guard.json",
}


# ══════════════════════════════════════════════════════════════
# Layer 5: Measurement Hygiene — собственные замеры вне индекса
# ══════════════════════════════════════════════════════════════
# Probe/result JSON-дампы содержат дословный текст запросов — попадая в
# индекс, они доминируют в BM25 и отравляют замеры (gate RED по вине
# измерительного стенда, а не кода). Тот же эффект у файлов под
# experiments/**/results и experiments/**/work.
_MEASUREMENT_RESULTS_DIRS: Set[str] = {
    "results",
    "work",
}

_MEASUREMENT_JSON_STEMS: Set[str] = {
    "probe",
    "result",
}


# ══════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════


class SystemArtifacts:
    """Единый источник правды о системных файлах проекта.

    Все guard-ы (FileGuard, FeedbackGuard, EmbeddingGuard) используют
    этот класс вместо разрозненных списков. Это гарантирует, что
    добавление нового системного файла не приведёт к появлению
    feedback loop в индексе.
    """

    @classmethod
    def get_system_dirs(cls) -> Set[str]:
        """Возвращает копию списка системных директорий."""
        return _SYSTEM_DIRS.copy()

    @classmethod
    def get_artifact_patterns(cls) -> Set[str]:
        """Возвращает копию списка паттернов артефактов."""
        return _ARTIFACT_PATTERNS.copy()

    @classmethod
    def get_feedback_patterns(cls) -> Set[str]:
        """Возвращает копию списка feedback-паттернов."""
        return _FEEDBACK_PATTERNS.copy()

    # ─── Layer 1: Directory Guard ───────────────────────────

    @classmethod
    def is_system_dir(cls, dir_name: str) -> bool:
        """Проверяет, является ли директория системной.

        Вызывается при обходе файловой системы: если директория
        системная — весь её subtree пропускается.
        """
        return dir_name.lower() in _SYSTEM_DIRS_LOWER

    @classmethod
    def is_in_system_dir(cls, path: Path) -> bool:
        """Проверяет, находится ли файл внутри системной директории.

        Проходит по всем parts пути: если хоть одна совпадает
        с системной директорией — файл считается системным.
        """
        return any(part.lower() in _SYSTEM_DIRS_LOWER for part in path.parts)

    # ─── Layer 2: Artifact Guard ────────────────────────────

    @classmethod
    def is_artifact(cls, path: Path) -> bool:
        """Проверяет, является ли файл известным артефактом системы.

        Два критерия:
        1. Файл находится в системной директории.
        2. Имя файла совпадает с известным паттерном артефакта.
        """
        name = path.name.lower()
        for pattern in _ARTIFACT_PATTERNS:
            if pattern.startswith("*."):
                # Wildcard по расширению
                if name.endswith(pattern[1:]):
                    return True
            elif name == pattern:
                return True
        return False

    @classmethod
    def is_artifact_by_name(cls, file_name: str) -> bool:
        """Проверяет имя файла (без пути) на совпадение с артефактами.

        Полезно для быстрой проверки в os.walk без создания Path.
        """
        name = file_name.lower()
        for pattern in _ARTIFACT_PATTERNS:
            if pattern.startswith("*."):
                if name.endswith(pattern[1:]):
                    return True
            elif name == pattern:
                return True
        return False

    # ─── Layer 3: Feedback Guard ────────────────────────────

    @classmethod
    def is_feedback_risk(cls, path: Path) -> bool:
        """Проверяет, является ли файл риском feedback loop.

        Такие файлы были созданы самим индексатором и содержат
        производные данные (описания чанков, метаданные памяти).
        Если их проиндексировать — качество RAG деградирует.
        """
        name = path.name.lower()
        return name in _FEEDBACK_PATTERNS

    # ─── Layer 5: Measurement Hygiene ───────────────────────

    @classmethod
    def is_measurement_artifact(cls, path: Path) -> bool:
        """Проверяет, является ли файл артефактом собственных замеров.

        Два критерия (достаточно одного):
        1. Файл лежит под ``experiments/**/results`` или ``experiments/**/work``
           (любое расширение — дампы, логи, скрипты прогонов).
        2. Имя — probe/result JSON-дамп (``*probe*.json``, ``*result*.json``,
           регистронезависимо) в любом месте дерева.

        Такие файлы содержат дословный текст проб-запросов и при индексации
        доминируют в BM25 — измерительный стенд отравляет измерение.
        """
        parts = [p.lower() for p in path.parts]
        if "experiments" in parts:
            tail = parts[parts.index("experiments") + 1:]
            if any(d in tail for d in _MEASUREMENT_RESULTS_DIRS):
                return True
        name = path.name.lower()
        if name.endswith(".json"):
            stem = name[:-len(".json")]
            if any(s in stem for s in _MEASUREMENT_JSON_STEMS):
                return True
        return False

    # ─── Unified Check ────────────────────────────────────────

    @classmethod
    def is_system_path(cls, path: Path) -> bool:
        """Единая проверка: является ли файл системным (финальный guard).

        Объединяет все уровни:
        1. Находится в системной директории (Directory Guard).
        2. Является известным артефактом (Artifact Guard).
        3. Создан индексатором (Feedback Guard).
        4. Артефакт собственных замеров (Measurement Hygiene).

        Returns:
            True — файл системный, не должен индексироваться.
        """
        if cls.is_in_system_dir(path):
            return True
        if cls.is_artifact(path):
            return True
        if cls.is_feedback_risk(path):
            return True
        if cls.is_measurement_artifact(path):
            return True
        return False
