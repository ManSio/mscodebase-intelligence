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
from typing import Any, Callable, Dict, Optional, Type, TypeVar

from src.core.file_guard import FileGuard
from src.core.indexer import Indexer, _generate_unique_db_path
from src.core.parser import CodeParser
from src.core.rate_limiter import (
    CircuitBreaker,
    DebounceBatch,
    DebounceConfig,
    SlidingWindowRateLimiter,
)
from src.core.remote_embedder import RemoteEmbedder
from src.core.searcher import Searcher
from src.core.symbol_index import SymbolIndex

logger = logging.getLogger("mscodebase_server.di")

T = TypeVar("T")


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
        self._instances: Dict[type, Any] = {}      # Уже созданные экземпляры
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

    def list_registered(self) -> list:
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
    # Утилитные типы (keys)
    # ══════════════════════════════════════════════════════
    # Используем строку как ключ (не Path, т.к. может конфликтовать)
    services.add_singleton(str, project_root)  # "project_root"
    # Но также регистрируем как контекстный маркер
    services.add_singleton(type("ProjectRoot", (), {}), project_root)

    # ══════════════════════════════════════════════════════
    # Cross-project компоненты (для cross_repo_search и cross_project_deps)
    # ══════════════════════════════════════════════════════
    from src.core.multi_project_searcher import MultiProjectSearcher, ProjectRegistry

    project_registry = ProjectRegistry()
    project_registry.register(project_root)
    services.add_singleton(ProjectRegistry, project_registry)

    multi_project_searcher = MultiProjectSearcher(embedder, project_registry)
    services.add_singleton(MultiProjectSearcher, multi_project_searcher)

    # ══════════════════════════════════════════════════════
    # Базовые компоненты (без зависимостей от других)
    # ══════════════════════════════════════════════════════
    db_path = _generate_unique_db_path(project_root)
    services.add_singleton(Path, db_path)  # db_path

    code_parser = CodeParser()
    services.add_singleton(CodeParser, code_parser)

    file_guard = FileGuard(project_root)
    services.add_singleton(FileGuard, file_guard)

    if embedder is None:
        embedder = RemoteEmbedder()
    services.add_singleton(RemoteEmbedder, embedder)

    symbol_index = SymbolIndex()
    services.add_singleton(SymbolIndex, symbol_index)

    # ══════════════════════════════════════════════════════
    # Rate Limiting компоненты (защита от перегрузки)
    # ══════════════════════════════════════════════════════
    rate_limiter = SlidingWindowRateLimiter()
    services.add_singleton(SlidingWindowRateLimiter, rate_limiter)

    # CircuitBreaker для LM Studio
    lm_studio_breaker = CircuitBreaker(
        failure_threshold=5,
        recovery_timeout=30.0,
        name="lm_studio",
    )
    services.add_singleton(type("LmStudioCircuitBreaker", (), {}), lm_studio_breaker)

    # ══════════════════════════════════════════════════════
    # Indexer (зависит от embedder, file_guard, parser)
    # ══════════════════════════════════════════════════════
    indexer = Indexer(
        db_path=db_path,
        embedder=embedder,
        file_guard=file_guard,
        project_path=project_root,
        parser=code_parser,
        symbol_index=symbol_index,
    )
    services.add_singleton(Indexer, indexer)

    # ══════════════════════════════════════════════════════
    # Searcher (зависит от indexer, embedder)
    # ══════════════════════════════════════════════════════
    searcher = Searcher(indexer, embedder)
    indexer.searcher = searcher  # обратная связь
    services.add_singleton(Searcher, searcher)

    # ══════════════════════════════════════════════════════
    # DebounceBatch — пакетная реиндексация BM25
    # ══════════════════════════════════════════════════════
    # Вместо searcher.reindex() на каждый файл — накапливаем батч
    # и реиндексируем BM25 раз в 500ms (или при 100 файлах)
    def _batch_reindex_bm25(changed_files: set):
        """Callback для DebounceBatch — реиндексация BM25."""
        logger.info(f"BM25 reindex triggered for {len(changed_files)} changed files")
        searcher.reindex()

    bm25_batch = DebounceBatch(
        callback=_batch_reindex_bm25,
        config=DebounceConfig(debounce_ms=500, max_batch_size=100, max_wait_ms=5000),
    )
    services.add_singleton(DebounceBatch, bm25_batch)

    logger.info(
        f"DI Container initialized for {project_root.name}: "
        f"{len(services.list_registered())} services registered"
    )
    return services
