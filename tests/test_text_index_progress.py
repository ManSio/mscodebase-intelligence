"""Phase 3 text index: progress reporting and callback isolation.

Observation 2026-11-07: a full text reindex left the UI at 10% for the whole
run because `_index_text_only_project` never called the progress callback the
reindex job passes in. The callback now gets (current, done, total, phase),
and a raising callback must not abort indexing.
"""

from __future__ import annotations

from pathlib import Path

from src.core.indexing.indexer import Indexer


class _Pipeline:
    def process_file(self, **kwargs):
        return {"rel_path": kwargs["rel_path_str"], "skip_vectors": True}


class _Writer:
    def write_text_records(self, parsed):
        return [1]


class _Store:
    def all_records(self):
        return []

    def delete_files(self, stale):  # pragma: no cover — не должно вызываться
        raise AssertionError(f"unexpected prune: {stale}")


class _Guard:
    def should_skip_dir(self, name: str) -> bool:
        return name in {"skipdir", ".git"}

    def should_skip_file(self, path: Path) -> bool:
        return path.name == "skipme.py"


class _Self:
    file_guard = _Guard()
    _pipeline = _Pipeline()
    _db_writer = _Writer()
    _chunk_store = _Store()

    @staticmethod
    def watchdog_heartbeat(label: str = "") -> None:
        return None


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "pkg").mkdir(parents=True)
    (root / "a.py").write_text("print(1)\n", encoding="utf-8")
    (root / "pkg" / "b.py").write_text("print(2)\n", encoding="utf-8")
    (root / "skipme.py").write_text("print(3)\n", encoding="utf-8")
    (root / "empty.py").write_text("   \n", encoding="utf-8")
    (root / "skipdir").mkdir()
    (root / "skipdir" / "c.py").write_text("print(4)\n", encoding="utf-8")
    return root


def test_progress_reaches_total_and_uses_parsing_phase(tmp_path):
    calls: list[tuple[int, int, str]] = []
    root = _project(tmp_path)

    count = Indexer._index_text_only_project(
        _Self(), root, lambda cur, done, total, phase: calls.append((done, total, phase))
    )

    # 2 индексируемых файла (+ empty.py отчитывается, но чанков не даёт).
    assert count == 2
    assert calls, "progress callback must be called"
    assert all(phase == "parsing" for _, _, phase in calls)
    assert calls[-1][:2] == (3, 3), calls
    assert max(done for done, _, _ in calls) == 3


def test_raising_callback_does_not_abort_indexing(tmp_path):
    def boom(*args, **kwargs):
        raise RuntimeError("callback exploded")

    count = Indexer._index_text_only_project(_Self(), _project(tmp_path), boom)

    assert count == 2
