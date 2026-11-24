"""Guards for test/process isolation (audit 2026-11-24).

Two defects were reproduced on this checkout:

1. ``Searcher(MagicMock(), ...)`` built a SQLite chunk store from
   ``mock.project_path`` and created ``<cwd>/MagicMock/mock.project_path/<id>/
   .mscodebase/chunks.db`` -- 491 files / 16.3 MB per tree after a few runs.
2. The process-global log handler was bound to the *real* data root
   (``D:\\mscodebase-data\\logs\\mcp_global.log``) before the per-test
   ``MSCODEBASE_DATA_DIR`` override; 672 ``MagicMock`` lines from one suite run
   landed in the production log.

The negative guards must fail on the pre-fix code; the positive controls below
make sure the guard did not simply disable the production path.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from src.config.settings import get_config
from src.core.search.engine import Searcher


def _file_handlers(logger: logging.Logger, root: Path) -> list[logging.FileHandler]:
    """Handlers writing under *root*; independent of the fix's ownership marker."""
    return [
        handler for handler in logger.handlers
        if isinstance(handler, logging.FileHandler)
        and Path(handler.baseFilename).is_relative_to(root)
    ]


def test_mock_project_path_does_not_create_a_chunk_store(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    search = get_config().search
    assert search.sqlite_chunks or search.dense_off, (
        "precondition: the SQLite chunk-store path must be enabled"
    )

    indexer = MagicMock()
    indexer.project_path = MagicMock(name="project_path")

    searcher = Searcher(indexer, MagicMock())

    assert searcher._chunk_store is None, (
        "a non-path project_path must not become a SQLite location: "
        f"got {getattr(searcher._chunk_store, 'db_path', None)!r}"
    )
    assert not (tmp_path / "MagicMock").exists()


def test_real_project_path_still_creates_a_chunk_store(tmp_path, monkeypatch):
    """Positive control: the guard must not disable the production path."""
    monkeypatch.chdir(tmp_path)
    search = get_config().search
    assert search.sqlite_chunks or search.dense_off, (
        "precondition: the SQLite chunk-store path must be enabled"
    )

    indexer = MagicMock()
    indexer.project_path = tmp_path

    searcher = Searcher(indexer, MagicMock())

    assert searcher._chunk_store is not None
    assert Path(searcher._chunk_store.db_path).is_relative_to(tmp_path)


def test_blank_string_project_path_is_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    indexer = MagicMock()
    indexer.project_path = "   "

    searcher = Searcher(indexer, MagicMock())

    assert searcher._chunk_store is None
    assert not (tmp_path / ".mscodebase").exists()


def test_log_handler_follows_the_current_data_root(tmp_path, monkeypatch):
    """The handler must move with MSCODEBASE_DATA_DIR, close the old file,
    stay single per logger, and rebind when a root is revisited (A -> B -> A).
    """
    import src.core.log_manager as log_manager

    root_logger = logging.getLogger("mscodebase")
    mcp_logger = logging.getLogger("mscodebase_server")
    before = {id(h) for lg in (root_logger, mcp_logger) for h in lg.handlers}

    def _reset():
        for logger in (root_logger, mcp_logger):
            for handler in list(logger.handlers):
                if id(handler) not in before:
                    logger.removeHandler(handler)
                    handler.close()
        log_manager._initialized_projects.clear()

    _reset()
    try:
        first = tmp_path / "first"
        second = tmp_path / "second"
        project = tmp_path / "project"

        monkeypatch.setenv("MSCODEBASE_DATA_DIR", str(first))
        log_manager.setup_project_logging(project, project_label="isolation_probe")
        logging.getLogger("mscodebase").warning("first root")
        for handler in _file_handlers(root_logger, first) + _file_handlers(mcp_logger, first):
            handler.flush()
        assert (first / "logs" / "isolation_probe.log").is_file()
        assert len(_file_handlers(root_logger, first)) == 1
        assert len(_file_handlers(mcp_logger, first)) == 1

        # Same project + same root: no duplicate handler on either logger.
        log_manager.setup_project_logging(project, project_label="isolation_probe")
        assert len(_file_handlers(root_logger, first)) == 1
        assert len(_file_handlers(mcp_logger, first)) == 1

        original = _file_handlers(root_logger, first)[0]

        monkeypatch.setenv("MSCODEBASE_DATA_DIR", str(second))
        log_manager.setup_project_logging(project, project_label="isolation_probe")

        assert _file_handlers(root_logger, first) == []
        assert _file_handlers(mcp_logger, first) == []
        assert original.stream is None, "old handler must be closed, not just detached"
        assert original not in root_logger.handlers
        assert original not in mcp_logger.handlers

        logging.getLogger("mscodebase").warning("second root")
        logging.getLogger("mscodebase_server").warning("second root via server")
        for handler in _file_handlers(root_logger, second) + _file_handlers(mcp_logger, second):
            handler.flush()
        assert (second / "logs" / "isolation_probe.log").is_file()
        content = (second / "logs" / "isolation_probe.log").read_text(encoding="utf-8")
        assert "second root" in content
        assert "second root via server" in content

        # A -> B -> A must rebind again, not return silently at the stale key.
        monkeypatch.setenv("MSCODEBASE_DATA_DIR", str(first))
        log_manager.setup_project_logging(project, project_label="isolation_probe")
        logging.getLogger("mscodebase").warning("back to first")
        for handler in _file_handlers(root_logger, first) + _file_handlers(mcp_logger, first):
            handler.flush()
        assert "back to first" in (
            first / "logs" / "isolation_probe.log"
        ).read_text(encoding="utf-8")
        assert _file_handlers(root_logger, second) == []
    finally:
        _reset()


def test_runtime_metrics_file_is_not_tracked():
    """The server rewrites this file every 10 calls; git must not track it."""
    import subprocess

    repo = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "telemetry/tool_metrics.json"],
        cwd=repo,
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert proc.returncode != 0, (
        "telemetry/tool_metrics.json is runtime state written by the MCP server; "
        "tracking it makes every server run dirty the work tree"
    )


def test_conftest_pins_a_temp_session_root():
    import conftest

    assert conftest.SESSION_DATA_ROOT.is_dir()
    assert conftest.SESSION_DATA_ROOT.is_relative_to(Path(tempfile.gettempdir()))
