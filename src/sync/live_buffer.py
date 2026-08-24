"""LiveBuffer — RAM-оверлей несохранённых изменений редактора.

Хранит актуальное содержимое файла в оперативной памяти демона, пока
пользователь НЕ сохранил файл на диск. При чтении (`read_live_file`) и поиске
оверлей имеет приоритет над диском → агент/ИИ видит «живой» текст мгновенно,
даже если файл на диске ещё старый.

Гарантии (Red Team §1.16 / §2.3 / §5.13):
- Потокобезопасность: все мутации под threading.Lock.
- Монотонная версия: применяется только change с version >= последней
  (last-writer-wins), чтобы внеочередные WS-сообщения не затирали свежее.
- НИКОГДА не пишет на диск (асинхронный flush_to_disk намеренно отсутствует).
- LRU-кап + TTL-сборка мусора, чтобы забытые несохранённые буферы не текли.
- Ключ — абсолютный нормализованный путь файла (кросс-IDE: VS Code/Cursor/Zed
  редактируют один и тот же физический файл → делят один оверлей).
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger("mscodebase_server.live_buffer")

# Лимиты (можно переопределить через env для тюнинга).
_DEFAULT_MAX_ENTRIES = 4000
_DEFAULT_TTL_SECONDS = 1800  # 30 мин простоя → сброс (файл «забыт»)


@dataclass
class _LiveEntry:
    content: str
    version: int
    updated_at: float = field(default_factory=time.time)
    # Порядок для LRU-вытеснения (чем больше, тем свежее).
    seq: int = 0


class LiveBuffer:
    """Потокобезопасный RAM-оверлей несохранённых изменений.

    Методы дизайна:
    - update(): только last-writer-wins по version (равная version — обновляет,
      чтобы ре-синк после реконнекта был идемпотентным).
    - get(): возвращает живой контент или None (тогда читаем с диска).
    - drop(): удаляет запись (при save — диск теперь авторитетен; при close —
      несохранённое содержимое потеряно, держать незачем).
    """

    def __init__(
        self,
        max_entries: int = _DEFAULT_MAX_ENTRIES,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
    ) -> None:
        self._max_entries = max(1, max_entries)
        self._ttl_seconds = max(1, ttl_seconds)
        self._entries: Dict[str, _LiveEntry] = {}
        self._lock = threading.RLock()
        self._seq = 0

    # ─── Публичный API ─────────────────────────────────────────────
    def update(self, abs_path: str, content: str, version: int) -> bool:
        """Применяет изменение из редактора.

        Returns:
            True — применено (свежая/равная версия); False — отклонено (старая
            версия пришла позже свежей, гонка вне очереди).
        """
        key = self._norm(abs_path)
        with self._lock:
            existing = self._entries.get(key)
            if existing is not None and version < existing.version:
                # Пришла старая версия после свежей — игнорируем (last-writer-wins).
                logger.debug(
                    f"LiveBuffer.update DROP (stale): {key} "
                    f"incoming v{version} < stored v{existing.version}"
                )
                return False
            self._seq += 1
            self._entries[key] = _LiveEntry(
                content=content, version=version, seq=self._seq
            )
            # LRU-кап: вытесняем самые старые по seq.
            if len(self._entries) > self._max_entries:
                self._evict_locked()
            return True

    def get(self, abs_path: str) -> Optional[str]:
        """Возвращает живой контент или None (читать с диска)."""
        key = self._norm(abs_path)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            # Touch для LRU (свежий доступ — не вытеснять).
            self._seq += 1
            entry.seq = self._seq
            entry.updated_at = time.time()
            return entry.content

    def get_version(self, abs_path: str) -> Optional[int]:
        key = self._norm(abs_path)
        with self._lock:
            entry = self._entries.get(key)
            return entry.version if entry is not None else None

    def drop(self, abs_path: str) -> bool:
        """Удаляет оверлей (save → диск авторитетен; close → потеряно)."""
        key = self._norm(abs_path)
        with self._lock:
            return self._entries.pop(key, None) is not None

    def keys(self):
        with self._lock:
            return list(self._entries.keys())

    def sweep(self) -> int:
        """Удаляет просроченные по TTL записи. Возвращает число удалённых."""
        now = time.time()
        removed = 0
        with self._lock:
            stale = [
                k
                for k, e in self._entries.items()
                if now - e.updated_at > self._ttl_seconds
            ]
            for k in stale:
                del self._entries[k]
                removed += 1
        if removed:
            logger.info(f"LiveBuffer.sweep: dropped {removed} stale entries")
        return removed

    def stats(self) -> dict:
        with self._lock:
            return {
                "entries": len(self._entries),
                "max_entries": self._max_entries,
                "ttl_seconds": self._ttl_seconds,
            }

    # ─── Внутреннее ───────────────────────────────────────────────
    @staticmethod
    def _norm(abs_path: str) -> str:
        try:
            return str(Path(abs_path).resolve())
        except Exception:  # noqa: BLE001 - нормализация, фолбэк на сырой путь
            return abs_path.replace("\\", "/")

    def _evict_locked(self) -> None:
        """Вытесняет самую старую (по seq) запись. Требует self._lock."""
        if not self._entries:
            return
        oldest_key = min(self._entries, key=lambda k: self._entries[k].seq)
        del self._entries[oldest_key]


# ─── Singleton accessor (один оверлей на процесс-демон) ───────────────
_BUFFER: Optional[LiveBuffer] = None
_BUFFER_LOCK = threading.Lock()


def get_live_buffer() -> LiveBuffer:
    """Возвращает единый LiveBuffer процесса (лениво)."""
    global _BUFFER
    if _BUFFER is None:
        with _BUFFER_LOCK:
            if _BUFFER is None:
                _BUFFER = LiveBuffer()
    return _BUFFER
