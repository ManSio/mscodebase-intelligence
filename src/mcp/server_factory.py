"""
server_factory.py — Жизненный цикл MCP-сервера.

Lazy-импорты из server.py для избежания циклических зависимостей.
"""
from __future__ import annotations

import asyncio
import atexit
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("mscodebase_server")


# ══════════════════════════════════════════════════════════
# Heartbeat — Anti-Orphan защита
# ══════════════════════════════════════════════════════════


class HeartbeatService:
    """Heartbeat-сервис для Anti-Orphan защиты."""

    def __init__(self, interval=30.0, timeout=90.0, check_interval=15.0):
        self.interval = interval
        self.timeout = timeout
        self.check_interval = check_interval
        self._parent_pid: Optional[int] = None
        self._last_heartbeat_time: float = 0.0
        self._task: Optional[asyncio.Task] = None
        self._lock = threading.Lock()
        self._running = False

    def init(self) -> None:
        with self._lock:
            self._parent_pid = os.getppid()
            self._last_heartbeat_time = time.time()
        logger.info(f"💓 Heartbeat инициализирован. Parent PID: {self._parent_pid}")

    def beat(self) -> None:
        with self._lock:
            self._last_heartbeat_time = time.time()

    def is_parent_alive(self) -> bool:
        with self._lock:
            pid = self._parent_pid
        if pid is None:
            return True
        try:
            if sys.platform == "win32":
                import ctypes
                handle = ctypes.windll.kernel32.OpenProcess(0x0400, False, pid)
                if handle:
                    ctypes.windll.kernel32.CloseHandle(handle)
                    return True
                return ctypes.windll.kernel32.GetLastError() != 87
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError, OSError):
            return False
        except Exception:
            return True

    async def _monitor(self) -> None:
        logger.info(f"💓 Heartbeat monitor (check={self.check_interval}s, timeout={self.timeout}s)")
        try:
            while self._running:
                await asyncio.sleep(self.check_interval)
                with self._lock:
                    elapsed = time.time() - self._last_heartbeat_time
                if elapsed > self.timeout:
                    logger.warning(f"💔 Heartbeat таймаут: {elapsed:.0f}s")
                    self._shutdown(f"Heartbeat timeout: {elapsed:.0f}s")
                    return
                if not self.is_parent_alive():
                    logger.warning(f"💔 Parent PID {self._parent_pid} dead")
                    self._shutdown("Parent process died")
                    return
        except asyncio.CancelledError:
            logger.info("💓 Heartbeat monitor остановлен")
        except Exception as e:
            logger.error(f"Heartbeat error: {e}")
        finally:
            with self._lock:
                self._running = False

    def _shutdown(self, reason: str) -> None:
        """Graceful shutdown — atexit и finally сработают корректно."""
        logger.warning(f"🛑 Graceful shutdown: {reason}")
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        try:
            _shutdown_services()
        except Exception as _e:
            logger.warning("exception", exc_info=True)
        sys.exit(0)

    def start_monitor(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                self._task = asyncio.ensure_future(self._monitor())
                self._task.add_done_callback(lambda _: None)
        except RuntimeError:
            pass


_heartbeat_service = HeartbeatService()


def init_heartbeat():
    _heartbeat_service.init()


def update_heartbeat():
    _heartbeat_service.beat()


def start_heartbeat_monitor(mcp):
    try:
        server = mcp._mcp_server
        if hasattr(server, "request_handlers") and isinstance(server.request_handlers, dict):
            async def _on_heartbeat(params):
                update_heartbeat()
                return {}
            server.request_handlers["mscodebase/heartbeat"] = _on_heartbeat
        _heartbeat_service.start_monitor()
    except Exception as e:
        logger.warning(f"Heartbeat: {e}")


# ══════════════════════════════════════════════════════════
# Создание MCP-сервера (lazy-импорты server.py)
# ══════════════════════════════════════════════════════════


def create_mcp_server():
    """Создаёт и настраивает MCP-сервер с DI-контейнером."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("MSCodebase Intelligence Server")

    # Lazy импорты из server.py (избегаем циклической зависимости)
    from src.mcp.server import (
        _check_source_extension_sync,
        _ext_root,
        _log_run_passport,
        resolve_project_root,
    )
    from src.mcp.server_tools import register_all_tools, register_system_prompt

    _log_run_passport()

    warning = _check_source_extension_sync()
    if warning:
        logger.warning(warning)

    try:
        import py_compile
        lsp_path = Path(__file__).resolve().parent.parent / "lsp_main.py"
        if lsp_path.exists():
            py_compile.compile(str(lsp_path), doraise=True)
    except py_compile.PyCompileError as err:
        logger.critical(f"❌ LSP HAS COMPILE ERROR: {err}")
    except Exception as _e:
        logger.warning("exception", exc_info=True)
        pass
    project_root = resolve_project_root()
    # Sanitization guard: if path has \n (Zed multi-root bug), pick last valid dir.
    _pr_str = str(project_root)
    if "\n" in _pr_str:
        _parts = _pr_str.split("\n")
        logger.warning(f"project_root contains newline ({len(_parts)} parts)")
        _found = None
        for _p in reversed(_parts):
            _p = _p.strip()
            if _p and Path(_p).is_dir():
                _found = Path(_p).resolve()
                break
        project_root = _found or Path(_pr_str.split("\n")[0].strip()).resolve()
        logger.warning(f"  -> sanitized: {project_root}")
    # FIX: обновляем модульный атрибут напрямую (from...import создаёт локальную копию)
    import src.mcp.server as _srv
    _srv._default_project_root = project_root
    _srv._services_cache = None  # будет заполнен ниже

    from src.core.di_container import create_service_collection
    services = create_service_collection(project_root)
    _srv._services_cache = services

    locale = os.environ.get("MSCODEBASE_LOCALE", "")
    if not locale:
        try:
            env_file = _ext_root / ".env"
            if env_file.exists():
                for line in env_file.read_text(encoding='utf-8').splitlines():
                    if line.startswith("MSCODEBASE_LOCALE="):
                        locale = line.split("=", 1)[1].strip()
                        break
        except Exception as _e:
            logger.warning("exception", exc_info=True)
            pass
    from src.utils.i18n import set_locale
    set_locale(locale or "en")

    from src.core.log_manager import setup_project_logging
    try:
        setup_project_logging(_ext_root, project_label="mcp_global")
    except Exception as e:
        logger.debug(f"setup_project_logging fallback: {e}")

    from src.core.task_queue import enable_idle_scheduler, get_task_queue
    enable_idle_scheduler()
    try:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(get_task_queue().start())
        except RuntimeError:
            # Нет event loop — create_mcp_server вызван синхронно ДО asyncio.run().
            # task_queue запустится автоматически при старте event loop через
            # asyncio.run(mcp.run_stdio_async()).
            pass
    except Exception as _e:
        logger.warning("exception", exc_info=True)
        pass
    from src.core.error_handler import set_metrics_path
    set_metrics_path(_ext_root / "telemetry" / "tool_metrics.json")

    init_heartbeat()
    register_all_tools(mcp, services)
    register_system_prompt(mcp)
    _register_notification_broker(mcp, services)
    _register_extension_handlers(mcp, services)
    start_heartbeat_monitor(mcp)
    # Auto-index НЕ вызываем здесь — event loop ещё не запущен.
    # Вызов будет в run_server() после asyncio.run().
    _start_delayed_bridge_recheck(services)

    return mcp


# ══════════════════════════════════════════════════════════
# NotificationBroker, Extension handlers, Auto-index
# ══════════════════════════════════════════════════════════


def _register_notification_broker(mcp, services):
    try:
        from mcp.types import InitializedNotification

        from src.core.notification_broker import NotificationBroker
        broker = services.resolve(NotificationBroker)
        server = mcp._mcp_server
        from src.core.error_handler import set_notification_broker
        set_notification_broker(broker)

        async def _on_init(notification: InitializedNotification):
            try:
                broker.attach_session(server.request_context.session)
            except LookupError:
                logger.warning("Broker: request_context не доступен")
            except Exception as e:
                logger.error(f"Broker: {e}")

        server.notification_handlers[InitializedNotification] = _on_init
        logger.debug("NotificationBroker: initialized handler registered")
    except Exception as e:
        logger.warning(f"NotificationBroker: {e}")


def _register_extension_handlers(mcp, services):
    try:
        server = mcp._mcp_server
        from src.mcp.tools.base import resolve_indexer_for_request
        if not (hasattr(server, "request_handlers") and isinstance(server.request_handlers, dict)):
            return

        async def _get_dashboard(params) -> str:
            try:
                root = (params or {}).get("project_root", "") if isinstance(params, dict) else ""
                idx = resolve_indexer_for_request(services, explicit_project_root=root or None)
                s = idx.get_status()
                return f"# Index Status\nChunks: {s.get('total_chunks', 0)}\nFiles: {s.get('unique_files', 0)}"
            except Exception as e:
                return f"# Error\n{str(e)}"

        async def _force_reindex(params) -> str:
            try:
                root = (params or {}).get("project_root", "") if isinstance(params, dict) else ""
                idx = resolve_indexer_for_request(services, explicit_project_root=root or None)
                count = await asyncio.to_thread(idx.index_project, idx.project_path)
                return f'{{"status": "ok", "files": {count}}}'
            except Exception as e:
                return f'{{"status": "error", "message": "{e}"}}'

        async def _clear_memory(params) -> str:
            try:
                root = (params or {}).get("project_root", "") if isinstance(params, dict) else ""
                idx = resolve_indexer_for_request(services, explicit_project_root=root or None)
                if hasattr(idx, "_symbol_index") and idx._symbol_index:
                    idx._symbol_index._definitions.clear()
                return '{"status": "ok"}'
            except Exception as e:
                return f'{{"status": "error", "message": "{e}"}}'

        server.request_handlers["mscodebase/get_dashboard"] = _get_dashboard
        server.request_handlers["mscodebase/force_reindex"] = _force_reindex
        server.request_handlers["mscodebase/clear_memory"] = _clear_memory
        logger.info("🌉 Extension handlers registered (3 methods)")
    except Exception as e:
        logger.warning(f"Extension handlers: {e}")





def _start_delayed_bridge_recheck(services):
    try:
        from src.core.lsp_project_bridge import read_project_from_bridge

        def _recheck():
            try:
                time.sleep(1.5)
                bridged = read_project_from_bridge(max_wait=2.0)
                from src.mcp.server import _ext_root, reset_project_root_cache
                if bridged and bridged.resolve() != _ext_root.resolve():
                    reset_project_root_cache()
                    logger.info(f"🌉 Delayed recheck: project_root = {bridged}")
            except Exception as _e:
                logger.warning("exception", exc_info=True)
                pass
        threading.Thread(target=_recheck, name="bridge-recheck", daemon=True).start()
    except Exception as _e:
        logger.warning("exception", exc_info=True)
        pass
# ══════════════════════════════════════════════════════════
# run_server — точка входа stdio
# ══════════════════════════════════════════════════════════


def run_server(original_stdout=None):
    """Запускает MCP-сервер через stdio."""
    mcp = create_mcp_server()
    if not mcp:
        return

    try:
        atexit.register(lambda: _shutdown_services())

        # Всегда запускаем reranker (не зависит от провайдера эмбеддинга)
        _start_llama_sync()

        # ─── Contradiction Ledger (auto-verify AGENT_DIARY on startup) ───
        _start_contradiction_ledger_background()

        if original_stdout:
            sys.stdout = original_stdout

        # Запускаем MCP внутри async-функции, где event loop уже работает
        async def _run_with_auto_index():
            from src.mcp.server import _services_cache
            # Auto-index — event loop УЖЕ запущен -> create_task сработает
            if _services_cache is not None:
                asyncio.create_task(_delayed_auto_index(_services_cache))
            await mcp.run_stdio_async()

        asyncio.run(_run_with_auto_index())
    except KeyboardInterrupt:
        logger.info("Сервер остановлен пользователем.")
    except Exception as e:
        logger.critical(f"Критический сбой: {e}", exc_info=True)
    finally:
        _shutdown_services()


async def _delayed_auto_index(services):
    """Запускает автоиндексацию с задержкой после старта сервера.

    Вызывается из run_server() после asyncio.run(), когда event loop УЖЕ запущен.
    """
    try:
        from src.mcp.tools.base import resolve_indexer_for_request
        indexer = resolve_indexer_for_request(services)
        if indexer is None:
            return

        from src.mcp.server import _ext_root
        try:
            if indexer.project_path.resolve() == _ext_root.resolve():
                logger.info("⏸ Auto-index: project_root == ext_root, пропускаем")
                return
        except Exception:
            pass

        status = indexer.get_status()
        if status.get("total_chunks", 0) > 0:
            logger.info(f"⏸ Auto-index: индекс не пуст ({status.get('total_chunks', 0)} чанков), пропускаем")
            return

        # Ждём готовности рантайма
        await asyncio.sleep(1.5)

        from src.mcp.server import _ext_root
        if indexer.project_path.resolve() == _ext_root.resolve():
            logger.info("⏸ Auto-index: project_root == ext_root, пропускаем")
            return

        logger.info("🚀 Auto-index: starting background indexing task")

        # Guard (AGENTS.md §5.13): запрещаем concurrent search
        _dbm = getattr(indexer, "db_manager", None)
        if _dbm is not None and hasattr(_dbm, "set_reindexing"):
            _dbm.set_reindexing()
        try:
            c = await asyncio.to_thread(indexer.index_project, indexer.project_path)
            logger.info(f"✅ Auto-index: completed ({c} files)")
        finally:
            if _dbm is not None and hasattr(_dbm, "clear_reindexing"):
                _dbm.clear_reindexing()
    except Exception as e:
        logger.warning(f"Auto-index: {e}", exc_info=True)


def _start_contradiction_ledger_background() -> None:
    """Фоновая проверка AGENT_DIARY.md против реального кода при старте MCP.

    Не блокирует старт сервера (stdio). Результат логируется:
    - ok=True: все "✅ done" из дневника верифицированы
    - ok=False: расхождения (устаревший диари, незапушенный коммит и т.п.)

    Ждёт 2s перед первым resolve — даёт SQLite bridge инициализироваться.
    """
    try:
        import threading

        def _run():
            try:
                import time as _time

                import scripts.verify_diary as vd
                # Ждём 2s — bridge/SQLite могут не быть готовы при冷 старте.
                # Этот паттерн повторяет _start_delayed_bridge_recheck.
                _time.sleep(2)
                _proj = _resolve_ledger_project_root()
                if _proj is None:
                    logger.warning("Contradiction Ledger: project_root не найден (resolve вернул None)")
                    return
                logger.info(f"Contradiction Ledger: project_root = {_proj}")
                # Guard: не проверяем сам расширение
                try:
                    from src.mcp.server import _ext_root
                    if _proj.resolve() == _ext_root.resolve():
                        logger.warning(f"Contradiction Ledger: project_root == ext_root ({_proj}), пропускаю")
                        return
                except Exception:
                    pass
                logger.info("Contradiction Ledger: calling run_contradiction_ledger()...")
                res = vd.run_contradiction_ledger(_proj)
                logger.info(f"Contradiction Ledger: result received, ok={res['ok']}, claims={res['claims']}")
                if res["ok"]:
                    logger.info(
                        f"✅ Contradiction Ledger: утверждения AGENT_DIARY.md "
                        f"верифицированы ({res['claims']} claims, {res['commits']} commits)"
                    )
                else:
                    logger.warning(
                        f"⚠️ Contradiction Ledger: {len(res['discrepancies'])} расхождений "
                        f"в AGENT_DIARY.md:"
                    )
                    for d in res["discrepancies"][:10]:
                        logger.warning(f"   → {d}")
            except Exception as _e:
                logger.warning(f"Contradiction Ledger не запустился: {_e}")

        t = threading.Thread(target=_run, name="contradiction-ledger", daemon=True)
        t.start()
        logger.info("🔍 Contradiction Ledger запущен в фоне (ожидание 2s для bridge init)")
    except Exception as _e:
        logger.warning(f"Не удалось запустить Contradiction Ledger: {_e}")


def _resolve_ledger_project_root():
    """Возвращает путь к проекту пользователя (где лежит AGENT_DIARY.md).

    Использует resolve_project_root() из server.py — единственный надёжный
    резолвер (SQLite bridge + env + fallback). _default_project_root в
    server_factory.py — ЛОКАЛЬНАЯ переменная (баг F811), не обновляет модуль.

    Ранее использовал самодельный резолвер, который падал из-за:
    - пустого registry при старте
    - literal string '$ZED_WORKTREE_ROOT' в env (не раскрыта shell'ом)
    - ext_root guard блокировал fallback на CWD
    """
    try:
        from src.mcp.server import _ext_root, resolve_project_root
        p = resolve_project_root()
        if p and p.resolve() != _ext_root.resolve():
            return p
    except Exception as _e:
        logger.debug(f"resolve_project_root failed for ledger: {_e}")
    return None


def _start_llama_sync():
    """Синхронный запуск llama.cpp при старте.

    Управляется тумблером LLAMA_CPP_ENABLED (config.py / .env).
    По умолчанию выключен — embedder (порт 8080) не поднимается.
    """
    try:
        from src.config.settings import get_config

        if not get_config().embedding.llama_cpp_enabled:
            logger.info("🦙 llama.cpp отключён (LLAMA_CPP_ENABLED=false). Пропускаю авто-запуск.")
            return
    except Exception as _cfg_err:
        logger.warning(f"llama toggle check failed: {_cfg_err}")

    try:
        import httpx

        from src.providers.reranker.llama_install import is_compatible
        from src.providers.reranker.llama_runner import (
            DEFAULT_EMBEDDING_MODEL,
            get_global_runner,
        )
        runner = get_global_runner()
        model = os.getenv("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
        if is_compatible() and not runner.is_alive():
            logger.info(f"🦙 Запуск llama.cpp ({model})...")
            ok = runner._start_sync(model)
            if ok:
                for _ in range(40):
                    try:
                        r = httpx.get("http://127.0.0.1:8080/health", timeout=0.5)
                        if r.status_code == 200:
                            from src.mcp.server import _services_cache
                            from src.providers.embedder.remote_embedder import RemoteEmbedder
                            embedder = _services_cache.resolve(RemoteEmbedder)
                            with embedder._mode_lock:
                                embedder.mode = "llama_cpp"
                            break
                    except Exception as _e:
                        logger.warning(f"llama health check failed: {_e}")
                    time.sleep(0.5)
    except Exception as e:
        logger.warning(f"⚠️ llama.cpp embedder: {e}")

    # Всегда пытаемся запустить reranker (не зависит от embedder)
    try:
        from src.providers.reranker.llama_runner import get_global_runner
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        ok = loop.run_until_complete(get_global_runner().start_reranker())
        loop.close()
        if ok:
            logger.info("✅ Реренкер (BGE-M3) запущен")
        else:
            logger.warning("⚠️ Реренкер не запустился (будет fallback)")
    except Exception as e:
        # Не критично — search_code работает без реранкера
        logger.warning(f"⚠️ Реренкер (BGE-M3) не запустился: {e}")


def _shutdown_services():
    try:
        from src.mcp.server import _services_cache
        if _services_cache:
            _services_cache.shutdown()
    except Exception as _e:
        logger.warning("exception", exc_info=True)
        pass
