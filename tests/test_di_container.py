"""Unit-тесты для di_container.py: ServiceCollection, create_service_collection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.core.di_container import (
    ServiceCollection,
    create_service_collection,
)
from src.core.file_guard import FileGuard
from src.core.indexer import Indexer
from src.core.parser import CodeParser
from src.core.remote_embedder import RemoteEmbedder
from src.core.searcher import Searcher
from src.core.symbol_index import SymbolIndex
from src.core.rate_limiter import (
    SlidingWindowRateLimiter,
    DebounceBatch,
    CircuitBreaker,
)
from src.core.multi_project_searcher import MultiProjectSearcher, ProjectRegistry


# ══════════════════════════════════════════════════════════
# ServiceCollection
# ══════════════════════════════════════════════════════════

class TestServiceCollection:
    """ServiceCollection — DI контейнер."""

    def setup_method(self):
        self.services = ServiceCollection()

    def test_add_and_resolve_singleton(self):
        """Синглтон: add_singleton + resolve возвращает тот же объект."""
        obj = {"key": "value"}
        self.services.add_singleton(dict, obj)
        resolved = self.services.resolve(dict)
        assert resolved is obj
        assert resolved["key"] == "value"

    def test_add_factory_lazy_creation(self):
        """Фабрика: add_factory создаёт объект при первом resolve."""
        factory_called = False

        def factory(services):
            nonlocal factory_called
            factory_called = True
            return {"created": True}

        self.services.add_factory(dict, factory)
        assert factory_called is False  # лениво

        result = self.services.resolve(dict)
        assert factory_called is True
        assert result["created"] is True

    def test_factory_is_singleton(self):
        """Фабрика вызывается только один раз, возвращается тот же экземпляр."""
        call_count = 0

        def factory(services):
            nonlocal call_count
            call_count += 1
            return {"count": call_count}

        self.services.add_factory(dict, factory)
        r1 = self.services.resolve(dict)
        r2 = self.services.resolve(dict)

        assert call_count == 1  # вызвана один раз
        assert r1 is r2  # тот же объект

    def test_resolve_raises_key_error_for_unregistered(self):
        """resolve бросает KeyError для незарегистрированного типа."""
        with pytest.raises(KeyError, match="not registered"):
            self.services.resolve(type("Unknown", (), {}))

    def test_list_registered(self):
        """list_registered возвращает все зарегистрированные типы."""
        self.services.add_singleton(str, "test")
        self.services.add_singleton(int, 42)
        registered = self.services.list_registered()
        assert str in registered
        assert int in registered

    def test_multiple_types_independent(self):
        """Разные типы резолвятся независимо."""

        class ServiceA:
            pass

        class ServiceB:
            pass

        a = ServiceA()
        b = ServiceB()
        self.services.add_singleton(ServiceA, a)
        self.services.add_singleton(ServiceB, b)

        assert self.services.resolve(ServiceA) is a
        assert self.services.resolve(ServiceB) is b


# ══════════════════════════════════════════════════════════
# create_service_collection
# ══════════════════════════════════════════════════════════

class TestCreateServiceCollection:
    """create_service_collection — фабрика DI контейнера."""

    @pytest.fixture
    def project_root(self, tmp_path):
        return tmp_path / "test_project"

    def test_creates_all_services(self, project_root):
        """create_service_collection создаёт 14+ сервисов."""
        project_root.mkdir()
        services = create_service_collection(project_root)

        registered = services.list_registered()
        # Проверяем, что все ключевые сервисы зарегистрированы
        type_names = [t.__name__ for t in registered]
        for expected in ["Indexer", "CodeParser", "FileGuard",
                          "RemoteEmbedder", "SymbolIndex", "Searcher",
                          "SlidingWindowRateLimiter", "DebounceBatch",
                          "ProjectRegistry", "MultiProjectSearcher"]:
            assert expected in type_names, f"Missing: {expected}"

    def test_indexer_has_correct_deps(self, project_root):
        """Indexer создаётся с правильными зависимостями."""
        project_root.mkdir()
        services = create_service_collection(project_root)

        indexer = services.resolve(Indexer)
        assert indexer.project_path == project_root
        assert isinstance(indexer.parser, CodeParser)
        assert isinstance(indexer.file_guard, FileGuard)

    def test_searcher_sees_same_indexer(self, project_root):
        """Searcher использует тот же Indexer (циклическая связь)."""
        project_root.mkdir()
        services = create_service_collection(project_root)

        indexer = services.resolve(Indexer)
        searcher = services.resolve(Searcher)

        assert searcher.indexer is indexer
        assert indexer.searcher is searcher  # обратная связь

    def test_debounce_batch_uses_searcher(self, project_root):
        """DebounceBatch вызывает searcher.reindex при сбросе."""
        project_root.mkdir()
        services = create_service_collection(project_root)

        searcher = services.resolve(Searcher)
        original_reindex = searcher.reindex
        searcher.reindex = MagicMock()

        batch = services.resolve(DebounceBatch)
        # Добавляем файл и принудительно сбрасываем
        import asyncio
        asyncio.run(batch.add("test.py"))
        asyncio.run(batch.flush_now())

        searcher.reindex.assert_called_once()

    def test_multi_project_searcher_registered(self, project_root):
        """MultiProjectSearcher и ProjectRegistry зарегистрированы."""
        project_root.mkdir()
        services = create_service_collection(project_root)

        mp = services.resolve(MultiProjectSearcher)
        assert isinstance(mp, MultiProjectSearcher)

        pr = services.resolve(ProjectRegistry)
        assert isinstance(pr, ProjectRegistry)

    def test_project_registry_contains_project(self, project_root):
        """ProjectRegistry содержит переданный project_root."""
        project_root.mkdir()
        services = create_service_collection(project_root)

        pr = services.resolve(ProjectRegistry)
        projects = pr.list_projects()
        # Проверяем, что проект зарегистрирован
        names = [p[0] for p in projects]
        assert project_root.name in names

    def test_optional_embedder(self, project_root):
        """Можно передать готовый embedder."""
        project_root.mkdir()
        mock_embedder = MagicMock(spec=RemoteEmbedder)
        services = create_service_collection(project_root, embedder=mock_embedder)

        embedder = services.resolve(RemoteEmbedder)
        assert embedder is mock_embedder

    def test_circuit_breaker_registered(self, project_root):
        """CircuitBreaker для LM Studio зарегистрирован."""
        project_root.mkdir()
        services = create_service_collection(project_root)

        # Находим CircuitBreaker по типу
        for t in services.list_registered():
            if t.__name__ == "LmStudioCircuitBreaker":
                cb = services.resolve(t)
                assert isinstance(cb, CircuitBreaker)
                assert cb.name == "lm_studio"
                return
        pytest.fail("LmStudioCircuitBreaker not registered")
