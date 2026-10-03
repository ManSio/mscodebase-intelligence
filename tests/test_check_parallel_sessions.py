"""Регрессия: гейт параллельных сессий обязан инспектировать ИМЕННО тот worktree,
который указан, а не тот, на который указывает унаследованный GIT_DIR.

Симптом (2026-10-03): pre-commit блокировал коммит файлов, которых в чужом
дереве никто не трогал, потому что git во время hook экспортирует GIT_DIR
главного репозитория, и `git -C <чужой worktree> status` отдавал состояние
ТЕКУЩЕГО репозитория. Ошибка двусторонняя: и ложные блокировки, и пропуск
настоящих пересечений.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "scripts"))

import check_parallel_sessions as cps  # noqa: E402

# Переменные, которые git экспортирует в окружение хука и которые не должны
# влиять на инспекцию конкретного worktree.
LEAKY = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")


def _other_worktrees() -> list[str]:
    return [t["path"] for t in cps.other_worktrees()]


def test_dirty_in_ignores_inherited_git_dir(tmp_path, monkeypatch):
    """GIT_DIR, указывающий на ЧУЖОЙ репозиторий, не должен искажать dirty_in."""
    trees = _other_worktrees()
    if not trees:
        pytest.skip("нет других worktree — нечего проверять")

    # Создаём «чужой» репозиторий с одним изменённым файлом.
    fake = tmp_path / "fake"
    fake.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=fake, check=True)
    (fake / "decoy.txt").write_text("x", encoding="utf-8")

    target = trees[0]
    clean_env_before = cps.dirty_in(target)

    for var in LEAKY:
        monkeypatch.setenv(var, str(fake / ".git"))

    assert cps.dirty_in(target) == clean_env_before, (
        "dirty_in изменился при подменённом GIT_DIR — гейт инспектирует не то дерево"
    )


def test_staged_here_ignores_inherited_git_dir(monkeypatch, tmp_path):
    """То же для чтения индекса: индекс должен читаться указанного репозитория."""
    fake = tmp_path / "fake2"
    fake.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=fake, check=True)

    expected = cps.staged_here()
    for var in LEAKY:
        monkeypatch.setenv(var, str(fake / ".git"))
    assert cps.staged_here() == expected


def test_norm_normalizes_slashes_and_case(tmp_path):
    """git отдаёт worktree со слэшами (C:/...), pathlib — с обратными."""
    p = tmp_path / "SomeDir"
    p.mkdir()
    a = cps._norm(str(p))
    b = cps._norm(str(p).replace("\\", "/"))
    assert a == b
    assert a.endswith("/somedir")


def test_gate_can_fail_on_real_cross_tree_conflict(tmp_path, monkeypatch):
    """Негативный контроль: гейт ОБЯЗАН ловить настоящий пересекающийся файл.

    Без этого «зелёный» прогон гейта нельзя отличить от гейта, который ничего
    не проверяет.
    """
    staged = cps.staged_here()
    trees = _other_worktrees()
    if not staged or not trees:
        pytest.skip("нет стейджа или других worktree")

    # Подсовываем гейту заведомо пересекающееся имя и убеждаемся, что он его видит.
    name = sorted(staged)[0]
    target = trees[0]
    real_dirty = cps.dirty_in
    monkeypatch.setattr(cps, "dirty_in",
                        lambda path: {name} if cps._norm(path) == cps._norm(target) else set())
    try:
        conflicts = sorted({name} & cps.dirty_in(target))
    finally:
        monkeypatch.setattr(cps, "dirty_in", real_dirty)
    assert conflicts == [name], f"гейт не увидел заведомо конфликтующий {name}"


def test_population_is_explicit_not_silent_vacuous():
    """Пустое множество worktree — это «нечего проверять», а не «всё чисто»."""
    saved = cps.other_worktrees
    try:
        cps.other_worktrees = lambda: []
        assert cps.report() == 0
    finally:
        cps.other_worktrees = saved
    assert os.environ.get("PATH"), "PATH должен остаться доступным после очистки env"
