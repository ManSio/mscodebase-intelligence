"""gitignore_parser: dir-семантика паттернов (фикс 2026-08-16).

Регрессия: `_match_gitignore_pattern` терял флаг is_dir_pattern (ветка
`pattern.endswith("/")` была мёртвой) — `generated/` не исключал вложенные
файлы. Теперь dir-паттерн матчит директорию на любой глубине и всё под ней
(git-семантика). Затрагивает FileGuard (индексатор) и DocGenerator.
"""

from pathlib import Path

import pytest

from src.core.gitignore_parser import (
    is_file_excluded_by_gitignore,
    load_gitignore_patterns,
)


@pytest.fixture
def proj(tmp_path: Path) -> Path:
    p = tmp_path / "p"
    p.mkdir()
    (p / ".gitignore").write_text("generated/\ndist/\nnotes.txt\n", encoding="utf-8")
    return p


def _excluded(proj: Path, rel: str) -> bool:
    pats = load_gitignore_patterns(proj)
    return is_file_excluded_by_gitignore(proj / rel, proj, pats)


def test_dir_pattern_excludes_nested(proj: Path):
    """«generated/» — всё под директорией (и подвложенными)."""
    assert _excluded(proj, "generated/gen.py")
    assert _excluded(proj, "generated/sub/x.py")
    assert _excluded(proj, "generated")


def test_dir_pattern_matches_any_depth(proj: Path):
    """Без ведущего / dir-паттерн матчит директорию на любой глубине (git)."""
    assert _excluded(proj, "a/b/generated/gen.py")
    assert not _excluded(proj, "src/main.py")
    assert not _excluded(proj, "generatedx/keep.py")


def test_path_dir_pattern_prefix(tmp_path: Path):
    """dir-паттерн со слэшем («docs/demo/casts/») — корневой префикс
    (git: паттерн, содержащий /, root-relative). В отличие от бесслэшевого
    «dist/» (любая глубина), «src/dist/y.py» НЕ матчится."""
    p = tmp_path / "p"
    p.mkdir()
    (p / ".gitignore").write_text("docs/demo/casts/\n", encoding="utf-8")
    pats = load_gitignore_patterns(p)
    assert is_file_excluded_by_gitignore(p / "docs/demo/casts/rec.mp4", p, pats)
    assert not is_file_excluded_by_gitignore(p / "a/docs/demo/casts/x.mp4", p, pats)


def test_file_pattern_unchanged(proj: Path):
    """«notes.txt» — файл на любой глубине (поведение не менялось)."""
    assert _excluded(proj, "notes.txt")
    assert _excluded(proj, "a/b/notes.txt")
    assert not _excluded(proj, "notes.txt.bak")


def test_no_slash_pattern_matches_file_not_dir(tmp_path: Path):
    """Без trailing / паттерн матчит ФАЙЛ с именем, не содержимое директории
    (осознанное ограничение: git матчил бы и директорию — scope-решение 2026-08-16)."""
    p = tmp_path / "p"
    p.mkdir()
    (p / ".gitignore").write_text("cache\n", encoding="utf-8")
    pats = load_gitignore_patterns(p)
    assert is_file_excluded_by_gitignore(p / "cache", p, pats)  # файл с именем
    assert not is_file_excluded_by_gitignore(p / "cache/x.py", p, pats)  # содержимое
