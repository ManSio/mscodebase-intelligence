"""UploadSource — источник из загруженного архива/патча (Фаза 2, ТЗ §2.1/§2.2).

Реализует WorkspaceSource (src/core/interfaces/workspace_source.py). Кейс:
«дали архив/патч через MCP resource / HTTP multipart → распаковали в temp
workspace → индексируем как локальный».

Безопасность (R-3, план §3):
1. Size cap ДО распаковки (по размеру члена-архива) + cap суммарного распакованного
   (decompression-bomb: zip-bomb / tar sparse).
2. Path-traversal guard: каждый член архива обязан распаковаться ВНУТРИ корня
   (отклоняем абсолютные пути, "../", symlink/hardlink-члены).
3. TTL-очистка кэша (прецедент KI-110 «2481 мусорных папок, нет GC»).

Fingerprint = content-hash архива (sha256): повторная загрузка идентичного
архива → тот же кэш-каталог → 0 повторной распаковки/re-embed.

Ошибки: UploadSourceError с kind (INCONCLUSIVE-контракт, ТЗ §6.5).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import shutil
import tarfile
import threading
import zipfile
from pathlib import Path
from typing import AsyncIterator, Optional

from src.core.interfaces.workspace_source import FileChangeEvent

logger = logging.getLogger(__name__)

DEFAULT_MAX_ARCHIVE_BYTES = 100 * 1024 * 1024  # 100MB входа
DEFAULT_MAX_EXTRACTED_BYTES = 500 * 1024 * 1024  # 500MB распакованного (bomb-guard)
DEFAULT_TTL_SEC = 24 * 3600  # кэш протухает за сутки (KI-110 урок)

# Расширения-архивы, которые принимаем
_SUPPORTED_SUFFIXES = (".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2")


class UploadSourceError(Exception):
    """Ошибка UploadSource с машинным kind (маппится в INCONCLUSIVE)."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _safe_join(root: Path, member_name: str) -> Path:
    """Резолв члена внутри root с path-traversal guard (R-3)."""
    if member_name.startswith(("/", "\\")):
        raise UploadSourceError("path_traversal", f"Абсолютный член {member_name!r} запрещён")
    norm = Path(member_name)
    if norm.is_absolute():
        raise UploadSourceError("path_traversal", f"Абсолютный член {member_name!r} запрещён")
    parts = norm.parts
    if any(p in ("..", "") for p in parts):
        raise UploadSourceError("path_traversal", f"Обход пути в члене {member_name!r}")
    dest = (root / norm).resolve()
    if not dest.is_relative_to(root.resolve()):
        raise UploadSourceError("path_traversal", f"Член {member_name!r} выходит за корень")
    return dest


def _extract_zip(archive: Path, target: Path, max_bytes: int) -> None:
    with zipfile.ZipFile(archive) as zf:
        infos = zf.infolist()
        total = sum(i.file_size for i in infos if not i.is_dir())
        if total > max_bytes:
            raise UploadSourceError(
                "too_large_extracted",
                f"Распакованный объём {total / 1e6:.0f}MB > лимит {max_bytes / 1e6:.0f}MB (bomb-guard)",
            )
        for i in infos:
            if i.is_dir():
                continue
            # symlink-члены zip (external_attr mode 0o120000) — запрещены (эскейп)
            if (i.external_attr >> 16) & 0o170000 == 0o120000:
                raise UploadSourceError("symlink_member", f"Symlink-член {i.filename!r} запрещён")
            dest = _safe_join(target, i.filename)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(i) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)


def _extract_tar(archive: Path, target: Path, max_bytes: int) -> None:
    with tarfile.open(archive) as tf:
        total = 0
        for member in tf:
            if member.isdir():
                continue
            if member.issym() or member.islnk():
                raise UploadSourceError("symlink_member", f"Ссылочный член {member.name!r} запрещён")
            if member.isreg():
                if member.size < 0 or total + member.size > max_bytes:
                    raise UploadSourceError(
                        "too_large_extracted",
                        f"Распакованный объём > лимит {max_bytes / 1e6:.0f}MB (bomb-guard)",
                    )
                dest = _safe_join(target, member.name)
                dest.parent.mkdir(parents=True, exist_ok=True)
                f = tf.extractfile(member)
                if f is None:
                    continue
                with open(dest, "wb") as out:
                    shutil.copyfileobj(f, out)
                total += member.size
            elif not member.ischr() and not member.isblk() and not member.isfifo():
                # специальные типы (device/fifo) — игнорируем, не пишем
                continue


