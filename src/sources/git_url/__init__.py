"""GitUrlSource — источник кода по git-URL (Фаза 2, ТЗ §2.1/§2.2).

Реализует WorkspaceSource (src/core/interfaces/workspace_source.py).
Дизайн и обоснование — план §2.2 (prior art: bloop/Sourcegraph/Bazel GC;
OWASP SSRF; E-02: clone/fingerprint замеры).

Безопасность (R-2, план §3):
1. Scheme allowlist — ТОЛЬКО https (дефолт); ssh/git/file/scp отклоняются
   на этапе парсинга (git ≥2.38 сам блокирует file://, но мы не полагаемся).
2. Domain allowlist (github.com/gitlab.com/bitbucket.org + конфигурируемые).
3. DNS-проверка: все A/AAAA хоста обязаны быть global (IMDS/RFC1918/
   loopback/link-local/multicast → отказ). DNS-rebinding до конца не закрыт —
   KNOWN_ISSUES (Фаза 2.5: пиннинг IP + повторный резолв перед fetch).
4. Post-clone: remote.origin.url обязан остаться в allowlist (защита от
   редиректа на чужой хост); лимиты размера и числа файлов (DoS).

Ошибки: GitUrlSourceError с машинным kind — потребитель (MCP-тул) обязан
мапить их в INCONCLUSIVE (ТЗ §6.5), не в crash.

Кэш: <cache_root>/<hash8>/ + manifest.json; LRU(max_entries=5) + TTL 24ч
(план §9 п.2; GC по размеру — Фаза 2.5, паттерн Bazel disk-cache).
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.parse
from pathlib import Path
from typing import AsyncIterator, Iterable, Optional

from src.core.interfaces.workspace_source import FileChangeEvent

logger = logging.getLogger(__name__)

# ── Константы/дефолты (план §2.2) ──────────────────────────────────────────

DEFAULT_ALLOWED_DOMAINS = frozenset({"github.com", "gitlab.com", "bitbucket.org"})
DEFAULT_ALLOWED_SCHEMES = frozenset({"https"})
DEFAULT_MAX_CLONE_BYTES = 500 * 1024 * 1024  # 500MB пост-clone лимит
DEFAULT_MAX_FILE_COUNT = 200_000
DEFAULT_CLONE_TIMEOUT_SEC = 120.0
DEFAULT_TTL_SEC = 24 * 3600  # 24ч
DEFAULT_MAX_ENTRIES = 5  # LRU — то же число, что ProjectIndexerRegistry

# Порты: только дефолтный, чтобы git не стал сканером портов
_ALLOWED_PORTS = frozenset({None, 443})

_SAFE_ENV_OVERRIDES = {
    "GIT_TERMINAL_PROMPT": "0",  # не висеть на auth-промпте
    "GIT_LFS_SKIP_SMUDGE": "1",  # индексируем исходники, не LFS-блоб
}

_HARDENED_GIT_CFG = (
    "-c",
    "protocol.file.allow=never",  # класс CVE-2022-39253: file:// клоны
    "-c",
    "protocol.ext.allow=never",
    "-c",
    "protocol.allow=user",
)


class GitUrlSourceError(Exception):
    """Ошибка GitUrlSource с машинным kind (маппится в INCONCLUSIVE)."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def _url_hash(url: str) -> str:
    """Детерминированный хэш канонического URL (8 символов)."""
    return hashlib.md5(url.encode("utf-8")).hexdigest()[:8]


def _ips_are_global(ip_strings: Iterable[str]) -> bool:
    """Все ли IP global (не private/loopback/link-local/multicast/reserved)."""
    for ip_str in ip_strings:
        try:
            ip = ipaddress.ip_address(ip_str.split("%")[0])
        except ValueError:
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False
    return True


