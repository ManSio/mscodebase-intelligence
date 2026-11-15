"""Guard: явный PROJECT_PATH не теряется, когда cwd не является проектом.

Замер 2026-11-16: сервер, запущенный с `cwd=%TEMP%/scratch` и
`PROJECT_PATH=<настоящий проект>`, индексировал пустоту
(`[text-index] done: 0 files`), потому что резолвер был CWD-first без проверки,
похож ли cwd на проект. При этом multi-window поведение (два окна Zed, у каждого
свой cwd-проект) обязано сохраниться.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.core.project_resolution import resolve_project_root


def _project(root: Path, name: str) -> Path:
    proj = root / name
    (proj / "src").mkdir(parents=True)
    (proj / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (proj / "src" / "app.py").write_text("def run() -> None:\n    pass\n", encoding="utf-8")
    return proj


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("MSCODEBASE_PROJECT_PATH", "PROJECT_PATH", "ZED_WORKTREE_ROOT"):
        monkeypatch.delenv(var, raising=False)


def test_project_path_wins_when_cwd_is_not_a_project(tmp_path, monkeypatch):
    real = _project(tmp_path, "real")
    empty = tmp_path / "scratch"
    empty.mkdir()

    monkeypatch.chdir(empty)
    monkeypatch.setenv("PROJECT_PATH", str(real))

    assert resolve_project_root() == real.resolve()


def test_cwd_wins_when_it_is_a_project(tmp_path, monkeypatch):
    """Multi-window: два окна Zed, у каждого свой cwd-проект."""
    cwd_project = _project(tmp_path, "window_a")
    other = _project(tmp_path, "window_b")

    monkeypatch.chdir(cwd_project)
    monkeypatch.setenv("PROJECT_PATH", str(other))

    assert resolve_project_root() == cwd_project.resolve()


def test_mscodebase_project_path_still_has_priority(tmp_path, monkeypatch):
    forced = _project(tmp_path, "forced")
    cwd_project = _project(tmp_path, "window_a")

    monkeypatch.chdir(cwd_project)
    monkeypatch.setenv("MSCODEBASE_PROJECT_PATH", str(forced))

    assert resolve_project_root() == forced.resolve()


def test_cwd_stays_when_nothing_else_is_known(tmp_path, monkeypatch):
    empty = tmp_path / "scratch"
    empty.mkdir()
    monkeypatch.chdir(empty)

    resolved = resolve_project_root()
    assert resolved is not None
    assert resolved.exists()