class UploadCache:
    """TTL-кэш распакованных архивов (<cache_root>/<hash8>/)."""

    def __init__(self, cache_root: Path, *, ttl_sec: float = DEFAULT_TTL_SEC):
        self.root = Path(cache_root)
        self.ttl_sec = ttl_sec
        self._lock = threading.Lock()

    def get_fresh(self, digest: str) -> Optional[Path]:
        with self._lock:
            d = self.root / digest[:8]
            if not d.is_dir():
                return None
            import time

            if time.time() - d.stat().st_mtime > self.ttl_sec:
                shutil.rmtree(d, ignore_errors=True)
                return None
            return d

    def put(self, digest: str, extracted: Path) -> None:
        with self._lock:
            import os
            import time

            self.root.mkdir(parents=True, exist_ok=True)
            dest = self.root / digest[:8]
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            os.replace(str(extracted), str(dest))
            # фиксируем время кладём в mtime (порт: os.utime на dir)
            t = time.time()
            os.utime(dest, (t, t))


class UploadSource:
    """Источник кода из архива (реализация WorkspaceSource)."""

    def __init__(
        self,
        archive_path: Path,
        cache_root: Path,
        *,
        max_archive_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
        max_extracted_bytes: int = DEFAULT_MAX_EXTRACTED_BYTES,
        ttl_sec: float = DEFAULT_TTL_SEC,
    ):
        self._archive = Path(archive_path)
        self.cache = UploadCache(cache_root, ttl_sec=ttl_sec)
        self._max_archive_bytes = max_archive_bytes
        self._max_extracted_bytes = max_extracted_bytes

    # ── WorkspaceSource ──────────────────────────────────────────────

    async def resolve(self) -> Path:
        """Распаковывает архив (если кэш протух/отсутствует) и возвращает путь."""
        return await asyncio.to_thread(self._resolve_sync)

    async def watch(self, interval_seconds: float = 30.0) -> AsyncIterator[FileChangeEvent]:
        """Poll по content-hash архива: событие при изменении загруженного файла."""
        last = self.fingerprint()
        while True:
            await asyncio.sleep(interval_seconds)
            current = self.fingerprint()
            if current != last:
                yield FileChangeEvent(kind="fingerprint_changed", fingerprint=current)
                last = current

    def fingerprint(self) -> str:
        """Content-hash архива: идентичная загрузка → тот же кэш → 0 re-embed."""
        if not self._archive.is_file():
            return ""
        return _sha256_file(self._archive)

    # ── Внутреннее ───────────────────────────────────────────────────

    def _resolve_sync(self) -> Path:
        if not any(self._archive.name.endswith(s) for s in _SUPPORTED_SUFFIXES):
            raise UploadSourceError(
                "unsupported_format",
                f"Не-поддерживаемый формат '{self._archive.name}'; "
                f"поддерживаются: {', '.join(_SUPPORTED_SUFFIXES)}",
            )
        if not self._archive.is_file():
            raise UploadSourceError("missing_archive", "Архив не найден")
        size = self._archive.stat().st_size
        if size > self._max_archive_bytes:
            raise UploadSourceError(
                "too_large",
                f"Архив {size / 1e6:.0f}MB > лимит {self._max_archive_bytes / 1e6:.0f}MB",
            )

        digest = self.fingerprint()
        cached = self.cache.get_fresh(digest)
        if cached is not None:
            return cached

        # распаковка в tmp, затем атомарный перенос в кэш (неудача → INCONCLUSIVE)
        import tempfile

        with tempfile.TemporaryDirectory(prefix="mscodebase_upload_") as tmp:
            tmp_path = Path(tmp)
            if self._archive.name.endswith(".zip"):
                _extract_zip(self._archive, tmp_path, self._max_extracted_bytes)
            else:
                _extract_tar(self._archive, tmp_path, self._max_extracted_bytes)
            self.cache.put(digest, tmp_path)
        return self.cache.root / digest[:8]
