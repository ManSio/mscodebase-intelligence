"""MSCodebase Intelligence MCP Server — рефакторинг v3

Чистый IoC-ориентированный сервер с DI-контейнером.

Архитектура:
- create_mcp_server() — только регистрация инструментов
- DI Container (ServiceCollection) — единственное место создания зависимостей
- tool/*.py — каждый инструмент в отдельном классе с constructor injection
- core/* — чистая бизнес-логика без MCP-зависимостей
"""

import asyncio
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("mscodebase_server")

# ══════════════════════════════════════════════════════════
# Process Passport — уникальный ID запуска для диагностики
# ══════════════════════════════════════════════════════════

import uuid as _uuid

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
except Exception:
    pass


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
    except Exception:
        pass
    try:
        from src.core.di_container import ProjectIndexerRegistry as PIRKey
        from src.mcp.server import _services_cache

        if _services_cache is not None:
            _reg = _services_cache.resolve(PIRKey)
            _paths = _reg.get_all_paths()
            _registry_state = "; ".join(str(p) for p in _paths) if _paths else "<empty>"
    except Exception:
        pass

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
        except Exception:
            pass

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

    # ─── 1. SQLite: multi_workspace_state.active_workspace_id (НАДЁЖНО!) ───
    # Zed пишет сюда активный workspace при каждом переключении проекта.
    # Единственный механизм, который работает на Windows (не требует env/LSP).
    try:
        _db_path = (
            Path(os.environ.get("LOCALAPPDATA", ""))
            / "Zed"
            / "db"
            / "0-stable"
            / "db.sqlite"
        )
        if _db_path.exists():
            import json as _json
            import sqlite3

            _conn = sqlite3.connect(str(_db_path), timeout=2.0)
            _cur = _conn.cursor()
            # Ищем multi_workspace_state для любого window_id
            _cur.execute(
                "SELECT key, value FROM scoped_kv_store "
                "WHERE namespace = 'multi_workspace_state'"
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
                            _path = Path(_match[0].strip())
                            if _path.exists() and not _reject_self_index_target(
                                _path, source="ACTIVE_WORKSPACE"
                            ):
                                _conn.close()
                                logger.debug(
                                    f"resolve_project_root: active_workspace_id={_active_id} → {_path}"
                                )
                                return _path.resolve()
                except Exception:
                    continue
            _conn.close()
    except Exception as _active_err:
        logger.debug(f"resolve_project_root: active_workspace error: {_active_err}")

    # LSP→MCP bridge (Windows compat)
    try:
        from src.core.lsp_project_bridge import read_project_from_bridge

        bridge_path = read_project_from_bridge()
        if bridge_path is not None:
            logger.debug(f"resolve_project_root: bridge={bridge_path}")
            return bridge_path
    except Exception:
        pass

    # Fallback: Zed SQLite DB (не зависит от LSP!)
    # Multi-window: читаем ВСЕ воркспейсы, фильтруем self-indexing,
    # выбираем самый свежий с .git (реальный проект).
    try:
        _zed_db_path = (
            Path(os.environ.get("LOCALAPPDATA", ""))
            / "Zed"
            / "db"
            / "0-stable"
            / "db.sqlite"
        )
        if _zed_db_path.exists():
            import sqlite3

            _conn = sqlite3.connect(str(_zed_db_path), timeout=2.0)
            _cur = _conn.cursor()
            # Читаем ВСЕ workspace paths, сортируем по свежести
            _cur.execute(
                "SELECT paths, timestamp FROM workspaces WHERE paths != '' AND paths IS NOT NULL ORDER BY timestamp DESC"
            )
            _all_rows = _cur.fetchall()
            _conn.close()
            _candidates = []
            for _row in _all_rows:
                if not _row[0]:
                    continue
                for _part in _row[0].split(","):
                    _p = _part.strip()
                    if not _p:
                        continue
                    _path = Path(_p)
                    if _reject_self_index_target(_path, source="ZED_DB"):
                        continue
                    # Предпочитаем проекты с .git (реальные, не临时ные)
                    _score = 2 if (_path / ".git").exists() else 1
                    _candidates.append((_score, _row[1] or "", _path))
            if _candidates:
                # Сортируем: score(выше) → timestamp(новее)
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


def create_mcp_server() -> "FastMCP":
    """Создаёт и настраивает MCP-сервер с DI-контейнером.

    Шаги:
    1. Создаём FastMCP
    2. Определяем project_root
    3. Создаём DI-контейнер (все зависимости в одном месте)
    4. Регистрируем инструменты (36 шт)
    5. Регистрируем системный prompt
    """
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("MSCodebase Intelligence Server")

    # ─── 0. Process Passport (для отладки) ───────────
    # Печатает RUN_ID + PID + env summary при КАЖДОМ старте.
    # Если в логах MCP RUN_ID отличается от ожидаемого — значит
    # процесс не перезапустился после обновления кода.
    _log_run_passport()

    # ─── 0.5 Health Check LSP (чтобы не было silent crash) ───
    # Проверяем, что LSP-модуль компилируется — если нет,
    # bridge никогда не сработает и проект уйдёт в self-indexing.
    try:
        import py_compile

        _lsp_path = Path(__file__).resolve().parent.parent / "lsp_main.py"
        if _lsp_path.exists():
            py_compile.compile(str(_lsp_path), doraise=True)
            logger.info(f"✅ LSP health check: {_lsp_path.name} compiles OK")
        else:
            logger.warning(f"⚠️ LSP health check: {_lsp_path} not found")
    except py_compile.PyCompileError as _lsp_err:
        logger.critical(
            f"❌ LSP MODULE HAS COMPILE ERROR — bridge will NEVER work!\n"
            f"   File: lsp_main.py\n"
            f"   Error: {_lsp_err}"
        )
        logger.critical(
            f"   Fix: reinstall extension (install.py) or restart Zed.\n"
            f"   Until fixed: extension will self-index instead of your project."
        )
    except Exception:
        pass

    # ─── 1. Project root (default) ────────────────────
    # Используется как fallback если инструмент не передал project_root.
    # Multi-window (INC-6BCB): per-project indexer резолвится в самом
    # инструменте через resolve_indexer_for_request().
    project_root = resolve_project_root()
    global _default_project_root
    _default_project_root = project_root
    logger.info(
        f"🏠 Default project root: {project_root} "
        f"(CWD={Path.cwd().resolve()}, "
        f"PROJECT_PATH={os.environ.get('PROJECT_PATH', 'не установлен')}). "
        f"Per-project indexers via ProjectIndexerRegistry."
    )

    # ─── 2. DI Container (multi-project) ─────────────
    from src.core.di_container import create_service_collection

    services = create_service_collection(project_root)
    global _services_cache
    _services_cache = services

    # Настройка файлового логирования — в _ext_root с явным label "mcp_global".
    # Per-project логи живут в <project>/.codebase_indices/logs/ через
    # Indexer.notification_broker.
    from src.core.log_manager import setup_project_logging

    try:
        setup_project_logging(_ext_root, project_label="mcp_global")
    except Exception as e:
        logger.debug(f"setup_project_logging fallback: {e}")
    logger.info("🚀 MCP-сервер запущен (DI Container ready, multi-window)")

    # ─── 3. Heartbeat (Anti-Orphan) ─────────────────
    _init_heartbeat()

    # ─── 4. Регистрация инструментов ─────────────────
    _register_all_tools(mcp, services)

    # ─── 4. Системный prompt ─────────────────────────
    _register_system_prompt(mcp)

    # ─── 5. Привязка NotificationBroker к сессии ─────
    # Ждём нотификацию initialized от клиента (Zed), после чего
    # сессия JSON-RPC становится доступна через request_context
    _register_notification_broker(mcp, services)

    # ─── 7. Регистрация JSON-RPC методов для Rust-расширения ─
    _register_extension_handlers(mcp, services)

    # ─── 8. Heartbeat хендлер + фоновый мониторинг ──
    _start_heartbeat_monitor(mcp)

    # ─── 9. Авто-индексация при пустом индексе ───────
    _trigger_auto_index_if_empty(services)

    # ─── 10. Фоновая «дозвонка» до LSP bridge ───────
    # Если resolve_project_root упал в fallback на ext_root (race с LSP),
    # через 1.5s попробуем ещё раз прочитать bridge. Если нашли — обновим
    # кэш env и залогируем. Полная переиндексация НЕ запускается автоматически
    # — пользователь должен вызвать index_project_dir().
    # см. INC-6BCB / multi-window race.
    try:
        import threading

        from src.core.lsp_project_bridge import get_bridge_dir, read_project_from_bridge

        def _delayed_bridge_recheck():
            try:
                time.sleep(1.5)
                bridged = read_project_from_bridge(max_wait=2.0)
                if bridged is not None and bridged.resolve() != _ext_root.resolve():
                    # Сбрасываем кэш resolve_project_root — следующий вызов
                    # выберет bridge как приоритет.
                    reset_project_root_cache()
                    logger.info(
                        f"🌉 Delayed bridge recheck: project_root = {bridged} "
                        f"(LSP дозвонился)"
                    )
                else:
                    # Bridge не ответил — диагностируем причину
                    _bridge_log_failure()
            except Exception as br_err:
                logger.debug(f"Delayed bridge recheck: {br_err}")

        def _bridge_log_failure():
            """Диагностика: почему bridge не работает."""
            bridge_dir = get_bridge_dir()
            if not bridge_dir.exists():
                logger.warning("🌉 BRIDGE: директория ~/.mscodebase/bridge/ не создана")
                return
            files = list(bridge_dir.glob("*.json"))
            if not files:
                # Проверка: может Restricted Mode?
                _restricted = False
                try:
                    _db_p = (
                        Path(os.environ.get("LOCALAPPDATA", ""))
                        / "Zed"
                        / "db"
                        / "0-stable"
                        / "db.sqlite"
                    )
                    if _db_p.exists():
                        import sqlite3

                        _c = sqlite3.connect(str(_db_p))
                        _c.row_factory = sqlite3.Row
                        _cur = _c.cursor()
                        _cur.execute(
                            "SELECT paths FROM workspaces WHERE paths != '' AND paths IS NOT NULL ORDER BY timestamp DESC LIMIT 1"
                        )
                        _w = _cur.fetchone()
                        if _w and _w[0]:
                            _proj = _w[0].split(",")[0].strip()
                            _cur.execute(
                                "SELECT COUNT(*) as cnt FROM trusted_worktrees WHERE ? LIKE absolute_path || '%'",
                                (_proj,),
                            )
                            if _cur.fetchone()["cnt"] == 0:
                                _restricted = True
                        _c.close()
                except Exception:
                    pass

                if _restricted:
                    logger.critical(
                        "🌉 BRIDGE: НЕТ JSON-ФАЙЛОВ — LSP НЕ ЗАПУЩЕН!\n"
                        "  Причина: Zed Restricted Mode (Ограниченный режим).\n"
                        "  Проект не добавлен в доверенные.\n"
                        "  Решение:\n"
                        "    Открой проект → нажми 'Trust and Continue'\n"
                        "  Или выполни это в терминале:\n"
                    )
                else:
                    logger.critical(
                        "🌉 BRIDGE: НЕТ JSON-ФАЙЛОВ — LSP НЕ ЗАПИСАЛ project_root!\n"
                        "  Причины:\n"
                        "  1. LSP-сервер 'mscodebase-lsp' не настроен в settings.json\n"
                        "  2. LSP падает при старте (проверь: intel_get_runtime_status)\n"
                        "  3. Файлы Python не открыты — LSP стартует только при\n"
                        "     открытии .py/.rs/... файла в редакторе\n"
                        "  До исправления: проект определён как ext_root (self-indexing)"
                    )
            else:
                logger.warning(
                    f"🌉 BRIDGE: {len(files)} файл(ов) есть, но ни один не "
                    f"содержит project_root. Возможно race condition."
                )

        threading.Thread(
            target=_delayed_bridge_recheck,
            name="mscodebase-bridge-recheck",
            daemon=True,
        ).start()
    except Exception:
        pass

    return mcp


def _register_notification_broker(mcp, services):
    """Привязывает NotificationBroker к JSON-RPC сессии через initialized handler.

    Когда Zed присылает notifications/initialized, session уже создана.
    Захватываем её через request_context и сохраняем в брокере.
    """
    try:
        from mcp.types import InitializedNotification

        from src.core.notification_broker import NotificationBroker

        broker = services.resolve(NotificationBroker)
        server = mcp._mcp_server

        # Также устанавливаем брокер для error_boundary
        from src.core.error_handler import set_notification_broker as _set_err_broker

        _set_err_broker(broker)

        async def _on_initialized(notification: InitializedNotification):
            """Хендлер: клиент подтвердил инициализацию — сессия готова."""
            try:
                # request_context.session доступен только внутри MCP-хендлера
                ctx = server.request_context
                session = ctx.session
                broker.attach_session(session)
            except LookupError:
                logger.warning("Broker: request_context не доступен (вне запроса)")
            except Exception as e:
                logger.error(f"Broker: ошибка захвата сессии: {e}")

        # Регистрируем хендлер на нотификацию initialized
        server.notification_handlers[InitializedNotification] = _on_initialized
        logger.debug("NotificationBroker: хендлер initialized зарегистрирован")

    except Exception as e:
        logger.warning(f"NotificationBroker: не удалось зарегистрировать: {e}")


def _normalize_dashboard_path(path: str) -> str:
    """Нормализует Windows-путь для zed://file/ URI.

    Rust-расширение Zed (особенно под GitBash) ожидает URI с прямыми слэшами.
    Пример: C:\\Users\\misha\\file.py → C:/Users/misha/file.py
    """
    return path.replace("\\", "/")


def _register_extension_handlers(mcp, services):
    """Регистрирует JSON-RPC методы для Rust/WASM расширения.

    Методы:
    - msccodebase/get_dashboard — генерация Markdown дашборда с zed://file/ ссылками
    - msccodebase/force_reindex — принудительная переиндексация
    - msccodebase/clear_memory — очистка кэша памяти
    """
    try:
        server = mcp._mcp_server
        from src.mcp.server import resolve_project_root as _rpr
        from src.mcp.tools.base import resolve_indexer_for_request

        # Multi-window: default project_root для дашборда (per-call tools
        # резолвят свой).
        default_project_root = _rpr()

        if not (
            hasattr(server, "request_handlers")
            and isinstance(server.request_handlers, dict)
        ):
            return

        # ─── msccodebase/get_dashboard ─────────────────────
        async def _handle_get_dashboard(params) -> str:
            """Генерирует Markdown дашборд с НОРМАЛИЗОВАННЫМИ путями.

            Все пути в zed://file/ URI принудительно конвертируются
            из backslashes в forward slashes для совместимости с Zed/GitBash.
            """
            try:
                # Multi-window: резолвим per-project indexer (если передан
                # params.project_root) или default.
                requested_root = (
                    (params or {}).get("project_root", "")
                    if isinstance(params, dict)
                    else ""
                )
                idx = resolve_indexer_for_request(
                    services,
                    explicit_project_root=requested_root or None,
                )
                stats = idx.get_status()
                chunks = stats.get("total_chunks", 0)
                files = stats.get("unique_files", 0)

                # Нормализуем пути для zed://file/ URI
                db_path = _normalize_dashboard_path(str(idx.db_path))
                root = _normalize_dashboard_path(str(idx.project_path))

                md = f"""# 🏗 MSCodeBase Architecture Dashboard

## 📊 Index Status
- **Chunks:** {chunks}
- **Files:** {files}
- **DB:** `{db_path}`

## 📁 Project: {project_root.name}
- [**src/core/**](zed://file/{root}/src/core/)
- [**tests/**](zed://file/{root}/tests/)

## 🛠 Commands
- [Trigger Full Reindex](command:mscodebase:trigger-full-reindex)
- [Clear Memory Cache](command:mscodebase:clear-project-memory)
"""
                return md
            except Exception as e:
                return f"# ❌ Dashboard Error\n\n{str(e)}"

        server.request_handlers["mscodebase/get_dashboard"] = _handle_get_dashboard

        # ─── msccodebase/force_reindex ────────────────────
        async def _handle_force_reindex(params) -> str:
            """Принудительная переиндексация.

            Multi-window: params.project_root задаёт какой проект переиндексировать.
            """
            import asyncio

            try:
                requested_root = (
                    (params or {}).get("project_root", "")
                    if isinstance(params, dict)
                    else ""
                )
                idx = resolve_indexer_for_request(
                    services,
                    explicit_project_root=requested_root or None,
                )
                target = idx.project_path
                indexed = await asyncio.to_thread(idx.index_project, target)
                return f'{{"status": "ok", "files": {indexed}, "project": "{target.name}"}}'
            except Exception as e:
                return f'{{"status": "error", "message": "{e}"}}'

        server.request_handlers["mscodebase/force_reindex"] = _handle_force_reindex

        # ─── msccodebase/clear_memory ─────────────────────
        async def _handle_clear_memory(params) -> str:
            """Очистка кэша памяти проекта (multi-window)."""
            try:
                requested_root = (
                    (params or {}).get("project_root", "")
                    if isinstance(params, dict)
                    else ""
                )
                idx = resolve_indexer_for_request(
                    services,
                    explicit_project_root=requested_root or None,
                )
                if hasattr(idx, "_symbol_index") and idx._symbol_index:
                    idx._symbol_index._definitions.clear()
                return f'{{"status": "ok", "project": "{idx.project_path.name}"}}'
            except Exception as e:
                return f'{{"status": "error", "message": "{e}"}}'

        server.request_handlers["mscodebase/clear_memory"] = _handle_clear_memory

        logger.info("🌉 Extension JSON-RPC handlers registered (3 methods)")

    except Exception as e:
        logger.warning(f"Extension handlers: {e}")


def _trigger_auto_index_if_empty(services):
    """Запускает фоновую индексацию, если индекс пуст.

    Multi-window: индексирует только default project_root (если пустой).
    Остальные проекты индексируются по запросу через index_project_dir.

    Self-indexing guard (INC-6BCB-v2): если project_path == _ext_root
    (т.е. resolve_project_root упал в fallback), НЕ индексируем —
    иначе проиндексируем само расширение (~500MB исходников).
    Ждём реального project_root через bridge / PROJECT_PATH.
    """
    import asyncio

    try:
        from src.mcp.server import resolve_project_root as _rpr
        from src.mcp.tools.base import resolve_indexer_for_request

        try:
            indexer = resolve_indexer_for_request(services)
        except Exception:
            return

        # Self-indexing guard: ext_root означает fallback (project не определён).
        try:
            if indexer.project_path.resolve() == _ext_root.resolve():
                logger.info(
                    "⏸ Auto-index: project_root == ext_root (fallback). "
                    "Пропускаем до появления реального project_root."
                )
                return
        except Exception:
            pass

        status = indexer.get_status()
        if status.get("total_chunks", 0) == 0:
            logger.info("🔄 Индекс пуст — запускаю фоновую индексацию (lazy)...")

            async def _auto_index():
                try:
                    target = indexer.project_path
                    logger.info(f"🔄 Индексация: {target.name}")
                    indexed = await asyncio.to_thread(indexer.index_project, target)
                    logger.info(f"✅ Авто-индексация: {indexed} файлов")
                except Exception as e:
                    logger.warning(f"Авто-индексация не удалась: {e}")
                    logger.info("Выполните index_project_dir(path) вручную")

            # КРИТИЧНО (INC-6BCB): НЕ ВЫЗЫВАЕМ loop.run_until_complete() —
            # он блокирует создание сервера и не даёт Zed ответить по stdio.
            # Если loop ещё не запущен (create_mcp_server вызывается до
            # mcp.run_stdio_async()), индексация будет запущена позже
            # через тот же ensure_future.
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(_auto_index())
                else:
                    # Loop ещё не запущен. НЕ блокируем — просто пропускаем.
                    # Индексация может быть запущена позже через явный вызов.
                    logger.debug(
                        "Event loop не запущен — auto-index будет пропущен. "
                        "Запустите index_project_dir() вручную."
                    )
            except RuntimeError:
                pass
        else:
            logger.info(f"Индекс не пуст ({status.get('total_chunks', 0)} чанков)")
    except Exception as e:
        logger.debug(f"Авто-индексация: {e}")


def _register_all_tools(mcp, services):
    """Регистрирует все 36 MCP-инструментов через DI контейнер.

    Каждый инструмент — отдельный class с constructor injection,
    задекорированный @error_boundary.
    """
    from src.mcp.tools.analysis_tools import (
        GenerateChunkSummariesTool,
        GetRepoMapTool,
        GetRepoRankTool,
        ScanChangesTool,
        StructuralSearchTool,
    )
    from src.mcp.tools.git_tools import (
        GetBranchInfoTool,
        GetCommitHistoryTool,
        GetFileHistoryTool,
    )
    from src.mcp.tools.graph_tools import (
        CrossProjectDepsTool,
        CrossRepoSearchTool,
        GetRelatedFilesTool,
        GraphQueryTool,
    )
    from src.mcp.tools.indexing_tools import (
        IndexHealthTool,
        IndexProjectDirTool,
        NotifyChangeTool,
    )
    from src.mcp.tools.investigation_tools import (
        FindSimilarBugsTool,
        GetBugCorrelationTool,
        GetHotspotsTool,
    )
    from src.mcp.tools.lifecycle_tools import (
        GetTaskStatusTool,
        SubmitBackgroundTaskTool,
        VerifyActionTool,
    )
    from src.mcp.tools.search_tools import (
        GetSymbolInfoTool,
        ImpactAnalysisTool,
        SearchCodeTool,
    )
    from src.mcp.tools.system_tools import (
        GetHealthReportTool,
        GetIndexProgressTool,
        GetIndexStatusTool,
        GetIndexTimelineTool,
        GetLogsTool,
        PredictEtaTool,
        ReadLiveFileTool,
        RunHealthCheckTool,
        WatcherStatusTool,
    )

    # Список всех инструментов для регистрации
    tool_classes = [
        # Search (3)
        SearchCodeTool,
        GetSymbolInfoTool,
        ImpactAnalysisTool,
        # Indexing (3)
        NotifyChangeTool,
        IndexProjectDirTool,
        IndexHealthTool,
        # Git (3)
        GetBranchInfoTool,
        GetCommitHistoryTool,
        GetFileHistoryTool,
        # System (9)
        GetIndexStatusTool,
        GetIndexProgressTool,
        GetIndexTimelineTool,
        WatcherStatusTool,
        GetLogsTool,
        GetHealthReportTool,
        PredictEtaTool,
        RunHealthCheckTool,
        ReadLiveFileTool,
        # Analysis (5)
        StructuralSearchTool,
        GetRepoMapTool,
        GetRepoRankTool,
        ScanChangesTool,
        GenerateChunkSummariesTool,
        # Graph (4)
        CrossRepoSearchTool,
        CrossProjectDepsTool,
        GraphQueryTool,
        GetRelatedFilesTool,
        # Investigation (3)
        GetBugCorrelationTool,
        GetHotspotsTool,
        FindSimilarBugsTool,
        # Lifecycle (3)
        SubmitBackgroundTaskTool,
        GetTaskStatusTool,
        VerifyActionTool,
    ]

    # Регистрируем каждый инструмент.
    # ВАЖНО (INC-6BCB-fallback): try/except вокруг каждого tool,
    # чтобы один сломанный __init__ не убивал все 36.
    registered = 0
    failed = []
    for tool_cls in tool_classes:
        try:
            instance = tool_cls(services)
            mcp.tool(name=instance.name)(instance.execute)
            registered += 1
            logger.debug(f"  🔧 Tool registered: {instance.name}")
        except Exception as e:
            failed.append((tool_cls.__name__, str(e)))
            logger.error(
                f"  ❌ Tool {tool_cls.__name__} failed to register: {e}",
                exc_info=True,
            )
    if failed:
        logger.warning(
            f"⚠️ {len(failed)}/{len(tool_classes)} tools failed to register: "
            f"{[n for n, _ in failed]}"
        )
    else:
        logger.info(f"✅ Все {registered} инструментов зарегистрированы")

    # ─── Intelligence Layer (10 инструментов) ──────
    # Multi-window (INC-6BCB-v2): Indexer/Searcher/SymbolIndex больше НЕ
    # зарегистрированы как singleton (см. di_container.py — Indexer-ы
    # per-project через ProjectIndexerRegistry). Используем
    # resolve_indexer_for_request() для получения per-project инстанса.
    # INC-6BCB-v3.1: передаём services для late-resolve (intel_* tools
    # работают даже если default = self-indexing fallback).
    try:
        from src.core.intelligence_layer import (
            ProjectIntelligenceLayer,
            register_intelligence_tools,
        )
        from src.mcp.tools.base import _is_self_index_path, resolve_indexer_for_request

        idx = resolve_indexer_for_request(services)
        intel_layer = ProjectIntelligenceLayer(
            project_path=idx.project_path,
            indexer=idx,
            searcher=idx.searcher,
            symbol_index=idx._symbol_index,
            services=services,  # INC-6BCB-v3.1
        )
        register_intelligence_tools(mcp, intel_layer)
        logger.info("  🧠 Intel tools registered (10 tools)")
    except Exception as e:
        logger.warning(f"  ⚠️ Intel layer not registered: {e}")

    logger.info(f"✅ Все инструменты зарегистрированы ({len(tool_classes)}+10)")

    # ─── Debug tool: passport ────────────────────
    # Возвращает JSON с RUN_ID, PID, env summary. Полезно для отладки
    # 'кэширован ли MCP' и 'правильный ли ext_root' прямо из чата.
    @mcp.tool("debug_runtime_passport")
    async def debug_runtime_passport() -> str:
        """Диагностика: возвращает 'паспорт' текущего процесса MCP.

        Если RUN_ID в ответе отличается от ожидаемого — значит процесс
        не перезапустился после обновления кода (Zed держит старый).
        """
        import getpass

        from src.mcp.server import (
            _BUILD_ID,
            _RUN_ID,
            _RUN_PID,
            _RUN_SOURCE_FILE,
            _RUN_STARTED_AT,
            _default_project_root,
            _ext_root,
            _services_cache,
        )
        from src.utils.ui_formatter import _val, header, section

        pr = _default_project_root or resolve_project_root()

        # Bridge state
        _bridge = None
        _bridge_err = None
        try:
            from src.core.lsp_project_bridge import read_project_from_bridge

            _bridge = str(read_project_from_bridge(max_wait=0.1))
        except Exception as e:
            _bridge_err = str(e)

        # Registry state
        _registry_paths: list[str] = []
        _registry_state_info: dict[str, Any] = {}
        _project_state: str = "UNKNOWN"
        try:
            from src.core.di_container import ProjectIndexerRegistry as PIRKey
            from src.core.project_indexer_registry import ProjectState

            if _services_cache is not None:
                _reg = _services_cache.resolve(PIRKey)
                _registry_paths = [str(p) for p in _reg.get_all_paths()]
                _registry_state_info = _reg.get_stats()
                # State for default project
                _st = _reg.get_state(pr)
                _project_state = _st.name
        except Exception as e:
            _project_state = f"ERROR: {e}"

        uptime_sec = round(time.time() - _RUN_STARTED_AT, 1)

        result = header("debug_runtime_passport", "ok")

        result += section("🧬 Process")
        result += f"• **RUN_ID:** `{_val(_RUN_ID)}`\n"
        result += f"• **BUILD_ID:** `{_val(_BUILD_ID, '<no git>')}`\n"
        result += f"• **PID:** `{_RUN_PID}`\n"
        result += (
            f"• **Started:** `{datetime.fromtimestamp(_RUN_STARTED_AT).isoformat()}`\n"
        )
        result += f"• **Uptime:** `{uptime_sec}s`\n"
        result += f"• **Source:** `{_val(_RUN_SOURCE_FILE)}`\n"
        result += f"• **User:** `{getpass.getuser()}`\n"

        result += section("🗂 Project")
        result += f"• **CWD:** `{_val(str(Path.cwd().resolve()))}`\n"
        result += f"• **Ext Root:** `{_val(str(_ext_root))}`\n"
        result += f"• **Default Project:** `{_val(str(pr))}`\n"
        result += f"• **Project State:** `{_val(_project_state)}`\n"

        result += section("🔗 Bridge")
        result += f"• **State:** {_val(_bridge)}\n"
        if _bridge_err:
            result += f"• **Error:** `{_val(_bridge_err)}`\n"

        result += section("📦 Registry")
        result += (
            f"• **Paths:** {', '.join(_registry_paths) if _registry_paths else '—'}\n"
        )
        result += f"• **Cached Projects:** `{_registry_state_info.get('cached_projects', 0)}`\n"
        result += f"• **Cache Hits:** `{_registry_state_info.get('cache_hits', 0)}`\n"
        result += (
            f"• **Cache Misses:** `{_registry_state_info.get('cache_misses', 0)}`\n"
        )

        result += section("🌱 Env")
        result += f"• **PROJECT_PATH:** `{_val(os.environ.get('PROJECT_PATH'))}`\n"
        result += (
            f"• **ZED_WORKTREE_ROOT:** `{_val(os.environ.get('ZED_WORKTREE_ROOT'))}`\n"
        )
        result += f"• **MSCODEBASE_ALLOW_SELF_INDEX:** `{_val(os.environ.get('MSCODEBASE_ALLOW_SELF_INDEX'))}`\n"
        _pp = (os.environ.get("PYTHONPATH") or "").split(os.pathsep)[0] or None
        result += f"• **PYTHONPATH[0]:** `{_val(_pp)}`\n"
        result += f"• **Self-Index Guard:** `{_is_self_index_path(pr)}`\n"

        return result

    # ─── Project Context tool (Intel Layer) ──────
    # Единый снэпшот проекта: state + index + bridge + health + memory + jobs
    @mcp.tool("intel_get_project_context")
    async def intel_get_project_context(project_root: str = "") -> str:
        """Единый снэпшот состояния проекта: state, index, bridge, health,
        memory (incidents/ADRs) и фоновые задачи — одним вызовом.

        Args:
            project_root: путь к проекту (по умолчанию — текущий проект).

        Returns:
            JSON со всей известной информацией о проекте.
        """
        from src.core.project_context import ProjectContext

        _default = _default_project_root or resolve_project_root()
        target = Path(project_root).resolve() if project_root else _default
        ctx = ProjectContext(target, services)
        snap = await ctx.capture()
        return json.dumps(snap.to_dict(), ensure_ascii=False, indent=2)

    # ─── Explain Project State (human-readable) ──────
    @mcp.tool("intel_explain_project_state")
    async def intel_explain_project_state(project_root: str = "") -> str:
        """Человекочитаемый диагноз состояния проекта.

        В отличие от intel_get_project_context (который возвращает JSON),
        этот инструмент возвращает текст для пользователя:
          ✓ Project READY — всё хорошо
          ✗ Cannot execute — с указанием причины и что делать

        Args:
            project_root: путь к проекту (по умолчанию — текущий).

        Returns:
            Текстовый диагноз с состоянием каждого слоя.
        """
        from src.core.project_context import ProjectContext
        from src.core.runtime_coordinator import RuntimeCoordinator

        _default = _default_project_root or resolve_project_root()
        target = Path(project_root).resolve() if project_root else _default

        coord = RuntimeCoordinator(services)
        verdict = await coord.can_execute(target)

        ctx = ProjectContext(target, services)
        snap = await ctx.capture()

        lines = [
            f"📂 Project: {target}",
            f"",
            f"=== State: {verdict.state} ===",
            f"",
        ]

        if verdict.ok:
            lines.append(f"✅ Ready to execute")
        else:
            lines.append(f"❌ Cannot execute: {verdict.reason}")
            lines.append(f"   {verdict.detail}")

        lines.append("")
        lines.append(f"── Index ──")
        lines.append(f"  Chunks: {snap.index_chunks or 0}")
        lines.append(f"  Files:  {snap.index_files or 0}")
        lines.append(f"  Symbols: {snap.index_symbols or 0}")
        lines.append(f"  Embedder: {snap.index_embedder or 'N/A'}")

        lines.append(f"")
        lines.append(f"── Bridge ──")
        if snap.bridge_synced:
            lines.append(f"  ✅ LSP synchronized: {snap.bridge_path}")
        else:
            lines.append(f"  ❌ LSP not synced")

        lines.append(f"")
        lines.append(f"── Runtime ──")
        lines.append(f"  PID: {snap.runtime_pid or 'N/A'}")
        lines.append(f"  Uptime: {snap.runtime_uptime or 0}s")

        lines.append(f"")
        lines.append(f"── Health ──")
        if snap.health_ok:
            lines.append(f"  ✅ OK")
        if snap.health_warnings:
            for w in snap.health_warnings[:5]:
                lines.append(f"  ⚠️  {w}")
        if snap.health_errors:
            for e in snap.health_errors[:5]:
                lines.append(f"  ❌ {e}")

        lines.append(f"")
        lines.append(f"── Memory ──")
        lines.append(f"  Incidents: {snap.memory_incidents}")
        lines.append(f"  ADRs: {snap.memory_adrs}")
        lines.append(f"  Known issues: {snap.memory_known_issues}")

        if verdict.warnings:
            lines.append(f"")
            lines.append(f"── Warnings ──")
            for w in verdict.warnings:
                lines.append(f"  ⚠️  {w}")

        if verdict.requires_reindex:
            lines.append(f"")
            lines.append(f"── Action Required ──")
            lines.append(
                f"  Run intel_trigger_reindex() then check status via intel_get_job_status()"
            )

        if not verdict.requires_bridge_sync and snap.bridge_path:
            lines.append(f"")
            lines.append(f"── Bridge path ──")
            lines.append(f"  LSP workspace: {snap.bridge_path}")

        return chr(10).join(lines)

    # --- Runtime Counters (telemetry) ---
    @mcp.tool("get_runtime_counters")
    async def get_runtime_counters() -> str:
        """Возвращает счётчики runtime: сколько запросов выполнено,
        сколько отклонено и по какой причине.

        Позволяет оценить реальный эффект архитектурных изменений:
        - can_execute_calls: всего проверок готовности
        - verdict_ready: сколько разрешено
        - verdict_blocked_*: сколько отклонено и почему
        - warnings_*: сколько предупреждений каждого типа

        Если blocked > 5% от calls — архитектура требует внимания.
        """
        from src.core.runtime_coordinator import get_counters
        from src.utils.ui_formatter import header, section

        counters = get_counters()
        result = header("Runtime Counters", "ok")
        result += section("📊 Состояние")
        calls = counters.get("can_execute_calls", 0)
        ready = counters.get("verdict_ready", 0)
        blocked_pct = round((1 - ready / max(calls, 1)) * 100, 1)
        result += f"• **Проверок:** {calls} | **Готов:** {ready} | **Блокировано:** {blocked_pct}%\n"

        result += section("🚫 Блокировки")
        for k, v in counters.items():
            if k.startswith("verdict_blocked_") and v:
                reason = k.replace("verdict_blocked_", "").replace("_", " ")
                result += f"• {reason}: {v}\n"

        result += section("⚠️ Предупреждения")
        has_warnings = False
        for k, v in counters.items():
            if k.startswith("warnings_") and v:
                w = k.replace("warnings_", "").replace("_", " ")
                result += f"• {w}: {v}\n"
                has_warnings = True
        if not has_warnings:
            result += "• Нет предупреждений\n"

        result += section("⏱ Производительность")
        result += f"• **Ожидание:** {counters.get('total_wait_time_sec', 0):.1f}с\n"
        return result

    # --- Telemetry History ---
    @mcp.tool("intel_get_telemetry")
    async def intel_get_telemetry(days: int = 7) -> str:
        """Возвращает историю метрик за последние N дней.

        Данные собираются скриптом scripts/collect_telemetry.py
        (разовый запуск или ежедневно через планировщик Windows).

        Args:
            days: количество дней истории (по умолчанию 7).

        Returns:
            JSON с историей метрик для построения графиков.
        """
        import json

        from scripts.collect_telemetry import get_history

        history = get_history(min(max(days, 1), 365))
        return json.dumps(history, ensure_ascii=False, indent=2)


def _register_system_prompt(mcp):
    """Регистрирует mscodebase-rules prompt для AI-агента."""
    from src.core.config import get_config

    mcp_prompt_text = """
# MSCODEBASE INTELLIGENCE CORE SYSTEM RULES

You operate under a strict deterministic execution matrix...

## 1. MCP PRIORITY RULES
- For ANY question about code → `search_code` FIRST
- If `get_index_status` returns chunks=0 → index_project_dir first
- If chunks > 0 → search_code for semantic, get_symbol_info for exact

## 2. RECONNAISSANCE BEFORE ACTION
- NEVER guess line numbers. Use get_symbol_info or grep before read_file.
- CONTEXT BUDGET: maximum 50 lines per read_file call.
- NEVER ingest entire files.

## 3. ERROR HANDLING
- If MCP tool returns error → pivot, don't retry same params
- Use get_logs for diagnostics
- Report exact error signatures

## 4. PATH PROTOCOL
- Native Windows paths (backslashes) for MCP tools
- Relative paths for notify_change (from project root)
- Absolute paths for project_root params
"""
    mcp.prompt(
        name="mscodebase-rules",
        description="Системные правила для работы с кодовой базой MSCodeBase",
    )(lambda: mcp_prompt_text)


# ══════════════════════════════════════════════════════════
# Heartbeat — Anti-Orphan защита
# Вынесено в DI-класс (см. INC-53EC / REFC-11): глобальные переменные
# на module-level ломались при двух инстансах MCP (global+project).
# ══════════════════════════════════════════════════════════


class HeartbeatService:
    """Heartbeat-сервис для Anti-Orphan защиты.

    Идемпотентен: можно создавать несколько экземпляров (например, для
    отдельных MCP-инстансов). Все состояние инкапсулировано.
    """

    def __init__(
        self,
        interval: float = 30.0,
        timeout: float = 90.0,
        check_interval: float = 15.0,
    ):
        self.interval = interval
        self.timeout = timeout
        self.check_interval = check_interval
        self._parent_pid: Optional[int] = None
        self._last_heartbeat_time: float = 0.0
        self._task: Optional[asyncio.Task] = None
        self._lock = threading.Lock()
        self._running = False

    def init(self) -> None:
        """Захватываем родительский PID при старте."""
        with self._lock:
            self._parent_pid = os.getppid()
            self._last_heartbeat_time = time.time()
        logger.info(f"💓 Heartbeat инициализирован. Parent PID: {self._parent_pid}")

    def beat(self) -> None:
        """Обновляет время последнего heartbeat (вызов из хендлера)."""
        with self._lock:
            self._last_heartbeat_time = time.time()

    def is_parent_alive(self) -> bool:
        """Проверяет, жив ли родительский процесс."""
        with self._lock:
            pid = self._parent_pid
        if pid is None:
            return True
        try:
            if sys.platform == "win32":
                import ctypes

                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(
                    0x0400, False, pid
                )  # PROCESS_QUERY_INFORMATION
                if handle:
                    kernel32.CloseHandle(handle)
                    return True
                return kernel32.GetLastError() != 87  # ERROR_INVALID_PARAMETER = мёртв
            else:
                os.kill(pid, 0)
                return True
        except (ProcessLookupError, PermissionError, OSError):
            return False
        except Exception:
            return True  # fallback: не можем проверить — считаем живым

    async def _monitor(self) -> None:
        """Фоновая задача: проверяет здоровье соединения."""
        logger.info(
            f"💓 Heartbeat monitor запущен "
            f"(check={self.check_interval}s, timeout={self.timeout}s)"
        )
        while self._running:
            await asyncio.sleep(self.check_interval)
            try:
                with self._lock:
                    elapsed = time.time() - self._last_heartbeat_time
                if elapsed > self.timeout:
                    logger.warning(f"💔 Heartbeat таймаут: {elapsed:.0f}s без пинга")
                    self._shutdown(f"Heartbeat timeout: {elapsed:.0f}s")
                    return
                if not self.is_parent_alive():
                    logger.warning(
                        f"💔 Родительский процесс (Zed) мёртв (PID: {self._parent_pid})"
                    )
                    self._shutdown("Parent process died")
                    return
            except asyncio.CancelledError:
                logger.info("💓 Heartbeat monitor остановлен")
                return
            except Exception as e:
                logger.error(f"Heartbeat monitor error: {e}")

    def _shutdown(self, reason: str) -> None:
        """Graceful shutdown: сначала atexit-обработчики, потом _exit."""
        logger.warning(f"🛑 Graceful shutdown: {reason}")
        try:
            from src.core.index_guard import IndexGuard

            db_path = Path.cwd() / ".codebase_indices" / "lancedb_v2"
            if db_path.exists():
                IndexGuard(db_path, Path.cwd())
        except Exception:
            pass
        # atexit-обработчики (SafePathManager.cleanup и т.д.) сработают
        # только при sys.exit. os._exit их обходит, теряя данные.
        # Мы всё равно вызываем os._exit потому что FastMCP застрял
        # в stdio-блокирующем режиме и не реагирует на sys.exit.
        # Но в начале пытаемся дать шанс atexit.
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        os._exit(0)

    def start_monitor(self) -> None:
        """Запускает фоновый мониторинг (если ещё не запущен)."""
        with self._lock:
            if self._running:
                return
            self._running = True
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                self._task = asyncio.ensure_future(self._monitor())
                logger.info("💓 Heartbeat monitor started")
        except RuntimeError:
            logger.debug("Heartbeat monitor: event loop not ready")


# Глобальный экземпляр для обратной совместимости с существующими вызовами.
_heartbeat_service = HeartbeatService()


def _init_heartbeat() -> None:
    _heartbeat_service.init()


def _update_heartbeat() -> None:
    _heartbeat_service.beat()


def _is_parent_alive() -> bool:
    return _heartbeat_service.is_parent_alive()


async def _heartbeat_monitor() -> None:
    await _heartbeat_service._monitor()


def _graceful_shutdown(reason: str) -> None:
    _heartbeat_service._shutdown(reason)


def _start_heartbeat_monitor(mcp) -> None:
    """Регистрирует хендлер heartbeat и запускает фоновый мониторинг."""
    try:
        server = mcp._mcp_server
        if hasattr(server, "request_handlers") and isinstance(
            server.request_handlers, dict
        ):

            async def _on_heartbeat(params):
                _update_heartbeat()
                return {}

            server.request_handlers["mscodebase/heartbeat"] = _on_heartbeat
            logger.debug("💓 Heartbeat handler registered")

        _heartbeat_service.start_monitor()
    except Exception as e:
        logger.warning(f"Heartbeat: {e}")


# ══════════════════════════════════════════════════════════
# Точка входа
# ══════════════════════════════════════════════════════════


def run_server(original_stdout=None):
    """Запускает MCP-сервер через stdio."""
    mcp = create_mcp_server()
    if mcp:
        try:
            if original_stdout:
                sys.stdout = original_stdout
            asyncio.run(mcp.run_stdio_async())
        except KeyboardInterrupt:
            logger.info("Сервер остановлен пользователем.")
        except Exception as e:
            logger.critical(f"Критический сбой MCP-сервера: {e}", exc_info=True)