def _parse_url(
    url: str,
    allowed_schemes: frozenset[str],
    allowed_domains: frozenset[str],
) -> tuple[str, str]:
    """Парсит и валидирует URL. Возвращает (host, path) или бросает ошибку."""
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError as e:
        raise GitUrlSourceError("invalid_url", f"Некорректный URL: {e}") from e

    if parsed.scheme not in allowed_schemes:
        raise GitUrlSourceError(
            "invalid_scheme",
            f"Схема '{parsed.scheme}' запрещена (разрешены: {sorted(allowed_schemes)})",
        )
    if parsed.username or parsed.password:
        raise GitUrlSourceError(
            "credentials_in_url", "Credentials в URL запрещены (userinfo rejected)"
        )
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "https":
        # Сетевые схемы: полный SSRF-набор проверок (host/port/domain)
        if not host:
            raise GitUrlSourceError("invalid_url", "HTTPS-URL без хоста")
        if parsed.port not in _ALLOWED_PORTS:
            raise GitUrlSourceError(
                "invalid_port", f"Порт {parsed.port} запрещён (только 443/дефолт)"
            )
        if host not in allowed_domains:
            raise GitUrlSourceError(
                "domain_not_allowed",
                f"Домен '{host}' не в allowlist: {sorted(allowed_domains)}",
            )
    return host, parsed.path


def _resolve_and_check_ips(host: str) -> frozenset[str]:
    """Резолвит host (все A/AAAA) и требует global IP (SSRF-защита, OWASP).

    Возвращает набор валидированных IP — для DNS-rebinding pinning (Фаза 2.5):
    тот же набор проверяется ПОСЛЕ клона; расхождение → подозрение на ребиндинг.
    """
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise GitUrlSourceError("dns_unresolved", f"Не удалось резолвить {host}: {e}") from e
    ips = frozenset(info[4][0] for info in infos)
    if not _ips_are_global(ips):
        raise GitUrlSourceError(
            "non_global_ip",
            f"Хост {host} резолвится в не-global IP: {sorted(ips)} (SSRF-защита)",
        )
    return ips


def _run_git(
    args: list[str],
    *,
    cwd: Optional[Path] = None,
    timeout_sec: float = DEFAULT_CLONE_TIMEOUT_SEC,
    extra_cfg: tuple[str, ...] = (),
) -> tuple[int, str, str]:
    """Безопасный git-вызов: Popen + communicate (§5.16), без консоли.

    Возвращает (returncode, stdout, stderr). НЕ бросает — вызывающий решает.
    extra_cfg — доп. `-c` флаги ПОСЛЕ харденинга (побеждают его; тестовый
    оверрайд для file-схемы, см. KNOWN_ISSUES: protocol.file.allow).
    """
    env = dict(os.environ)
    env.update(_SAFE_ENV_OVERRIDES)
    proc = None
    try:
        proc = subprocess.Popen(
            ["git", *_HARDENED_GIT_CFG, *extra_cfg, *args],
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        stdout, stderr = proc.communicate(timeout=timeout_sec)
        return proc.returncode or 0, stdout or "", stderr or ""
    except subprocess.TimeoutExpired:
        if proc is not None:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001 — best-effort kill
                pass
        return -1, "", f"git timeout after {timeout_sec}s"
    except OSError as e:
        return -2, "", f"git не запустился: {e}"


def _dir_size(path: Path) -> int:
    """Суммарный размер файлов (портабельно, без du)."""
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return total


def _file_count(path: Path) -> int:
    return sum(len(files) for _root, _dirs, files in os.walk(path))


class GitRepoCache:
    """LRU(max_entries) + TTL кэш клонов (план §9 п.2; паттерн Bazel GC).

    Манифест: <cache_root>/manifest.json — {url_hash: {url, dir_name,
    created_at, last_accessed, size_bytes}}. Thread-safe (threading.Lock).
    """

    def __init__(
        self,
        cache_root: Path,
        *,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        ttl_sec: float = DEFAULT_TTL_SEC,
    ):
        self.root = Path(cache_root)
        self.max_entries = max_entries
        self.ttl_sec = ttl_sec
        self._lock = threading.Lock()
        self._manifest_path = self.root / "manifest.json"

    def _load(self) -> dict:
        if not self._manifest_path.exists():
            return {}
        try:
            return json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self, manifest: dict) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            tmp = self._manifest_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self._manifest_path)
        except OSError as e:
            logger.warning(f"GitRepoCache: не удалось сохранить манифест: {e}")

    def get(self, url_hash: str) -> Optional[Path]:
        with self._lock:
            manifest = self._load()
            entry = manifest.get(url_hash)
            if not entry:
                return None
            entry_dir = self.root / entry["dir_name"]
            if not entry_dir.exists():
                manifest.pop(url_hash, None)
                self._save(manifest)
                return None
            if time.time() - entry.get("created_at", 0) > self.ttl_sec:
                manifest.pop(url_hash, None)
                self._save(manifest)
                shutil.rmtree(entry_dir, ignore_errors=True)
                return None
            entry["last_accessed"] = time.time()
            self._save(manifest)
            return entry_dir

    def put(self, url: str, url_hash: str, entry_dir: Path, size_bytes: int) -> None:
        with self._lock:
            manifest = self._load()
            now = time.time()
            manifest[url_hash] = {
                "url": url,
                "dir_name": entry_dir.name,
                "created_at": now,
                "last_accessed": now,
                "size_bytes": size_bytes,
            }
            while len(manifest) > self.max_entries:
                oldest_key = min(manifest, key=lambda k: manifest[k]["last_accessed"])
                oldest = manifest.pop(oldest_key)
                shutil.rmtree(self.root / oldest["dir_name"], ignore_errors=True)
                logger.info(f"GitRepoCache: LRU-эвикция {oldest['url']}")
            self._save(manifest)

    def evict(self, url_hash: str) -> None:
        with self._lock:
            manifest = self._load()
            entry = manifest.pop(url_hash, None)
            if entry:
                shutil.rmtree(self.root / entry["dir_name"], ignore_errors=True)
            self._save(manifest)


