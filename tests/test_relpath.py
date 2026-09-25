"""Guard: relative paths are canonical POSIX (index bloat root cause 2026-09-25)."""
from pathlib import Path

from src.core.relpath import normalize_rel_path


def test_backslashes_become_slashes():
    assert normalize_rel_path("src\\core\\indexer.py") == "src/core/indexer.py"


def test_posix_is_unchanged():
    assert normalize_rel_path("src/core/indexer.py") == "src/core/indexer.py"


def test_accepts_path_objects():
    assert normalize_rel_path(Path("a") / "b" / "c.py") in ("a/b/c.py", "a\\b\\c.py")
    assert normalize_rel_path(Path("a") / "b" / "c.py").count("/") == 2


def test_idempotent():
    once = normalize_rel_path("x\\y\\z.md")
    assert normalize_rel_path(once) == once


def test_two_forms_collapse_to_one():
    # The exact bug: same file, two separators -> one canonical key.
    assert normalize_rel_path("src\\core\\x.py") == normalize_rel_path("src/core/x.py")
