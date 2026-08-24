"""test_change_preview.py — e2e превью-патча в изолированном worktree.

Герметичный мини-репо (git init + commit) со всеми контролями:
  - изменение, ломающее тест          → REFUTED (CHANGE WOULD FAIL)
  - изменение, не затрагивающее тесты → VERIFIED (CHANGE WOULD PASS)
  - без изменений                     → INCONCLUSIVE
Скрипт грузится через importlib (scripts/ — не пакет, как в
test_architecture_invariants.py).
"""

import importlib.util
import subprocess
from pathlib import Path


def _load_change_preview():
    spec = importlib.util.spec_from_file_location(
        "change_preview_ut",
        Path(__file__).resolve().parent.parent / "scripts" / "change_preview.py",
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _g(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8"
    )


def _make_repo(tmp_path) -> Path:
    repo = tmp_path / "proj"
    repo.mkdir()
    assert _g(repo, "init", "-b", "main").returncode == 0
    _g(repo, "config", "user.email", "t@t")
    _g(repo, "config", "user.name", "t")
    (repo / "conftest.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parent))\n",
        encoding="utf-8",
    )
    (repo / "src").mkdir()
    (repo / "src" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "src" / "widget.py").write_text(
        "def render():\n    return 1\n", encoding="utf-8"
    )
    (repo / "tests").mkdir()
    (repo / "tests" / "test_widget.py").write_text(
        "from src.widget import render\n\ndef test_render():\n    assert render() == 1\n",
        encoding="utf-8",
    )
    assert _g(repo, "add", "-A").returncode == 0
    assert _g(repo, "commit", "-m", "base").returncode == 0
    return repo


class TestChangePreview:
    def test_refuted_when_test_breaks(self, tmp_path):
        """Положительный контроль: изменение, ломающее тест → REFUTED."""
        mod = _load_change_preview()
        repo = _make_repo(tmp_path)
        (repo / "src" / "widget.py").write_text(
            "def render():\n    return 2\n", encoding="utf-8"
        )
        verdict, _ = mod.ChangePreview(repo, "HEAD", timeout=180).run()
        assert verdict == "REFUTED", verdict

    def test_verified_when_no_test_hit(self, tmp_path):
        """Отрицательный контроль: изменение вне тестов → VERIFIED."""
        mod = _load_change_preview()
        repo = _make_repo(tmp_path)
        # docs-файл: не src/ и не tests/ → зоны пустые, affected_tests пусто
        (repo / "README.md").write_text("hello\n", encoding="utf-8")
        _g(repo, "add", "README.md")
        (repo / "README.md").write_text("hello changed\n", encoding="utf-8")
        verdict, _ = mod.ChangePreview(repo, "HEAD", timeout=180).run()
        assert verdict == "VERIFIED", verdict

    def test_inconclusive_when_no_changes(self, tmp_path):
        mod = _load_change_preview()
        repo = _make_repo(tmp_path)
        verdict, _ = mod.ChangePreview(repo, "HEAD", timeout=60).run()
        assert verdict == "INCONCLUSIVE", verdict

    def test_worktree_cleaned_after_run(self, tmp_path):
        """Ресурс закрыт на всех путях выхода (§5.27): worktree удалён."""
        mod = _load_change_preview()
        repo = _make_repo(tmp_path)
        wts_before = _g(repo, "worktree", "list").stdout
        (repo / "README.md").write_text("x\n", encoding="utf-8")
        mod.ChangePreview(repo, "HEAD", timeout=120).run()
        wts_after = _g(repo, "worktree", "list").stdout
        assert wts_before == wts_after, "worktree не очищен после превью"
