"""Structural search must prune heavy directories instead of walking them.

Observation 2026-11-07: `structural_search` timed out at 15 s on a built-in
pattern because it collected files with `project_path.rglob()` over venv/,
models/ and experiments/ (≈2 GB) and only then filtered them.
"""

from __future__ import annotations

import time
from pathlib import Path

from src.core.indexing.parser import CodeParser
from src.core.structural_search import StructuralSearcher


def _tree(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("class A:\n    pass\n", encoding="utf-8")
    for heavy in ("venv", "models", "experiments", ".codebase_models", "node_modules"):
        d = root / heavy
        d.mkdir()
        (d / "noise.py").write_text("class Noise:\n    pass\n", encoding="utf-8")
    return root


def test_walk_prunes_heavy_directories(tmp_path):
    searcher = StructuralSearcher(CodeParser())
    root = _tree(tmp_path)

    found = list(searcher._iter_source_files(root, ".py"))

    names = {p.name for p in found}
    assert "a.py" in names
    assert "noise.py" not in names


def test_search_is_fast_on_small_tree(tmp_path):
    searcher = StructuralSearcher(CodeParser())
    root = _tree(tmp_path)
    t0 = time.perf_counter()
    result = searcher.search(root, pattern_name="class_inheritance", max_results=5)
    elapsed = time.perf_counter() - t0

    assert result.files_scanned >= 1
    assert elapsed < 5.0, f"scan took {elapsed:.1f}s"
