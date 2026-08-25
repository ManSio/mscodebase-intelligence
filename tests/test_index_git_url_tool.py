"""Тесты index_git_url tool (Фаза 2 MCP-обвязка).

Без сети/сервисов: фабрика source в DI подменяется фейком.
- Плохой URL → INCONCLUSIVE [kind] (ТЗ §6.5), не crash.
- Happy path → «Индексирован remote-репозиторий».
"""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

from src.core.di_container import GitUrlSourceFactoryKey, ServiceCollection
from src.mcp.tools.indexing_tools import IndexGitUrlTool
from src.sources.git_url import GitUrlSourceError


class _FailSource:
    """Фейковый источник: любой URL → GitUrlSourceError."""

    def __init__(self, *a, **k):
        pass

    def resolve(self):
        async def _r():
            raise GitUrlSourceError("domain_not_allowed", "github.com не в allowlist")
        return _r()


class _OkSource:
    """Фейковый источник: resolve возвращает RESOLVED (задаётся в тесте)."""

    RESOLVED: object = None

    def __init__(self, *a, **k):
        pass

    def resolve(self):
        async def _r():
            return _OkSource.RESOLVED
        return _r()


def _make_tool(source_cls):
    services = ServiceCollection()
    services.add_singleton(GitUrlSourceFactoryKey, lambda url: source_cls(url, Path("/unused")))
    return IndexGitUrlTool(services)


def test_missing_url_returns_usage(tmp_path):
    tool = _make_tool(_FailSource)
    resp = asyncio.run(tool.execute(url=""))
    assert "required url" in resp


def test_bad_url_is_inconclusive_not_crash(tmp_path):
    tool = _make_tool(_FailSource)
    resp = asyncio.run(tool.execute(url="https://github.com/a/b.git"))
    assert "INCONCLUSIVE [domain_not_allowed]" in resp
    assert "не сбой движка" in resp


def test_happy_path(tmp_path):
    clone = tmp_path / "clone"
    _OkSource.RESOLVED = clone
    tool = _make_tool(_OkSource)
    fake_indexer = MagicMock()
    fake_indexer.index_project.return_value = 42
    tool.resolve_indexer = lambda explicit_project_root=None: fake_indexer

    resp = asyncio.run(tool.execute(url="https://github.com/encode/httpx.git"))
    assert "Индексирован remote-репозиторий" in resp
    assert "42" in resp
    assert fake_indexer.index_project.called
    assert str(fake_indexer.index_project.call_args[0][0]) == str(clone)
