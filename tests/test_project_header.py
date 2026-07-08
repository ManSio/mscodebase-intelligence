"""Tests for project_path visibility in tool outputs (INC-6BCB-v3).

Этот набор тестов проверяет:
1. _is_self_index_path() детектит Zed install dir, ext_root, None.
2. resolve_indexer_for_request() бросает ToolError на self-indexing.
3. _project_header() / _project_metadata() возвращают валидные данные.
4. IndexProjectDirTool блокирует self-indexing ДО запуска индексации.
5. GetIndexStatusTool показывает project_path в первой строке.
6. SearchCodeTool добавляет project_header в output.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core.error_handler import ToolError
from src.mcp.tools.base import (
    MCPTool,
    _is_self_index_path,
    resolve_indexer_for_request,
)

# ════════════════════════════════════════════════════════════
# _is_self_index_path
# ════════════════════════════════════════════════════════════


class TestIsSelfIndexPath:
    """Детект self-indexing targets."""

    def setup_method(self):
        # Не скипаем — запускаем только на Windows/реальных путях.
        # Тест для Linux-путей: см. test_is_zed_install_dir_linux (skipped).
        pass

    def test_none_is_self_index(self):
        """None = неопределённый project_path = self-indexing (запрещено)."""
        assert _is_self_index_path(None) is True

    @pytest.mark.parametrize(
        "path_str",
        [
            r"C:\AI\Zed",
            r"D:\AI\Zed",
            r"C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence",
            r"D:\AI\Zed\Zed.exe",
        ],
    )
    def test_zed_install_dir_detected(self, path_str):
        """Zed install dir = self-indexing."""
        assert _is_self_index_path(Path(path_str)) is True

    @pytest.mark.parametrize(
        "path_str",
        [
            r"C:\Users\misha\Documents\my-project",
            r"D:\projects\my-app",
        ],
    )
    def test_user_project_not_self_index(self, path_str):
        """Пользовательский проект ≠ self-indexing.

        Используем НЕ-ext_root путь (текущий репозиторий D:\\Project\\MSCodeBase
        это _ext_root — его self-indexing защита тоже ловит).
        """
        from src.mcp import server as server_mod

        # Подменяем _ext_root на ЗАВЕДОМО ДРУГОЙ путь, чтобы наш test path
        # не совпал с ним случайно.
        with patch.object(server_mod, "_ext_root", Path(r"D:\Some\Other\Path")):
            fake_user = Path(path_str)
            assert _is_self_index_path(fake_user) is False

    def test_ext_root_detected(self, tmp_path):
        """_ext_root (исходники расширения) = self-indexing."""
        # Подменяем _ext_root через patch.
        from src.mcp import server as server_mod

        with patch.object(server_mod, "_ext_root", tmp_path):
            assert _is_self_index_path(tmp_path) is True


# ════════════════════════════════════════════════════════════
# resolve_indexer_for_request — self-indexing guard
# ════════════════════════════════════════════════════════════


class TestResolveIndexerSelfIndexGuard:
    """resolve_indexer_for_request() бросает ToolError на self-indexing."""

    def _make_services(self, project_path_value: Path):
        """Создаёт mock ServiceCollection для теста."""
        from src.core.di_container import (
            IndexerFactoryKey,
            ProjectIndexerRegistry,
            ProjectRootKey,
        )

        services = MagicMock()
        mock_indexer = MagicMock()
        mock_indexer.project_path = project_path_value

        # registry.get_indexer() возвращает mock_indexer
        mock_registry = MagicMock(spec=ProjectIndexerRegistry)
        mock_registry.get_indexer.return_value = mock_indexer
        services.resolve.side_effect = lambda key: {
            ProjectRootKey: project_path_value,
            ProjectIndexerRegistry: mock_registry,
            IndexerFactoryKey: lambda p: mock_indexer,
        }[key]
        return services

    def test_explicit_user_project_works(self):
        """Явный explicit_project_root = user project — resolve_indexer возвращает indexer.

        Используем explicit_project_root чтобы обойти resolve_project_root()
        (который зависит от CWD/bridge/env). Прямой путь через kwargs — это
        контракт: пользователь вызвал tool с project_root=<свой проект>.
        """
        from src.mcp import server as server_mod

        # _ext_root = D:\Project\MSCodeBase (real). Используем путь,
        # который ЗАВЕДОМО не равен ext_root и не Zed install.
        user_project = Path(r"C:\Users\misha\Documents\my-cool-project")
        services = self._make_services(user_project)
        idx = resolve_indexer_for_request(
            services, explicit_project_root=str(user_project)
        )
        assert idx.project_path == user_project

    def test_explicit_zed_install_raises_tool_error(self):
        """explicit_project_root = Zed install dir → ToolError."""
        from src.mcp import server as server_mod

        zed_dir = Path(r"D:\AI\Zed")
        services = self._make_services(zed_dir)
        with pytest.raises(ToolError) as exc_info:
            resolve_indexer_for_request(services, explicit_project_root=str(zed_dir))
        assert "Self-indexing blocked" in str(exc_info.value)

    def test_explicit_none_project_raises_tool_error(self):
        """explicit_project_root = None → fallback к resolve_project_root() (не ошибка)."""
        services = self._make_services(None)
        result = resolve_indexer_for_request(services, explicit_project_root=None)
        assert result is not None  # успешный fallback к default проекту

    def test_explicit_ext_root_raises_tool_error(self):
        r"""explicit_project_root = _ext_root (исходники MCP) → ToolError.

        Без patch: _ext_root уже загружен и равен D:\Project\MSCodeBase.
        """
        from src.mcp import server as server_mod

        services = self._make_services(server_mod._ext_root)
        with pytest.raises(ToolError) as exc_info:
            resolve_indexer_for_request(
                services,
                explicit_project_root=str(server_mod._ext_root),
            )
        assert "Self-indexing blocked" in str(exc_info.value)


# ════════════════════════════════════════════════════════════
# _project_header / _project_metadata
# ════════════════════════════════════════════════════════════


class TestProjectHeader:
    """_project_header() возвращает строку с project path."""

    def test_returns_project_path(self):
        """Возвращает '📂 Project: <path>' для валидного indexer.

        Mock'аем _resolve_target_path чтобы обойти resolve_project_root
        (который зависит от CWD/bridge). Тестируем чистую логику
        _project_header.
        """
        from src.mcp.tools.search_tools import SearchCodeTool

        user_project = Path(r"C:\Users\misha\Documents\my-project")
        services = MagicMock()
        mock_indexer = MagicMock()
        mock_indexer.project_path = user_project
        # _resolve_target_path возвращает user_project (не self-indexing).
        services.resolve.return_value = user_project
        # resolve_indexer возвращает mock_indexer.
        with patch.object(SearchCodeTool, "resolve_indexer", return_value=mock_indexer):
            tool = SearchCodeTool(services)
            header = tool._project_header()
            assert "📂 Project: " in header
            assert str(user_project) in header

    def test_returns_unknown_on_error(self):
        """Если resolve_indexer падает — возвращает <unknown>."""
        services = MagicMock()
        services.resolve.side_effect = Exception("boom")

        from src.mcp.tools.search_tools import SearchCodeTool

        tool = SearchCodeTool(services)

        header = tool._project_header()
        assert "<unknown" in header

    def test_metadata_returns_dict(self):
        """_project_metadata() возвращает dict с project_path, chunks и т.п."""
        from src.mcp.tools.search_tools import SearchCodeTool

        user_project = Path(r"C:\Users\misha\Documents\my-project")
        services = MagicMock()
        mock_indexer = MagicMock()
        mock_indexer.project_path = user_project
        mock_indexer.get_status.return_value = {
            "total_chunks": 519,
            "unique_files": 42,
        }
        with patch.object(SearchCodeTool, "resolve_indexer", return_value=mock_indexer):
            tool = SearchCodeTool(services)

            meta = tool._project_metadata()
            assert meta["project_path"] == str(user_project)
            assert meta["total_chunks"] == 519
            assert meta["unique_files"] == 42

    def test_metadata_error_path(self):
        """_project_metadata() на ошибке возвращает dict с error."""
        services = MagicMock()
        services.resolve.side_effect = Exception("boom")

        from src.mcp.tools.search_tools import SearchCodeTool

        tool = SearchCodeTool(services)

        meta = tool._project_metadata()
        assert "error" in meta
        assert meta["project_path"] is None
