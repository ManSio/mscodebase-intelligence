"""Guard: системный каталог не становится «проектом» и не получает `.mscodebase`.

Живой инцидент 2026-11-15: хост запустил MCP-сервер с cwd=`C:\\Windows` и
`PROJECT_PATH='${workspaceRoot}'` (неразвёрнутый плейсхолдер). Резолвер откатился
на cwd, автоиндексация пошла по `C:\\Windows`, и в каталоге ОС появилась
`chunks.db` на 105 МБ (10 264 чанка системных файлов).

Тесты платформо-зависимые: на Windows проверяются `C:\\Windows`/`Program Files`,
на POSIX — `/usr`, `/etc`, `/home`. Обе линии гоняются в CI (ubuntu + windows).
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import pytest

from src.core.indexing.chunk_store import get_chunks_db_path
from src.core.project_resolution import (
    _forbidden_roots,
    _reject_self_index_target,
    _try_resolve_path_env,
    is_forbidden_root,
    is_project_root,
    resolve_project_root,
)

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    SYSTEM_ROOT = Path(os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows")
    SYSTEM_CHILDREN = [SYSTEM_ROOT, SYSTEM_ROOT / "System32"]
else:
    SYSTEM_ROOT = Path("/usr")
    SYSTEM_CHILDREN = [Path("/usr"), Path("/usr/lib"), Path("/etc")]


def _existing_dir(path: Path) -> bool:
    return path.is_dir()


# ── is_forbidden_root ───────────────────────────────────────────────────────


def test_system_roots_are_forbidden():
    for path in SYSTEM_CHILDREN:
        if _existing_dir(path):
            assert is_forbidden_root(path) is True, f"{path} должен считаться системным"


def test_profile_root_is_forbidden():
    assert is_forbidden_root(Path.home()) is True


def test_temp_root_is_forbidden():
    import tempfile

    assert is_forbidden_root(Path(tempfile.gettempdir())) is True


def test_project_inside_home_is_allowed():
    """`~/projects/x` — нормальный проект; режем только сам `~`."""
    assert is_forbidden_root(Path.home() / "projects" / "demo") is False


def test_project_inside_home_or_temp_is_allowed(tmp_path: Path):
    """Проект под `~` или `%TEMP%` — норма (pytest сам живёт в temp)."""
    assert is_forbidden_root(tmp_path) is False


def test_posix_roots_are_in_the_forbidden_set():
    """Состав набора проверяется на любой платформе (CI: ubuntu + windows)."""
    listed = {p.as_posix() for p in _forbidden_roots()}
    assert "/usr" in listed and "/etc" in listed


def test_filesystem_root_is_forbidden():
    assert is_forbidden_root(Path(Path.cwd().anchor)) is True


def test_project_directory_is_not_forbidden(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    assert is_forbidden_root(tmp_path) is False


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


def test_directory_with_code_files_is_a_project(tmp_path: Path):
    """Папка со скриптами без VCS — тоже проект (иначе ломается автоиндексация)."""
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    assert is_project_root(tmp_path) is True


def _make_chunks_db(path: Path, rows: int, *, keep_open: bool = False):
    """Настоящая chunks.db с N чанками. keep_open=True оставляет WAL незакрытым."""
    import sqlite3

    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("pragma journal_mode=wal")
    con.execute("create table chunks (id integer primary key, file_path text, text text)")
    con.executemany(
        "insert into chunks (file_path, text) values (?, ?)",
        [(f"src/m{i}.py", f"def fn_{i}(): pass") for i in range(rows)],
    )
    con.commit()
    if keep_open:
        return con
    con.close()
    return None


def test_previously_indexed_directory_is_a_project(tmp_path: Path):
    """Если человек уже индексировал каталог (в chunks.db есть данные), это проект."""
    _make_chunks_db(tmp_path / ".mscodebase" / "chunks.db", 5)
    assert is_project_root(tmp_path) is True


def test_live_index_in_wal_counts_as_a_project(tmp_path: Path):
    """Живой индекс: данные в `chunks.db-wal`, основной файл — 4096 b.

    Замер ревью 2026-11-16: 40 чанков при открытом соединении давали db 4096 b,
    и каталог переставал считаться проектом, хотя индекс реально есть.
    """
    con = _make_chunks_db(tmp_path / ".mscodebase" / "chunks.db", 40, keep_open=True)
    try:
        db = tmp_path / ".mscodebase" / "chunks.db"
        wal = tmp_path / ".mscodebase" / "chunks.db-wal"
        assert db.stat().st_size <= 8192, "условия теста: основной файл ещё пустой"
        assert wal.exists() and wal.stat().st_size > 0, "условия теста: данные в WAL"
        assert is_project_root(tmp_path) is True
    finally:
        con.close()


def test_empty_closed_index_does_not_make_a_project(tmp_path: Path):
    """Пустая (0 чанков) chunks.db — след запуска, а не признак проекта."""
    _make_chunks_db(tmp_path / ".mscodebase" / "chunks.db", 0)
    assert is_project_root(tmp_path) is False


def test_garbage_chunks_file_is_not_an_index(tmp_path: Path):
    """Мусорный файл нужного размера — не индекс (ревью 2026-11-16)."""
    (tmp_path / ".mscodebase").mkdir()
    (tmp_path / ".mscodebase" / "chunks.db").write_bytes(b"\0" * 32768)
    assert is_project_root(tmp_path) is False


def test_garbage_chunks_file_with_wal_is_not_an_index(tmp_path: Path):
    (tmp_path / ".mscodebase").mkdir()
    (tmp_path / ".mscodebase" / "chunks.db").write_bytes(b"\0" * 4096)
    (tmp_path / ".mscodebase" / "chunks.db-wal").write_bytes(b"\0" * 16384)
    assert is_project_root(tmp_path) is False


def test_index_with_only_a_symbol_graph_is_a_project(tmp_path, monkeypatch):
    """Проект может иметь только канонический graph.db (вне каталога проекта)."""
    from src.core import artifact_paths

    project = tmp_path / "proj"
    project.mkdir()
    data_root = tmp_path / "data"
    monkeypatch.setattr(artifact_paths, "get_data_root", lambda: data_root)

    graph_dir = artifact_paths._compute_project_dir(project)
    graph_dir.mkdir(parents=True)
    (graph_dir / "graph.db").write_bytes(b"\0" * 16384)

    assert is_project_root(project) is True


def test_tiny_graph_file_does_not_make_a_project(tmp_path, monkeypatch):
    """Пустая graph.db (4 КБ) — не признак проекта."""
    from src.core import artifact_paths

    project = tmp_path / "proj"
    project.mkdir()
    data_root = tmp_path / "data"
    monkeypatch.setattr(artifact_paths, "get_data_root", lambda: data_root)
    graph_dir = artifact_paths._compute_project_dir(project)
    graph_dir.mkdir(parents=True)
    (graph_dir / "graph.db").write_bytes(b"\0" * 4096)

    assert is_project_root(project) is False



def test_directory_with_only_documents_is_not_a_project(tmp_path: Path):
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    (tmp_path / "photo.jpg").write_bytes(b"\xff\xd8")
    assert is_project_root(tmp_path) is False


# ── resolve_project_root ────────────────────────────────────────────────────


def test_cwd_in_a_system_directory_is_not_used(monkeypatch):
    """Сервер, поднятый с cwd=C:\\Windows (или /usr), не должен брать его как проект."""
    monkeypatch.chdir(SYSTEM_ROOT)
    monkeypatch.delenv("MSCODEBASE_PROJECT_PATH", raising=False)
    monkeypatch.delenv("PROJECT_PATH", raising=False)

    resolved = resolve_project_root()

    assert not is_forbidden_root(resolved), f"resolve_project_root вернул {resolved}"


def test_explicit_project_root_in_a_system_directory_is_ignored(monkeypatch):
    """Явный аргумент инструмента — не повод индексировать ОС."""
    monkeypatch.delenv("MSCODEBASE_PROJECT_PATH", raising=False)
    monkeypatch.delenv("PROJECT_PATH", raising=False)
    resolved = resolve_project_root(provided=str(SYSTEM_ROOT))
    assert not is_forbidden_root(resolved)


def test_active_workspace_on_a_system_directory_is_rejected():
    """Даже «явный» источник не делает проект из каталога ОС."""
    assert _reject_self_index_target(SYSTEM_ROOT, source="ACTIVE_WORKSPACE") is True


def test_unresolved_placeholder_is_ignored_with_a_warning(caplog):
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
