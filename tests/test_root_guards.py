"""Guard: системный каталог не становится «проектом» и не получает `.mscodebase`.

Живой инцидент 2026-11-15: хост запустил MCP-сервер с cwd=`C:\\Windows` и
`PROJECT_PATH='${workspaceRoot}'` (неразвёрнутый плейсхолдер). Резолвер откатился
на cwd, автоиндексация пошла по `C:\\Windows`, и в каталоге ОС появилась
`chunks.db` на 105 МБ (10 264 чанка системных файлов).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from src.core.indexing.chunk_store import get_chunks_db_path
from src.core.project_resolution import (
    _try_resolve_path_env,
    is_forbidden_root,
    is_project_root,
    resolve_project_root,
)

SYSTEM_ROOT = Path(os.environ.get("SystemRoot") or os.environ.get("windir") or "C:/Windows")


# ── is_forbidden_root ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        SYSTEM_ROOT,
        SYSTEM_ROOT / "System32",
        Path.home(),
        Path(os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp"),
    ],
)
def test_system_locations_are_forbidden(path: Path):
    assert is_forbidden_root(path) is True, f"{path} должен считаться системным"


def test_project_directory_is_not_forbidden(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    assert is_forbidden_root(tmp_path) is False


def test_drive_root_is_forbidden():
    assert is_forbidden_root(Path(Path.cwd().anchor)) is True


def test_nonexistent_path_is_not_forbidden(tmp_path: Path):
    assert is_forbidden_root(tmp_path / "no" / "such" / "dir") is False


# ── is_project_root ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("marker", [".git", "pyproject.toml", "package.json", "Cargo.toml"])
def test_marker_makes_a_project(tmp_path: Path, marker: str):
    target = tmp_path / marker
    if marker.startswith("."):
        target.mkdir()
    else:
        target.write_text("{}", encoding="utf-8")
    assert is_project_root(tmp_path) is True


def test_glob_marker_makes_a_project(tmp_path: Path):
    (tmp_path / "App.sln").write_text("", encoding="utf-8")
    assert is_project_root(tmp_path) is True


def test_empty_directory_is_not_a_project(tmp_path: Path):
    assert is_project_root(tmp_path) is False


# ── resolve_project_root ────────────────────────────────────────────────────


def test_cwd_in_a_system_directory_is_not_used(monkeypatch):
    """Сервер, поднятый с cwd=C:\\Windows, не должен резолвить его как проект."""
    monkeypatch.chdir(SYSTEM_ROOT)
    monkeypatch.delenv("MSCODEBASE_PROJECT_PATH", raising=False)
    monkeypatch.delenv("PROJECT_PATH", raising=False)

    resolved = resolve_project_root()

    assert not is_forbidden_root(resolved), f"resolve_project_root вернул {resolved}"


def test_unresolved_placeholder_is_ignored_with_a_warning(monkeypatch, caplog):
    monkeypatch.setenv("PROJECT_PATH", "${workspaceRoot}")
    with caplog.at_level(logging.WARNING, logger="mscodebase_server.project_resolution"):
        assert _try_resolve_path_env("${workspaceRoot}", "PROJECT_PATH") is None
    assert any("плейсхолдер" in r.getMessage() for r in caplog.records)


# ── get_chunks_db_path ──────────────────────────────────────────────────────


def test_chunks_db_is_refused_under_a_system_directory():
    with pytest.raises(ValueError, match="system directory"):
        get_chunks_db_path(SYSTEM_ROOT)


def test_chunks_db_lives_in_the_project(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("MSCODEBASE_CHUNKS_DB", raising=False)
    assert get_chunks_db_path(tmp_path) == (tmp_path / ".mscodebase" / "chunks.db")


def test_chunks_db_env_override_wins(tmp_path: Path, monkeypatch):
    explicit = tmp_path / "custom.db"
    monkeypatch.setenv("MSCODEBASE_CHUNKS_DB", str(explicit))
    assert get_chunks_db_path(SYSTEM_ROOT) == explicit


# ── автоиндексация ──────────────────────────────────────────────────────────


class _FakeIndexer:
    def __init__(self, path: Path) -> None:
        self.project_path = path
        self.indexed: list[Path] = []

    def get_status(self) -> dict:
        return {"total_chunks": 0}

    def index_project(self, path: Path) -> int:  # pragma: no cover - не должен зваться
        self.indexed.append(path)
        return 1


@pytest.mark.asyncio
async def test_auto_index_skips_a_directory_without_project_markers(tmp_path: Path, monkeypatch, caplog):
    from src.mcp import server_factory

    indexer = _FakeIndexer(tmp_path)
    monkeypatch.setattr(
        "src.mcp.tools.base.resolve_indexer_for_request", lambda services: indexer
    )

    with caplog.at_level(logging.WARNING, logger="mscodebase_server"):
        await server_factory._delayed_auto_index(services=object())

    assert indexer.indexed == [], "автоиндексация пошла по каталогу без маркеров проекта"
    assert any("нет маркеров проекта" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_auto_index_runs_for_a_real_project(tmp_path: Path, monkeypatch):
    from src.mcp import server_factory

    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    indexer = _FakeIndexer(tmp_path)
    monkeypatch.setattr(
        "src.mcp.tools.base.resolve_indexer_for_request", lambda services: indexer
    )

    class _Services:
        def resolve(self, _key):
            return None

    await server_factory._delayed_auto_index(services=_Services())

    assert indexer.indexed == [tmp_path], "маркеры проекта есть, автоиндексация обязана пройти"
