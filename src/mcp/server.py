"""MSCodebase Intelligence MCP Server — рефакторинг v3

Чистый IoC-ориентированный сервер с DI-контейнером.

Архитектура:
- create_mcp_server() — только регистрация инструментов
- DI Container (ServiceCollection) — единственное место создания зависимостей
- tool/*.py — каждый инструмент в отдельном классе с constructor injection
- core/* — чистая бизнес-логика без MCP-зависимостей
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    import sqlite3


logger = logging.getLogger("mscodebase_server")


# ══════════════════════════════════════════════════════════
# Process Passport — уникальный ID запуска для диагностики
# ══════════════════════════════════════════════════════════


from src.core.passport import (
    BUILD_ID as _BUILD_ID,
)
from src.core.passport import (
    RUN_ID as _RUN_ID,
)
from src.core.passport import (
    RUN_PID as _RUN_PID,
)
from src.core.passport import (
    RUN_SOURCE_FILE as _RUN_SOURCE_FILE,
)
from src.core.passport import (
    RUN_STARTED_AT as _RUN_STARTED_AT,
)
from src.core.platform_utils import get_zed_db_path

# (passport vars imported from src.core.passport above)
_RUN_SOURCE_FILE = str(Path(__file__).resolve())

# BUILD_ID — git commit hash для мгновенной верификации версии кода.
_BUILD_ID: str = ""
try:
    _git_dir = Path(__file__).resolve().parent.parent.parent / ".git"
    if _git_dir.is_dir():
        _head = _git_dir / "HEAD"
        if _head.exists():
            _ref = _head.read_text("utf-8").strip()
            if _ref.startswith("ref: "):
                _ref_path = _git_dir / _ref[5:]
                if _ref_path.exists():
                    _BUILD_ID = _ref_path.read_text("utf-8").strip()[:12]
            else:
                _BUILD_ID = _ref[:12]
except Exception as _e:
    logger.warning(f"BUILD_ID detection failed: {_e}")
def _log_run_passport() -> None:
    """Печатает 'паспорт' процесса при старте — уникальный RUN_ID + BUILD_ID + env summary.

    Это позволяет мгновенно отличить старый процесс от нового при отладке,
    и подтвердить, что Zed подхватил обновлённый код.
    """
    import getpass

    _bridge_state = "<unavailable>"
    _registry_state = "<unavailable>"
    try:
        from src.core.lsp_project_bridge import read_project_from_bridge

        _bp = read_project_from_bridge(max_wait=0.1)
        _bridge_state = str(_bp) if _bp else "<empty — LSP not synced>"
    except Exception as _e:
        logger.warning(f"Bridge state check failed: {_e}")
    try:
        from src.core.di_container import ProjectIndexerRegistry as PIRKey
        from src.mcp.server import _services_cache

        if _services_cache is not None:
            _reg = _services_cache.resolve(PIRKey)
            _paths = _reg.get_all_paths()
            _registry_state = "; ".join(str(p) for p in _paths) if _paths else "<empty>"
    except Exception as _e:
        logger.warning(f"Registry state check failed: {_e}")
    lines = [
        "",
        "=" * 60,
        "MSCodeBase Intelligence — Process Passport",
        f"  RUN_ID      : {_RUN_ID}",
        f"  BUILD_ID    : {_BUILD_ID or '<no git>'}",
        f"  PID         : {_RUN_PID}",
        f"  Started at  : {datetime.fromtimestamp(_RUN_STARTED_AT).isoformat()}",
        f"  Source file : {_RUN_SOURCE_FILE}",
        f"  User        : {getpass.getuser()}",
        f"  CWD         : {Path.cwd().resolve()}",
        f"  _ext_root   : {_ext_root}",
        f"  PROJECT_PATH     env: {os.environ.get('PROJECT_PATH', '<unset>')!r}",
        f"  ZED_WORKTREE_ROOT env: {os.environ.get('ZED_WORKTREE_ROOT', '<unset>')!r}",
        f"  MSCODEBASE_ALLOW_SELF_INDEX env: {os.environ.get('MSCODEBASE_ALLOW_SELF_INDEX', '<unset>')!r}",
        f"  PYTHONPATH env[0] : {(os.environ.get('PYTHONPATH') or '').split(os.pathsep)[0]!r}",
        f"  Bridge      : {_bridge_state}",
        f"  Registry    : {_registry_state}",
        "=" * 60,
        "",
    ]
    for ln in lines:
        logger.info(ln)


def _check_source_extension_sync() -> Optional[str]:
    """DEV-ONLY: проверяет рассинхрон source↔extension.

    Читает .codebase_indices/install_meta.json (записанный install.py в dev-режиме).
    Сверяет git HEAD исходников с записанным.
    Возвращает warning-строку или None.

    Обычные пользователи: install_meta.json отсутствует → возвращает None.
    """
    try:
        meta_path = Path(".codebase_indices") / "install_meta.json"
        if not meta_path.exists():
            return None  # не dev-режим — не проверяем

        import json
        import subprocess

        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        installed_head = meta.get("git_head")
        if not installed_head:
            return None

        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(Path.cwd()),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode == 0:
            current_head = r.stdout.strip()
            if current_head != installed_head:
                return (
                    f"⚠️ Исходники обновлены (git {current_head[:8]} ≠ "
                    f"установлено {installed_head[:8]}). Запустите install.py "
                    f"для синхронизации расширения."
                )
        return None
    except Exception:
        return None


# ══════════════════════════════════════════════════════════
# Progress Tracking — для визуализации хода индексации
# ══════════════════════════════════════════════════════════

_last_progress: Dict[str, Any] = {}
_progress_lock = threading.Lock()


def _create_progress_callback(project_name: str):
    """Создаёт callback для отслеживания прогресса индексации.

    Возвращает callable который обновляет внутренний счётчик прогресса
    и логирует каждые 10 файлов. Потокобезопасен через _progress_lock.
    """

    def progress_callback(file_name: str, done: int, total: int, phase: str):
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


# ══════════════════════════════════════════════════════════
# Резолвер корня проекта (стабильная логика, не в DI)
# ══════════════════════════════════════════════════════════

_ext_root: Path
# ext_root определяется из PYTHONPATH (надёжнее, чем __file__,
# т.к. PYTHONPATH всегда указывает на установленное расширение,
# а __file__ может указывать на исходники при dev-запуске).
_pythonpath = os.environ.get("PYTHONPATH", "")
if _pythonpath:
    _ext_root = Path(_pythonpath.split(";")[0]).resolve()
else:
    _ext_root = Path(__file__).resolve().parent.parent.parent

# Lazy-кэш для env-резолва. ВАЖНО: PROJECT_PATH резолвится на каждый
# вызов resolve_project_root() (см. INC-53EC / REFC-02) — иначе при
# переключении workspace в Zed без рестарта MCP используется stale-путь.
_env_project_root_cache: Optional[Path] = None
_env_cache_lock = threading.Lock()

# SQLite connection cache + schema guard — открываем соединение раз в 2 секунды.
# Zed пишет workspace_id при переключении проекта, 2с TTL — достаточная свежесть.
# ВАЖНО: scoped_kv_store — недокументированный внутренний API Zed.
# При обновлении Zed схема может измениться — мы логируем предупреждение.
_sqlite_conn: Optional[sqlite3.Connection] = None
_sqlite_conn_time: float = 0
_sqlite_conn_lock = threading.RLock()  # RLock, т.к. _check_sqlite_schema_health вызывается изнутри _get_sqlite_connection
_SQLITE_CACHE_TTL = 2.0
# Флаг: проверка схемы выполнена (однократно при старте)
_sqlite_schema_checked: bool = False




def _check_sqlite_schema_health(conn) -> Optional[str]:
    """Проверяет, что таблицы scoped_kv_store и workspaces существуют.

    Принимает уже открытое соединение — не вызывает _get_sqlite_connection()
    рекурсивно. Вызывается один раз при старте.
    """
    if conn is None:
        return "Zed SQLite DB недоступна — workspace-резолвинг будет degraded"
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='scoped_kv_store'"
        )
        if cur.fetchone() is None:
            return "scoped_kv_store не найдена! workspace-резолвинг будет degraded"
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='workspaces'"
        )
        if cur.fetchone() is None:
            return "workspaces не найдена! workspace-резолвинг будет degraded"
        return None
    except Exception as e:
        return f"Ошибка проверки схемы SQLite: {e}"


def _get_sqlite_connection() -> Optional[sqlite3.Connection]:
    """Возвращает кэшированное SQLite-соединение или открывает новое.
    TTL = _SQLITE_CACHE_TTL секунд, потокобезопасно."""
    import sqlite3
    import time

    global _sqlite_conn, _sqlite_conn_time, _sqlite_schema_checked
    now = time.time()
    with _sqlite_conn_lock:
        if _sqlite_conn is not None and now - _sqlite_conn_time < _SQLITE_CACHE_TTL:
            try:
                _sqlite_conn.execute("SELECT 1")  # проверка живости
                return _sqlite_conn
            except Exception:
                _sqlite_conn = None  # умерло, создадим новое

        # открываем новое
        _db_path = get_zed_db_path()
        if not _db_path.exists():
            return None
        try:
            _sqlite_conn = sqlite3.connect(str(_db_path), timeout=2.0)
            # Однократная проверка схемы при старте
            if not _sqlite_schema_checked:
                warn = _check_sqlite_schema_health(_sqlite_conn)
                if warn:
                    logger.warning(f"[🛡 SQLite Schema Guard] {warn}")
                _sqlite_schema_checked = True
            _sqlite_conn_time = now
            return _sqlite_conn
        except Exception:
            _sqlite_conn = None
            return None


def _close_sqlite_connection():
    """Принудительно закрывает кэшированное SQLite-соединение."""
    global _sqlite_conn
    with _sqlite_conn_lock:
        if _sqlite_conn is not None:
            try:
                _sqlite_conn.close()
            except Exception as _e:
                logger.warning(f"SQLite close failed: {_e}")
            _sqlite_conn = None



def _reject_self_index_target(p: Path, *, source: str) -> bool:
    """Возвращает True если path — это self-indexing target (отклонить).

    Отклоняем:
    - _ext_root (исходники самого расширения в dev-режиме — `python -m src.main`
      из workspace `D:\\Project\\MSCodeBase`). Это может случиться, если
      пользователь открывает исходники расширения как проект в Zed.
    - Zed install dir (см. is_zed_install_dir в lsp_project_bridge).

    РАНЬШЕ здесь была проверка `(p / "src/lsp_main.py").exists()` — она
    была ошибочной, потому что исходники расширения РЕАЛЬНО содержат
    `src/lsp_main.py`, и guard блокировал легитимный dev-сценарий
    ("открыть репо расширения как проект в Zed, чтобы индексировать
    свой же код"). Теперь вместо маркера-файла используется явный
    ext_root-equality + is_zed_install_dir (Zed install markers
    специфичны, ложных срабатываний на обычных проектах не дают).

    NOTE: эта функция НЕ блокирует `_ext_root` через тот же guard, что
    и `base.py._is_self_index_path` — там блокировка строже (нужна
    для теста `test_explicit_ext_root_raises_tool_error`, где
    explicit_project_root == _ext_root должен бросать ToolError).
    Здесь же мы используем это только как «если env var буквально
    указывает на наш ext_root, отдать приоритет bridge / CWD».
    """
    if p == _ext_root:
        return True
    try:
        from src.core.lsp_project_bridge import is_zed_install_dir

        if is_zed_install_dir(p):
            logger.warning(
                f"{source} указывает на директорию установки Zed ({p}). "
                f"Игнорирую — self-indexing guard."
            )
            return True
    except Exception:
        # Если lsp_project_bridge недоступен — не блокируем (fail-open)
        pass
    return False


def _resolve_env_project_root() -> Optional[Path]:
    """Резолвит PROJECT_PATH из окружения лениво + один раз кэширует результат.

    Возвращает None, если PROJECT_PATH не задан / невалиден / указывает
    на сам ext (тогда bridge/ZED_WORKTREE_ROOT/CWD получают шанс).
    """
    global _env_project_root_cache
    with _env_cache_lock:
        if _env_project_root_cache is not None:
            return _env_project_root_cache
        raw = os.environ.get("PROJECT_PATH", "").strip()
        if not raw:
            return None
        # Случай 1: Zed literal "$ZED_WORKTREE_ROOT" без подстановки.
        if raw.startswith("$"):
            zed_root = os.environ.get("ZED_WORKTREE_ROOT")
            if zed_root:
                p = Path(zed_root).resolve()
                if p.exists() and not _reject_self_index_target(
                    p, source="ZED_WORKTREE_ROOT"
                ):
                    _env_project_root_cache = p
                    return _env_project_root_cache
            return None
        # Случай 2: прямой путь.
        try:
            resolved = Path(raw).resolve()
        except (OSError, ValueError):
            return None
        if not resolved.exists() or not resolved.is_dir():
            return None
        # Self-indexing guard (см. INC-53EC / REFC-02): если PROJECT_PATH
        # указывает на ext_root или Zed install — это либо ошибка
        # пользователя, либо попытка индексировать установку.
        if _reject_self_index_target(resolved, source="PROJECT_PATH"):
            logger.warning(
                f"PROJECT_PATH указывает на self-indexing target ({resolved}). "
                f"Игнорирую — установите PROJECT_PATH=$ZED_WORKTREE_ROOT."
            )
            return None
        _env_project_root_cache = resolved
        return _env_project_root_cache


def reset_project_root_cache() -> None:
    """Сбрасывает кэш resolve_project_root (для тестов и hot-reload)."""
    global _env_project_root_cache
    with _env_cache_lock:
        _env_project_root_cache = None


def resolve_project_root(provided: str = "") -> Path:
    """Возвращает корень проекта для MCP-инструментов.

    Приоритет (каждый вызов резолвит заново — см. INC-53EC / REFC-02):
    0. SQLite multi_workspace_state.active_workspace_id (НАДЁЖНО!)
       Zed пишет сюда активный проект при каждом переключении.
       Единственный механизм, работающий на Windows.
    1. Явно переданный provided
    2. LSP→MCP bridge (temp-файл от LSP)
    3. Zed SQLite DB (workspaces table — fallback, если нет active)
    4. PROJECT_PATH из окружения (lazy, с self-indexing guard)
    5. ZED_WORKTREE_ROOT env
    6. CWD, если != ext_root
    7. ext_root как fallback
    """
    if provided and provided.strip():
        return Path(provided).resolve()

    # ─── 1. SQLite: multi_workspace_state.active_workspace_id ───
    # Используем кэшированное соединение (TTL 2с, см. _get_sqlite_connection).
    try:
        _conn = _get_sqlite_connection()
        if _conn is not None:
            import json as _json

            _cur = _conn.cursor()
            _cur.execute(
                "SELECT key, value FROM scoped_kv_store "
                "WHERE namespace = 'multi_workspace_state' "
                "ORDER BY rowid DESC"
            )
            for _row in _cur.fetchall():
                try:
                    _state = _json.loads(_row[1])
                    _active_id = _state.get("active_workspace_id")
                    if _active_id is not None:
                        _cur.execute(
                            "SELECT paths FROM workspaces WHERE workspace_id = ?",
                            (_active_id,),
                        )
                        _match = _cur.fetchone()
                        if _match and _match[0]:
                            # Guard: SQLite paths могут быть через \n (multi-root).
                            _raw = _match[0].strip()
                            _first = _raw.split("\n")[0].split(",")[0].strip()
                            _path = Path(_first)
                            if _path.exists() and _path.is_dir() and not _reject_self_index_target(
                                _path, source="ACTIVE_WORKSPACE"
                            ):
                                logger.debug(
                                    f"resolve_project_root: active_workspace_id={_active_id} → {_path}"
                                )
                                return _path.resolve()
                except Exception:
                    continue
    except Exception as _active_err:
        logger.debug(f"resolve_project_root: active_workspace error: {_active_err}")

    # LSP→MCP bridge (Windows compat)
    try:
        from src.core.lsp_project_bridge import read_project_from_bridge

        bridge_path = read_project_from_bridge()
        if bridge_path is not None:
            logger.debug(f"resolve_project_root: bridge={bridge_path}")
            return bridge_path
    except Exception as _e:
        logger.warning(f"Bridge read failed: {_e}")
    # Fallback: Zed SQLite DB (через то же кэшированное соединение)
    try:
        _conn2 = _get_sqlite_connection()
        if _conn2 is not None:
            _cur2 = _conn2.cursor()
            _cur2.execute(
                "SELECT paths, timestamp FROM workspaces WHERE paths != '' AND paths IS NOT NULL ORDER BY timestamp DESC"
            )
            _all_rows = _cur2.fetchall()
            _candidates = []
            for _row in _all_rows:
                if not _row[0]:
                    continue
                # Guard: SQLite paths may contain \n (multi-root workspace).
                _raw = _row[0].strip()
                _parts = _raw.split("\n") if "\n" in _raw else _raw.split(",")
                for _part in _parts:
                    _p = _part.strip()
                    if not _p:
                        continue
                    _path = Path(_p)
                    if _reject_self_index_target(_path, source="ZED_DB"):
                        continue
                    _score = 2 if (_path / ".git").exists() else 1
                    _candidates.append((_score, _row[1] or "", _path))
            if _candidates:
                _candidates.sort(key=lambda x: (x[0], x[1] or ""), reverse=True)
                _best = _candidates[0][2]
                logger.debug(
                    f"resolve_project_root: Zed DB ({len(_candidates)} candidates) → {_best}"
                )
                return _best.resolve()
    except Exception as _zed_err:
        logger.debug(f"resolve_project_root: Zed DB fallback error: {_zed_err}")

    env_root = _resolve_env_project_root()
    if env_root is not None:
        logger.debug(f"resolve_project_root: PROJECT_PATH={env_root}")
        return env_root

    zed_root = os.environ.get("ZED_WORKTREE_ROOT")
    if zed_root:
        zed_path = Path(zed_root).resolve()
        if zed_path.exists() and not _reject_self_index_target(
            zed_path, source="ZED_WORKTREE_ROOT"
        ):
            logger.debug(f"resolve_project_root: ZED_WORKTREE_ROOT={zed_path}")
            return zed_path

    cwd = Path.cwd().resolve()
    if not _reject_self_index_target(cwd, source="CWD"):
        logger.debug(f"resolve_project_root: CWD={cwd}")
        return cwd

    # Диагностика: почему все шаги провалились
    _log_project_resolution_failure()
    logger.warning(
        f"resolve_project_root: fallback to ext_root={_ext_root} "
        f"(возможна self-indexing; установите PROJECT_PATH=$ZED_WORKTREE_ROOT)"
    )
    return _ext_root


def _log_project_resolution_failure() -> None:
    """Логирует детальную причину падения resolve_project_root в ext_root."""
    try:
        from src.core.lsp_project_bridge import get_bridge_dir

        bridge_dir = get_bridge_dir()
        if not bridge_dir.exists():
            logger.warning("🌉 BRIDGE: директория не существует")
            return
        json_files = list(bridge_dir.glob("*.json"))
        if not json_files:
            logger.warning(
                "🌉 BRIDGE: директория существует, но JSON-файлов нет — "
                "LSP не запущен или упал при старте"
            )
        else:
            for f in json_files:
                logger.debug(f"🌉 BRIDGE найден: {f.name}")
    except Exception as _rpf_err:
        logger.debug(f"_log_project_resolution_failure: {_rpf_err}")


# ══════════════════════════════════════════════════════════
# Default project root (устанавливается при create_mcp_server)
# ══════════════════════════════════════════════════════════

_default_project_root: Optional[Path] = None
_services_cache: Optional[Any] = None  # для debug_runtime_passport


# ══════════════════════════════════════════════════════════
# Создание MCP-сервера
# ══════════════════════════════════════════════════════════


# Re-export from server_factory (избегаем циклического импорта)
def run_server(original_stdout=None):
    """Запускает MCP-сервер через stdio (обёртка над server_factory)."""
    from src.mcp.server_factory import run_server as _run
    _run(original_stdout)