class GitUrlSource:
    """Источник кода по git-URL (реализация WorkspaceSource)."""

    def __init__(
        self,
        url: str,
        cache_root: Path,
        *,
        allowed_schemes: frozenset[str] = DEFAULT_ALLOWED_SCHEMES,
        allowed_domains: frozenset[str] = DEFAULT_ALLOWED_DOMAINS,
        max_clone_bytes: int = DEFAULT_MAX_CLONE_BYTES,
        max_file_count: int = DEFAULT_MAX_FILE_COUNT,
        clone_timeout_sec: float = DEFAULT_CLONE_TIMEOUT_SEC,
        max_cache_entries: int = DEFAULT_MAX_ENTRIES,
        ttl_sec: float = DEFAULT_TTL_SEC,
        extra_git_cfg: tuple[str, ...] = (),
    ):
        self.url = url
        self.cache = GitRepoCache(
            cache_root, max_entries=max_cache_entries, ttl_sec=ttl_sec
        )
        self._allowed_schemes = allowed_schemes
        self._allowed_domains = allowed_domains
        self._max_clone_bytes = max_clone_bytes
        self._max_file_count = max_file_count
        self._clone_timeout_sec = clone_timeout_sec
        self._extra_git_cfg = extra_git_cfg
        self._url_hash = _url_hash(url)

    # ── WorkspaceSource ──────────────────────────────────────────────

    async def resolve(self) -> Path:
        """Клонирует (если кэш протух/отсутствует) и возвращает путь к клону."""
        return await asyncio.to_thread(self._resolve_sync)

    async def watch(self, interval_seconds: float = 30.0) -> AsyncIterator[FileChangeEvent]:
        path = await self.resolve()
        last = self.fingerprint(path)
        while True:
            await asyncio.sleep(interval_seconds)
            current = self.fingerprint(path)
            if current != last:
                yield FileChangeEvent(kind="fingerprint_changed", fingerprint=current)
                last = current

    def fingerprint(self, path: Optional[Path] = None) -> str:
        """Git-tree fingerprint (E-02: 79ms, ноль re-hash); fallback — манифест."""
        repo = path or self.cache.get(self._url_hash)
        if repo is None:
            return ""
        head_rc, head, _ = _run_git(["-C", str(repo), "rev-parse", "HEAD"], timeout_sec=10)
        if head_rc != 0:
            return _manifest_fallback(repo)
        tree_rc, tree, _ = _run_git(["-C", str(repo), "ls-tree", "-r", "HEAD"], timeout_sec=30)
        if tree_rc != 0:
            return _manifest_fallback(repo)
        h = hashlib.sha256()
        h.update(head.strip().encode("ascii"))
        for line in sorted(tree.splitlines()):
            h.update(b"\n")
            h.update(line.encode("utf-8"))
        return h.hexdigest()

    # ── Внутреннее ───────────────────────────────────────────────────

    def _resolve_sync(self) -> Path:
        host, _path = _parse_url(self.url, self._allowed_schemes, self._allowed_domains)
        ips_pre: frozenset[str] = frozenset()
        if self._allowed_schemes & {"https"}:
            ips_pre = _resolve_and_check_ips(host)  # SSRF: все A/AAAA обязаны быть global

        cached = self.cache.get(self._url_hash)
        if cached is not None:
            return cached

        # Клон напрямую в target (без tmp+rename: rename свежих клонов на Windows
        # блокируется Defender/Search Indexer — E-03 2026-08-18). Атомарность
        # обеспечивает манифест: put() только после post-clone-проверок, поэтому
        # частичный клон (краш/таймаут) невидим для cache.get() и чистится
        # при следующем resolve (orphan ниже).
        target = self.cache.root / self._url_hash
        self.cache.root.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)  # orphan от прошлого краха
        try:
            rc, _out, err = _run_git(
                ["clone", "--depth", "1", "--single-branch", self.url, str(target)],
                timeout_sec=self._clone_timeout_sec,
                extra_cfg=self._extra_git_cfg,
            )
            if rc != 0:
                shutil.rmtree(target, ignore_errors=True)
                raise GitUrlSourceError(
                    "clone_failed", f"git clone завершился с кодом {rc}: {err.strip()[-400:]}"
                )
            self._post_clone_checks(target)
            # DNS-rebinding-детект (Фаза 2.5): если набор IP до/после клона
            # разошёлся — подозрение на rebinding; INCONCLUSIVE + evict.
            if self._allowed_schemes & {"https"} and ips_pre:
                ips_post = _resolve_and_check_ips(host)
                if ips_post != ips_pre:
                    raise GitUrlSourceError(
                        "dns_rebinding_suspected",
                        f"DNS изменился за время клона: {sorted(ips_pre)} → {sorted(ips_post)}",
                    )
            self.cache.put(self.url, self._url_hash, target, _dir_size(target))
            return target
        except GitUrlSourceError:
            shutil.rmtree(target, ignore_errors=True)
            raise
        except Exception as e:  # noqa: BLE001 — оборачиваем в INCONCLUSIVE-ошибку
            shutil.rmtree(target, ignore_errors=True)
            raise GitUrlSourceError("clone_error", f"Клонирование не удалось: {e}") from e

    def _post_clone_checks(self, repo: Path) -> None:
        size = _dir_size(repo)
        if size > self._max_clone_bytes:
            raise GitUrlSourceError(
                "too_large",
                f"Клон {size / 1e6:.0f}MB > лимит {self._max_clone_bytes / 1e6:.0f}MB",
            )
        count = _file_count(repo)
        if count > self._max_file_count:
            raise GitUrlSourceError(
                "too_many_files",
                f"{count} файлов > лимит {self._max_file_count}",
            )
        # Редирект-защита: канонический origin обязан остаться в allowlist
        rc, out, _ = _run_git(
            ["-C", str(repo), "config", "--get", "remote.origin.url"], timeout_sec=10
        )
        if rc == 0 and out.strip():
            _parse_url(out.strip(), self._allowed_schemes, self._allowed_domains)


def _manifest_fallback(repo: Path) -> str:
    """Fallback-fingerprint (не git-репо): хэш отсортированных путей+sha256."""
    h = hashlib.sha256()
    entries = []
    for p in sorted(Path(repo).rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(repo).as_posix()
        if rel.split("/", 1)[0].startswith("."):
            continue
        try:
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
        except OSError:
            digest = ""
        entries.append((rel, digest))
    for rel, digest in entries:
        h.update(rel.encode("utf-8"))
        h.update(b"\x00")
        h.update(digest.encode("ascii"))
    return h.hexdigest()
