"""Тесты Фазы 1 Universal Engine: LocalFsSource + WorkspaceSource wiring.

Покрывает:
- resolve(): нормализованный локальный путь (без смены поведения);
- fingerprint(): стабилен, меняется при модификации, игнорирует dot-каталоги;
- watch(): poll-наблюдатель выдаёт событие при смене fingerprint;
- Indexer: принимает WorkspaceSource и берёт path_manager из него (ТЗ §2.1).
"""

import asyncio
from pathlib import Path

from src.core.interfaces.workspace_source import WorkspaceSource
from src.sources.local_fs import LocalFsSource


def _populate(root: Path) -> None:
    (root / "a.py").write_text("def a(): pass\n", encoding="utf-8")
    (root / "b.py").write_text("def b(): pass\n", encoding="utf-8")
    (root / "sub").mkdir()
    (root / "sub" / "c.py").write_text("def c(): pass\n", encoding="utf-8")


def test_implements_protocol(tmp_path):
    src = LocalFsSource(tmp_path)
    assert isinstance(src, WorkspaceSource)  # runtime_checkable Protocol


def test_resolve_returns_normalized_root(tmp_path):
    src = LocalFsSource(tmp_path)
    resolved = asyncio.run(src.resolve())
    assert resolved == tmp_path.resolve()


def test_fingerprint_stable_across_calls(tmp_path):
    _populate(tmp_path)
    src = LocalFsSource(tmp_path)
    fp1 = src.fingerprint()
    fp2 = src.fingerprint()
    assert fp1 == fp2
    assert len(fp1) == 64  # sha256 hex


def test_fingerprint_changes_on_file_modify(tmp_path):
    _populate(tmp_path)
    src = LocalFsSource(tmp_path)
    before = src.fingerprint()
    (tmp_path / "a.py").write_text("def a(): return 42\n", encoding="utf-8")
    after = src.fingerprint()
    assert after != before


def test_fingerprint_ignores_dot_entries(tmp_path):
    _populate(tmp_path)
    src = LocalFsSource(tmp_path)
    before = src.fingerprint()
    dot = tmp_path / ".git"
    dot.mkdir()
    (dot / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    assert src.fingerprint() == before  # .git не влияет на fingerprint


async def test_watch_yields_event_on_change(tmp_path):
    _populate(tmp_path)
    src = LocalFsSource(tmp_path, path_manager=None)

    async def consume():
        events = []
        async for ev in src.watch(interval_seconds=0.05):
            events.append(ev)
            if len(events) >= 1:
                return events
        return events

    task = asyncio.ensure_future(consume())
    await asyncio.sleep(0.12)  # первый poll отработал, fingerprint стабилен
    (tmp_path / "b.py").write_text("def b(): return 1\n", encoding="utf-8")

    events = await asyncio.wait_for(task, timeout=5.0)
    assert len(events) == 1
    assert events[0].kind == "fingerprint_changed"
    assert events[0].fingerprint is not None


def test_indexer_uses_injected_source_path_manager(tmp_path):
    from unittest.mock import MagicMock

    from src.core.indexing.indexer import Indexer

    db_path = tmp_path / ".db" / "index.db"
    db_path.parent.mkdir(parents=True)
    source = LocalFsSource(tmp_path)
    indexer = Indexer(
        db_path,
        MagicMock(),
        MagicMock(),
        project_path=tmp_path,
        source=source,
    )
    assert indexer._source is source
    assert indexer.path_manager is source.path_manager


def test_indexer_default_source_is_local_fs(tmp_path):
    from unittest.mock import MagicMock

    from src.core.indexing.indexer import Indexer

    db_path = tmp_path / ".db" / "index.db"
    db_path.parent.mkdir(parents=True)
    indexer = Indexer(
        db_path,
        MagicMock(),
        MagicMock(),
        project_path=tmp_path,
    )
    assert isinstance(indexer._source, LocalFsSource)
    assert isinstance(indexer.path_manager, LocalFsSource(tmp_path).path_manager.__class__)
