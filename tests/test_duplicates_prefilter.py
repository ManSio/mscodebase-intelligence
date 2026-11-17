"""Guard: отсечение пар в find_duplicates не теряет настоящие дубликаты."""
from __future__ import annotations

from pathlib import Path

from src.core.duplication import find_duplicates


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "pkg").mkdir(parents=True)
    body = "def {name}(a, b):\n    total = a + b\n    total = total * 2\n    return total\n"
    (root / "a.py").write_text(body.format(name="alpha"), encoding="utf-8")
    (root / "b.py").write_text(body.format(name="beta"), encoding="utf-8")
    (root / "c.py").write_text(
        "def gamma(a):\n    return a\n", encoding="utf-8"
    )
    return root


def test_size_prefilter_keeps_identical_bodies(tmp_path):
    result = find_duplicates(_project(tmp_path), threshold=0.85, min_tokens=4)

    assert result["status"] == "ok"
    assert result["exact_count"] >= 1, result
    names = {
        s["name"]
        for group in result["exact_groups"]
        for s in group["symbols"]
    }
    assert {"alpha", "beta"} <= names


def test_scan_reports_limits(tmp_path):
    result = find_duplicates(_project(tmp_path), max_files=2)

    assert result["status"] == "ok"
    assert result["files_scanned"] <= 2


def test_max_files_is_respected(tmp_path):
    result = find_duplicates(_project(tmp_path), max_files=1)
    assert result["files_scanned"] == 1
