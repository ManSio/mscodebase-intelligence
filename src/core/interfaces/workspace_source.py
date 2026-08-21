"""WorkspaceSource — интерфейс источника кода (ТЗ §2.1 Universal Engine).

Core объявляет интерфейс (как IEmbedder/IReranker); реализация живёт в
src/sources/ (LocalFsSource сейчас, GitUrlSource/UploadSource — Фаза 2).
Core не знает, что за источник — он получает локальный путь через resolve().
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class FileChangeEvent:
    """Событие изменения в workspace (единый формат для всех источников).

    kind:
        "modified" / "created" / "deleted" — файловое событие
        "fingerprint_changed" — весь workspace изменился (poll/remote-источники)
    """

    kind: str
    path: Optional[Path] = None
    fingerprint: Optional[str] = None


@runtime_checkable
class WorkspaceSource(Protocol):
    """Абстракция «откуда код»."""

    async def resolve(self) -> Path:
        """Локальный путь, готовый к индексации.

        Для git-URL — клонирует/обновляет кэш и возвращает путь к нему.
        Для local — нормализует путь (текущая SafePathManager-логика).
        """
        ...

    async def watch(self) -> AsyncIterator[FileChangeEvent]:
        """Единый интерфейс изменений: fs-watcher, webhook или poll."""
        ...

    def fingerprint(self) -> str:
        """Стабильный хеш дерева файлов (Merkle-стиль).

        Нужен для cold-start (пропуск переиндексации, ТЗ §2.2)
        и integrity-проверок.
        """
        ...
