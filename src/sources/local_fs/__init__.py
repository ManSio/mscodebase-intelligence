"""LocalFsSource — источник кода из локальной файловой системы (Фаза 1, ТЗ §2.1).

Владеет локальной обработкой путей (SafePathManager / to_win_long_path —
деталь ЭТОГО класса, не всего core). Поведение идентично текущей логике:
resolve() возвращает нормализованный project_root без новых эффектов.

watch() — poll по fingerprint (Фаза-1 реализация интерфейса; Фаза 2 подключает
реальный watcher/webhook). fingerprint() — pure-Python Merkle-манифест
(O(files)); Фаза 2 заменяет на git-tree O(1) (E-02: 79ms, ноль re-hash) там,
где workspace — git-репозиторий.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import AsyncIterator, Optional

from src.core.interfaces.workspace_source import FileChangeEvent, WorkspaceSource
from src.sources.local_fs.windows import SafePathManager


def _skip_entry(rel: str) -> bool:
    """Эвристика исключений fingerprint: первый компонент с точкой
    (.git, .venv, __pycache__, ...) и известные тяжёлые каталоги."""
    first = rel.split("/", 1)[0]
    if first.startswith("."):
        return True
    if first in ("venv", "node_modules", "__pycache__"):
        return True
    return False


class LocalFsSource:
    """Локальный файловый источник (реализация WorkspaceSource)."""

    def __init__(self, project_root: Path, path_manager: Optional[SafePathManager] = None):
        self._project_root = Path(project_root)
        self.path_manager = path_manager or SafePathManager(self._project_root)

    # ── WorkspaceSource ──────────────────────────────────────────────

    async def resolve(self) -> Path:
        """Нормализованный локальный путь (без смены поведения)."""
        return self._project_root.resolve()

    async def watch(self, interval_seconds: float = 30.0) -> AsyncIterator[FileChangeEvent]:
        """Poll-наблюдатель: событие при смене fingerprint workspace.

        Фаза-1 реализация единого интерфейса watch(): детерминирована,
        тестируема, без внешних зависимостей. Фаза 2: fs-watcher/webhook.
        """
        last = self.fingerprint()
        while True:
            await asyncio.sleep(interval_seconds)
            current = self.fingerprint()
            if current != last:
                yield FileChangeEvent(
                    kind="fingerprint_changed",
                    path=None,
                    fingerprint=current,
                )
                last = current

    def fingerprint(self) -> str:
        """Merkle-манифест дерева: sha256 над отсортированными (rel_path, file_hash)."""
        h = hashlib.sha256()
        entries: list[tuple[str, str]] = []
        root = self._project_root.resolve()
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            if _skip_entry(rel):
                continue
            digest = self._sha256_file(p)
            entries.append((rel, digest))
        for rel, digest in entries:
            h.update(rel.encode("utf-8"))
            h.update(b"\x00")
            h.update(digest.encode("ascii"))
        return h.hexdigest()

    @staticmethod
    def _sha256_file(path: Path) -> str:
        """Потоковый sha256 без загрузки файла в память."""
        h = hashlib.sha256()
        try:
            with open(path, "rb") as f:
                for block in iter(lambda: f.read(65536), b""):
                    h.update(block)
        except OSError:
            return ""
        return h.hexdigest()
