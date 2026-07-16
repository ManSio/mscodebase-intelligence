"""
Project Indexer Registry — мультипроектная индексация для multi-window Zed.

Проблема (см. INC-6BCB / multi-window):
  - Один MCP/LSP процесс обслуживает несколько окон Zed одновременно.
  - Раньше DI хранил один Indexer — переключение окон ломало state.
  - MultiProjectSearcher кэшировал LanceDB connections, вызывая file-locks.

Решение:
  - IndexerRegistry: Dict[Path, Indexer] — per-project indexer с lazy созданием.
  - project_root определяется в каждом вызове MCP-инструмента:
    1) явный project_root из аргументов
    2) resolve_project_root() (PROJECT_PATH env / LSP bridge / CWD)
  - Per-project threading.Lock — запись в LanceDB сериализована.
  - LRU eviction (настраиваемый лимит) — не разрастается до бесконечности.
  - При вытеснении indexer из реестра — явный close на DB connections
    (LanceDB connections держат OS-level file locks на Windows).
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import threading
from collections import OrderedDict
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("mscodebase_server.registry")


class ProjectState(Enum):
    """Состояние проекта в реестре.

    UNINITIALIZED — проект ещё не создан (первый вызов get_indexer не сделан).
    STARTING     — создаётся Indexer (открывается LanceDB, загружаются метаданные).
    INDEXING     — фоновая индексация запущена (chunks ещё не полные).
    READY        — проект полностью готов к работе (indexer + chunks доступны).
    FAILED       — ошибка при создании/индексации.

    Переходы:
        UNINITIALIZED ──get_indexer()──▶ STARTING
        STARTING ──создан──▶ INDEXING (если auto-index)
        STARTING ──возврат──▶ READY      (если индекс уже есть)
        INDEXING ──завершён──▶ READY
        INDEXING/STARTING ──ошибка──▶ FAILED
    """

    UNINITIALIZED = auto()
    STARTING = auto()
    INDEXING = auto()
    READY = auto()
    FAILED = auto()


class ProjectIndexerRegistry:
    """Потокобезопасный реестр Indexer-ов per project.

    Используется как singleton в DI-контейнере. Все MCP-инструменты
    вызывают get_indexer(project_path) вместо services.resolve(Indexer)
    напрямую — это обеспечивает корректную работу при нескольких
    открытых окнах Zed.
    """

    def __init__(
        self,
        max_cached: int = 5,
        on_evict: Optional[Callable[[Path, Any], None]] = None,
        resource_monitor: Optional[Any] = None,
    ):
        """Инициализация реестра.

        Args:
            max_cached: LRU лимит (по умолчанию 5 — баланс между
                multi-window удобством и потреблением RAM).
                Каждый Indexer ~200-500MB (LanceDB + pandas-кэши).
                5 = 1-2.5GB на реестр — разумно для 16GB системы.
            on_evict: callback при вытеснении Indexer-а.
            resource_monitor: опциональный ResourceMonitor для adaptive
                throttling (см. resource_monitor.py).
        """
        self._indexers: "OrderedDict[Path, Any]" = OrderedDict()
        self._locks: Dict[Path, threading.Lock] = {}
        self._meta_lock = threading.Lock()
        self._max_cached = max(1, max_cached)
        self._on_evict = on_evict
        self._resource_monitor = resource_monitor
        self._create_lock = threading.Lock()

        # ══════════════════════════════════════════════════════════════
        # Per-project state machine (INC-6BCB-v4: race-free readiness)
        # ══════════════════════════════════════════════════════════════
        self._states: Dict[Path, ProjectState] = {}
        self._ready_events: Dict[Path, asyncio.Event] = {}

        self._stats = {
            "cache_hits": 0,
            "cache_misses": 0,
            "evictions": 0,
            "evictions_for_pressure": 0,
        }

        # Финальная очистка при завершении процесса.
        atexit.register(self.close_all)

    def get_lock(self, project_path: Path) -> threading.Lock:
        """Возвращает (и при необходимости создаёт) Lock для проекта.

        Используется для сериализации записи в LanceDB — каждый проект
        имеет свой lock, чтобы notify_change из разных окон не дрались
        за один файл.
        """
        p = Path(project_path).resolve()
        with self._meta_lock:
            lock = self._locks.get(p)
            if lock is None:
                lock = threading.Lock()
                self._locks[p] = lock
            return lock

    def get_indexer(
        self,
        project_path: Path,
        factory: Optional[Callable[[Path], Any]] = None,
    ) -> Any:
        """Возвращает Indexer для project_path, lazy-создавая если нужно.

        При первом создании переводит проект в STARTING, а после
        создания — в READY (если индекс не пустой) или INDEXING.

        Args:
            project_path: путь к корню проекта.
            factory: callable(project_path) -> Indexer. Если None — используется
                    дефолтный из di_container (нужен переданный в DI).

        Returns:
            Инстанс Indexer (singleton per project_path).

        Raises:
            ValueError: если project_path не существует.
        """
        p = Path(project_path).resolve()
        if not p.exists() or not p.is_dir():
            raise ValueError(f"project_path не существует или не директория: {p}")

        with self._meta_lock:
            existing = self._indexers.get(p)
            if existing is not None:
                # LRU touch — перемещаем в конец OrderedDict
                self._indexers.move_to_end(p)
                self._stats["cache_hits"] += 1
                # Если проект был создан — он как минимум READY
                return existing
        self._stats["cache_misses"] += 1

        # Проверяем pressure ДО создания нового Indexer-а — может, надо
        # что-то вытеснить.
        self._maybe_evict_for_pressure()

        # Создаём вне meta_lock (может занять время — открытие LanceDB).
        with self._create_lock:
            # Double-check: возможно параллельный поток уже создал.
            with self._meta_lock:
                existing = self._indexers.get(p)
                if existing is not None:
                    self._indexers.move_to_end(p)
                    return existing

            if factory is None:
                raise RuntimeError(
                    "ProjectIndexerRegistry: factory не передан. "
                    "Передайте create_indexer_for_path из di_container."
                )

            # STARTING → создаётся Indexer
            self.set_state(p, ProjectState.STARTING)
            logger.info(f"📦 ProjectIndexerRegistry: создаю Indexer для {p.name}")

            try:
                new_indexer = factory(p)
            except Exception as e:
                self.set_state(p, ProjectState.FAILED)
                raise RuntimeError(f"Ошибка создания Indexer для {p.name}: {e}") from e

            # После создания проверяем, пустой ли индекс
            try:
                status = new_indexer.get_status()
                total_chunks = status.get("total_chunks", 0)
                final_state = (
                    ProjectState.INDEXING if total_chunks == 0 else ProjectState.READY
                )
            except Exception:
                final_state = ProjectState.READY  # fallback — считаем готовым

            with self._meta_lock:
                self._indexers[p] = new_indexer
                self._maybe_evict_locked()
            self.set_state(p, final_state)

            return new_indexer

    def get_all_paths(self) -> list[Path]:
        """Возвращает список зарегистрированных project paths."""
        with self._meta_lock:
            return list(self._indexers.keys())

    def evict(self, project_path: Path) -> bool:
        """Явно удаляет Indexer для проекта (например, при закрытии окна)."""
        p = Path(project_path).resolve()
        with self._meta_lock:
            idx = self._indexers.pop(p, None)
            self._locks.pop(p, None)
        if idx is not None:
            self._safe_close(idx)
            if self._on_evict:
                try:
                    self._on_evict(p, idx)
                except Exception as _e:
                    logger.warning("exception", exc_info=True)
                    pass
            return True
        return False

    # ══════════════════════════════════════════════════════════════
    # Project State Machine
    # ══════════════════════════════════════════════════════════════

    def set_state(self, project_path: Path, state: ProjectState) -> None:
        """Устанавливает состояние проекта + сигналит Event при READY/FAILED.

        Потокобезопасен через _meta_lock. При READY или FAILED
        fires asyncio.Event — это позволяет MCP-инструментам ждать
        готовности через wait_until_ready().
        """
        p = Path(project_path).resolve()
        with self._meta_lock:
            old = self._states.get(p)
            self._states[p] = state
        log_level = logging.DEBUG
        if old != state:
            if state == ProjectState.READY:
                log_level = logging.INFO
                ev = self._ready_events.get(p)
                if ev is not None:
                    ev.set()
            elif state == ProjectState.FAILED:
                log_level = logging.WARNING
                ev = self._ready_events.get(p)
                if ev is not None:
                    ev.set()  # тоже пробуждаем wait (вызовет проверку)
        logger.log(log_level, f"📌 State {p.name}: {old} -> {state}")

    def get_state(self, project_path: Path) -> ProjectState:
        """Возвращает текущее состояние проекта.

        Если проект не зарегистрирован — UNINITIALIZED.
        """
        p = Path(project_path).resolve()
        with self._meta_lock:
            return self._states.get(p, ProjectState.UNINITIALIZED)

    async def wait_until_ready(
        self,
        project_path: Path,
        timeout: float = 5.0,
    ) -> ProjectState:
        """Ожидает, пока проект не перейдёт в READY (или FAILED).

        Args:
            project_path: корень проекта.
            timeout: макс. время ожидания в секундах (по умолч. 5с).

        Returns:
            Финальное состояние: READY, FAILED, или текущее если timeout.

        Используется MCP-инструментами перед выполнением:
            state = await registry.wait_until_ready(path, timeout=3.0)
            if state != ProjectState.READY:
                raise ToolError("Проект ещё не готов. Повторите запрос.")

        Это решает race condition: если пользователь переключился на
        новый проект, а LSP ещё не успел записать bridge, инструмент
        не возьмёт старый проект и не упадёт с 'project not found',
        а дождётся готовности (или timeout → понятная ошибка).
        """
        p = Path(project_path).resolve()
        ev: Optional[asyncio.Event] = None
        with self._meta_lock:
            current = self._states.get(p, ProjectState.UNINITIALIZED)
            if current in (ProjectState.READY, ProjectState.FAILED):
                return current
            if p not in self._ready_events:
                self._ready_events[p] = asyncio.Event()
            ev = self._ready_events[p]

        if ev is not None:
            try:
                await asyncio.wait_for(ev.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(
                    f"⏳ wait_until_ready({p.name}) timeout after {timeout}s"
                )

        # Re-check state after event (может измениться за время ожидания)
        with self._meta_lock:
            return self._states.get(p, ProjectState.UNINITIALIZED)

    def close_all(self) -> None:
        """Закрывает все Indexer-ы. Вызывается atexit."""
        with self._meta_lock:
            paths = list(self._indexers.keys())
        for p in paths:
            self.evict(p)
        logger.debug(f"ProjectIndexerRegistry: закрыто {len(paths)} indexer-ов")

    def _maybe_evict_locked(self) -> None:
        """LRU eviction по размеру кэша. Вызывать только под self._meta_lock."""
        while len(self._indexers) > self._max_cached:
            oldest_path, oldest_idx = self._indexers.popitem(last=False)
            self._locks.pop(oldest_path, None)
            self._stats["evictions"] += 1
            # Закрытие делаем вне lock (может быть долгим — LanceDB flush).
            threading.Thread(
                target=self._safe_close,
                args=(oldest_idx,),
                daemon=True,
                name=f"close-indexer-{oldest_path.name}",
            ).start()
            logger.info(
                f"📦 LRU evict (size): {oldest_path.name} "
                f"(cache: {len(self._indexers)}/{self._max_cached})"
            )

    def _maybe_evict_for_pressure(self) -> None:
        """Evict под давлением ResourceMonitor-а (RAM/CPU).

        Срабатывает ПЕРЕД созданием нового Indexer-а, чтобы освободить
        ресурсы для нового проекта. Если monitor не передан — no-op.
        """
        if self._resource_monitor is None:
            return
        if not self._resource_monitor.is_under_pressure():
            return
        # Под давлением — вытесняем самый старый (LRU).
        with self._meta_lock:
            if not self._indexers:
                return
            oldest_path, oldest_idx = self._indexers.popitem(last=False)
            self._locks.pop(oldest_path, None)
        self._stats["evictions_for_pressure"] += 1
        logger.warning(
            f"📦 Pressure evict: {oldest_path.name} "
            f"(RAM/CPU high; cache: {len(self._indexers)})"
        )
        # Закрытие синхронно (вытеснение под давлением должно быть быстрым).
        self._safe_close(oldest_idx)

    def get_stats(self) -> Dict[str, Any]:
        """Возвращает статистику реестра (для HealthReport / мониторинга)."""
        with self._meta_lock:
            return {
                **self._stats,
                "cached_projects": len(self._indexers),
                "max_cached": self._max_cached,
                "project_paths": [str(p) for p in self._indexers.keys()],
            }

    @staticmethod
    def _safe_close(indexer: Any) -> None:
        """Безопасно закрывает Indexer.

        LanceDB connection не имеет close() API — ресурсы освобождаются
        через GC. Но мы делаем это явно:
        1. Detach notification broker (разрываем ссылку на JSON-RPC session).
        2. Очищаем кэши Indexer-а (_cached_total_chunks, _df_cache).
        3. Обнуляем ссылку на lancedb.DB.
        4. gc.collect() — для немедленного освобождения mmap на Windows
           (иначе файл остаётся locked до выхода процесса).
        """
        try:
            if hasattr(indexer, "notification_broker") and indexer.notification_broker:
                try:
                    indexer.notification_broker.detach_session()
                except Exception as _e:
                    logger.warning("exception", exc_info=True)
                    pass
            # Очищаем in-memory кэши Indexer-а.
            for cache_attr in (
                "_cached_total_chunks",
                "_cached_unique_files",
                "_df_cache",
                "_last_reported_progress",
            ):
                if hasattr(indexer, cache_attr):
                    try:
                        if cache_attr == "_cached_unique_files":
                            setattr(indexer, cache_attr, set())
                        elif isinstance(getattr(indexer, cache_attr, None), int):
                            setattr(indexer, cache_attr, 0)
                        else:
                            setattr(indexer, cache_attr, None)
                    except Exception as _e:
                        logger.warning("exception", exc_info=True)
                        pass
            # Явно сбрасываем LanceDB connection — иначе на Windows файл
            # .lance остаётся залоченным через mmap до GC.
            if hasattr(indexer, "db"):
                try:
                    indexer.db = None
                except Exception as _e:
                    logger.warning("exception", exc_info=True)
                    pass
            if hasattr(indexer, "table"):
                try:
                    indexer.table = None
                except Exception as _e:
                    logger.warning("exception", exc_info=True)
                    pass
            # Async LanceDB + Searcher cleanup (memory leak fix v2.7.0).
            if hasattr(indexer, "_async_db"):
                try:
                    indexer._async_db = None
                except Exception as _e:
                    logger.warning("exception", exc_info=True)
                    pass
            if hasattr(indexer, "_async_table"):
                try:
                    indexer._async_table = None
                except Exception as _e:
                    logger.warning("exception", exc_info=True)
                    pass
            searcher_ref = getattr(indexer, "searcher", None)
            if searcher_ref is not None and hasattr(searcher_ref, "close"):
                try:
                    loop = None
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        if asyncio is not None:
                            asyncio.run(searcher_ref.close())
                    if loop is not None and loop.is_running():
                        searcher_ref._cache.clear()
                except Exception as _e:
                    logger.warning("exception", exc_info=True)
                    pass
            # Принудительный GC — освобождает mmap handles на Windows.
            import gc

            gc.collect()
        except Exception as e:
            logger.debug(f"_safe_close: {e}")


# Глобальный singleton для использования в инструментах.
_registry: Optional[ProjectIndexerRegistry] = None
_registry_lock = threading.Lock()


def get_global_registry() -> ProjectIndexerRegistry:
    """Возвращает singleton ProjectIndexerRegistry.

    Лимит кэша 5 (LRU) + ResourceMonitor для pressure-evict.
    """
    global _registry
    with _registry_lock:
        if _registry is None:
            # Lazy import — избегаем цикл импорта resource_monitor.
            try:
                from src.core.indexing.resource_monitor import get_global_resource_monitor

                monitor = get_global_resource_monitor()
            except Exception:
                monitor = None
            _registry = ProjectIndexerRegistry(
                max_cached=5,
                resource_monitor=monitor,
            )
        return _registry


def reset_global_registry() -> None:
    """Сбрасывает singleton (для тестов)."""
    global _registry
    with _registry_lock:
        if _registry is not None:
            _registry.close_all()
        _registry = None
