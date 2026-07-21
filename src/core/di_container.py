"""Dependency Injection Container для MSCodeBase.

Одно место регистрации всех зависимостей. Каждый компонент
получает только то, что ему нужно (Constructor Injection).

Решает проблему тройной инициализации:
- main.py создавал одни компоненты
- hybrid_server.py дублировал всю инициализацию
- lsp_main.py создавал третью копию через init_components()

Теперь: один ServiceCollection → все компоненты зарегистрированы один раз.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar

from src.core.graph import PropertyGraph
from src.core.indexing.file_guard import FileGuard
from src.core.indexing.indexer import Indexer, _generate_unique_db_path
from src.core.indexing.parser import CodeParser
from src.core.indexing.project_indexer_registry import (
    ProjectIndexerRegistry,
)
from src.core.indexing.resource_monitor import (
    ResourceMonitor,
    get_global_resource_monitor,
)
from src.core.indexing.symbol_index import SymbolIndex
from src.core.rate_limiter import (
    CircuitBreaker,
    DebounceBatch,
    DebounceConfig,
    SlidingWindowRateLimiter,
)
from src.core.search.engine import Searcher
from src.core.search.graph_adapter import SymbolIndexAdapter
from src.providers.embedder.remote_embedder import RemoteEmbedder

logger = logging.getLogger("mscodebase_server.di")

T = TypeVar("T")


class ProjectRootKey:
    """Sentinel-ключ для project_root в DI. Импортируется потребителями."""

    pass


class DbPathKey:
    """Sentinel-ключ для db_path в DI. Импортируется потребителями."""

    pass


class IndexerFactoryKey:
    """Sentinel-ключ для Indexer factory в DI (см. INC-6BCB / multi-window)."""

    pass


class ResourceMonitorKey:
    """Sentinel-ключ для ResourceMonitor в DI (см. INC-6BCB / multi-window)."""

    pass


# Экспортируем для потребителей.
__all__ = [
    "ServiceCollection",
    "ProjectRootKey",
    "DbPathKey",
    "IndexerFactoryKey",
    "ResourceMonitorKey",
    "create_service_collection",
]


class ServiceCollection:
    """Service Collection (аналог IServiceCollection из .NET).

    Позволяет регистрировать синглтоны и фабрики. Все инструменты
    получают зависимости через конструктор, а не через замыкание.

    Example:
        services = ServiceCollection()
        services.add_singleton(Path, project_root)
        services.add_singleton(Indexer, indexer_instance)
        indexer = services.resolve(Indexer)
    """

    def __init__(self):
        self._instances: Dict[type, Any] = {}  # Уже созданные экземпляры
        self._factories: Dict[type, Callable] = {}  # Фабрики для ленивых синглтонов

    def add_singleton(self, key: type, instance: Any = None):
        """Регистрирует синглтон (существующий экземпляр).

        Args:
            key: Тип для резолвинга (например, Indexer)
            instance: Экземпляр. Если None — будет использована фабрика.
        """
        if instance is not None:
            self._instances[key] = instance
            logger.debug(f"DI registered: {key.__name__} (instance)")

    def add_factory(self, key: type, factory: Callable[..., Any]):
        """Регистрирует фабрику для ленивого создания экземпляра.

        Фабрика вызывается один раз при первом resolve().

        Args:
            key: Тип для резолвинга
            factory: Функция, возвращающая экземпляр
        """
        self._factories[key] = factory
        logger.debug(f"DI registered: {key.__name__} (factory)")

    def resolve(self, key: Type[T]) -> T:
        """Резолвит зависимость по типу.

        Приоритет:
        1. Уже созданные экземпляры (singleton)
        2. Фабрики (ленивое создание, создаётся один раз)

        Raises:
            KeyError: Если тип не зарегистрирован
        """
        # 1. Проверяем уже созданные экземпляры
        if key in self._instances:
            return self._instances[key]

        # 2. Проверяем фабрики
        if key in self._factories:
            instance = self._factories[key](self)
            self._instances[key] = instance
            logger.debug(f"DI resolved (lazy): {key.__name__}")
            return instance

        raise KeyError(
            f"Dependency '{key.__name__}' not registered in ServiceCollection. "
            f"Available types: {list(self._instances.keys()) + list(self._factories.keys())}"
        )

    def shutdown(self):
        """Закрывает все зарегистрированные сервисы, реализующие close().

        Вызывается при остановке MCP-сервера для корректного освобождения
        ресурсов (файловые дескрипторы, HTTP-сессии, tree-sitter runtime).
        """
        closed = 0
        for key, instance in self._instances.items():
            close_method = getattr(instance, "close", None)
            if callable(close_method):
                try:
                    if hasattr(close_method, "__await__"):
                        import asyncio

                        try:
                            loop = asyncio.get_event_loop()
                            if loop.is_running():
                                loop.create_task(close_method())
                            else:
                                asyncio.run(close_method())
                        except RuntimeError:
                            asyncio.run(close_method())
                    else:
                        close_method()
                    closed += 1
                except Exception as e:
                    logger.debug(f"DI shutdown: {key.__name__}.close() error: {e}")
        logger.info(f"DI shutdown: {closed} services closed")

    def list_registered(self) -> List[type]:
        """Возвращает список всех зарегистрированных типов."""
        return list(self._instances.keys()) + list(self._factories.keys())


def create_service_collection(
    project_root: Path,
    embedder: Optional[RemoteEmbedder] = None,
) -> ServiceCollection:
    """Создает и настраивает DI контейнер.

    ЕДИНСТВЕННОЕ МЕСТО, где создаются все зависимости.
    Вызывается при старте сервера (main.py) или LSP (lsp_main.py).

    Args:
        project_root: Корень проекта (абсолютный путь)
        embedder: Опциональный предварительно созданный embedder (для hybrid режима)

    Returns:
        Настроенный ServiceCollection со всеми зависимостями
    """
    services = ServiceCollection()

    # ══════════════════════════════════════════════════════
    # Базовые компоненты (без зависимостей от других)
    # db_path нужен ДО регистрации sentinel-ключа.
    db_path = _generate_unique_db_path(project_root)

    # ══════════════════════════════════════════════════════
    # Утилитные типы (keys)
    # ══════════════════════════════════════════════════════
    # Sentinel-классы вместо str / type("…", (), {}) —
    # иначе ключи невозможно импортировать обратно (анонимный тип
    # создаётся заново при каждом импорте), а str конфликтует
    # с любым будущим string-сервисом. См. INC-53EC / REFC-04.
    services.add_singleton(ProjectRootKey, project_root)
    services.add_singleton(DbPathKey, db_path)

    code_parser = CodeParser()
    services.add_singleton(CodeParser, code_parser)

    file_guard = FileGuard(project_root)
    services.add_singleton(FileGuard, file_guard)

    if embedder is None:
        embedder = RemoteEmbedder()
    services.add_singleton(RemoteEmbedder, embedder)

    # ══════════════════════════════════════════════════════
    # Cross-project компоненты (ПОСЛЕ embedder!)
    # ══════════════════════════════════════════════════════
    from src.core.multi_project_searcher import MultiProjectSearcher, ProjectRegistry

    project_registry = ProjectRegistry()
    project_registry.register(project_root)
    services.add_singleton(ProjectRegistry, project_registry)

    multi_project_searcher = MultiProjectSearcher(embedder, project_registry)
    services.add_singleton(MultiProjectSearcher, multi_project_searcher)

    # PropertyGraph — персистентный граф знаний (v3.0)
    # Хранится в .codebase/graph.db, WAL mode, потокобезопасен.
    graph_db = project_root / ".codebase" / "graph.db"
    property_graph = PropertyGraph(graph_db)
    services.add_singleton(PropertyGraph, property_graph)

    # SymbolIndexAdapter — обёртка PropertyGraph в интерфейс SymbolIndex
    # HYBRID mode: PropertyGraph + in-memory Dict для плавной миграции
    symbol_index = SymbolIndexAdapter(property_graph, mode=SymbolIndexAdapter.MODE_PURE)
    services.add_singleton(SymbolIndex, symbol_index)

    # ══════════════════════════════════════════════════════
    # Project Indexer Registry (multi-window support).
    # Раньше Indexer был singleton в DI — переключение окон Zed
    # ломало state. Теперь Indexer-ы per-project_path, ленивое
    # создание через ProjectIndexerRegistry.
    # см. INC-6BCB / multi-window.
    # ══════════════════════════════════════════════════════
    # ResourceMonitor: подключаем к registry для adaptive throttling
    # (LRU evict под давлением RAM/CPU).
    resource_monitor = get_global_resource_monitor()
    services.add_singleton(ResourceMonitorKey, resource_monitor)
    services.add_singleton(ResourceMonitor, resource_monitor)

    registry = ProjectIndexerRegistry(
        max_cached=5,
        resource_monitor=resource_monitor,
    )

    services.add_singleton(ProjectIndexerRegistry, registry)

    # ══════════════════════════════════════════════════════
    # Event Broker (Push-уведомления в Zed)
    # ОБЪЯВЛЯЕМ ПЕРВЫМ — иначе CircuitBreaker.on_state_change
    # не сможет захватить его в closure (был NameError на первом
    # срабатывании LM Studio, см. INC-53EC / BUG-01).
    # ══════════════════════════════════════════════════════
    from src.core.notification_broker import NotificationBroker

    notification_broker = NotificationBroker()
    services.add_singleton(NotificationBroker, notification_broker)

    # ══════════════════════════════════════════════════════
    # Per-project Indexer factory (multi-window, INC-6BCB-v2).
    # Объявляется ПОСЛЕ notification_broker, чтобы избежать late-binding
    # NameError при будущих рефакторингах. Python closures — late binding,
    # здесь работает потому что фабрика вызывается ПОСЛЕ return services,
    # но это хрупко. Явный захват переменных в аргументы default делает
    # код устойчивым.
    # ══════════════════════════════════════════════════════
    def _create_indexer_for_path(
        p: Path,
        _embedder=embedder,
        _code_parser=code_parser,
        _registry=registry,
        _notification_broker=notification_broker,
    ) -> Indexer:
        """Фабрика для создания per-project Indexer.

        Каждый Indexer получает свой db_path, file_guard, symbol_index,
        bm25_batch — полностью изолировано от других окон.

        Multi-window (INC-6BCB-v2): bm25_batch живёт НА Indexer-е
        (не в DI singleton) — иначе per-project файлы реиндексировались
        бы общим батчем, привязанным к default project_root.
        """
        p_db_path = _generate_unique_db_path(p)
        p_file_guard = FileGuard(p)
        # Per-project PropertyGraph + SymbolIndexAdapter
        p_graph_db = p / ".codebase" / "graph.db"
        p_property_graph = PropertyGraph(p_graph_db)
        p_symbol_index = SymbolIndexAdapter(p_property_graph, mode=SymbolIndexAdapter.MODE_PURE)
        p_indexer = Indexer(
            db_path=p_db_path,
            embedder=_embedder,
            file_guard=p_file_guard,
            project_path=p,
            parser=_code_parser,
            symbol_index=p_symbol_index,
            notification_broker=_notification_broker,
        )
        # Searcher создаём сразу и связываем через set_searcher.
        p_searcher = Searcher(p_indexer, _embedder)
        p_indexer.set_searcher(p_searcher)

        # Per-project BM25 debounce batch. Захватываем p_indexer в closure —
        # bm25_batch будет реиндексировать Searcher именно этого Indexer-а.
        captured_indexer = p_indexer

        def _bm25_reindex_callback(_changed_files: set):
            try:
                if captured_indexer.searcher:
                    captured_indexer.searcher.reindex()
            except Exception as cb_err:
                logger.debug(f"per-project bm25 batch callback: {cb_err}")

        p_indexer.bm25_batch = DebounceBatch(
            callback=_bm25_reindex_callback,
            config=DebounceConfig(
                debounce_ms=500, max_batch_size=100, max_wait_ms=5000
            ),
        )
        return p_indexer

    services.add_singleton(IndexerFactoryKey, _create_indexer_for_path)

    # ══════════════════════════════════════════════════════
    # Rate Limiting компоненты (защита от перегрузки)
    # ══════════════════════════════════════════════════════
    rate_limiter = SlidingWindowRateLimiter()
    services.add_singleton(SlidingWindowRateLimiter, rate_limiter)

    # CircuitBreaker для LM Studio.
    # Callback захватывает уже объявленный notification_broker.
    lm_studio_breaker = CircuitBreaker(
        failure_threshold=5,
        recovery_timeout=30.0,
        name="lm_studio",
        on_state_change=lambda old, new, err: notification_broker.publish_sync(
            "mscodebase/system_health",
            {
                "embedder": "LM Studio (Local)",
                "circuit_breaker": new.upper(),
                "fallback_active": new == "open",
                "error_message": err or "",
            },
        ),
    )
    services.add_singleton(CircuitBreaker, lm_studio_breaker)

    # Подключаем CircuitBreaker к embedder-у (защита от каскадных сбоев LM Studio)
    if hasattr(embedder, "_breaker"):
        embedder._breaker = lm_studio_breaker

    # ══════════════════════════════════════════════════════
    # DebounceBatch — пакетная реиндексация BM25.
    # Multi-window (INC-6BCB-v2): больше НЕ регистрируется в DI как
    # singleton. Вместо этого создаётся per-project ВНУТРИ
    # _create_indexer_for_path() и прикрепляется к Indexer-у как
    # indexer.bm25_batch. Это устраняет баг, когда для не-default
    # проектов batch работал с default project_root.
    # ══════════════════════════════════════════════════════

    logger.info(
        f"DI Container initialized for {project_root.name}: "
        f"{len(services.list_registered())} services registered"
    )
    return services
