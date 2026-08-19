"""_scan_disk_files — исключение не-индексируемых каталогов.

Регрессия 2026-08-14: health._check_filesystem_sync rglob'ил venv/ (22k файлов
из verify_clean_state.sh) → кап 10001 → «осиротевшие файлы» = артефакт среза
(273 ложных orphan при 0 реальных).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.core.intelligence.health import _scan_disk_files  # noqa: E402


def test_excludes_venv_and_git(tmp_path):
    """venv/.git не входят в файловый манифест (не индексируются)."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("x", encoding="utf-8")
    (tmp_path / "venv" / "Lib" / "site-packages").mkdir(parents=True)
    for i in range(20):
        (tmp_path / "venv" / "Lib" / "site-packages" / f"pkg{i}.py").write_text("x", encoding="utf-8")
    (tmp_path / ".git" / "objects").mkdir(parents=True)
    (tmp_path / ".git" / "objects" / "ab").write_text("x", encoding="utf-8")

    files, count, truncated = _scan_disk_files(tmp_path)
    assert "src/main.py" in files
    assert not any("venv" in f or ".git" in f for f in files)
    assert count == 2  # каталог src + src/main.py (счётчик — все не-исключённые пути)
    assert truncated is False


def test_cap_truncation_detected(tmp_path):
    """Реальный кап для исходников (не venv) всё ещё детектируется."""
    for i in range(15):
        (tmp_path / f"f{i}.py").write_text("x", encoding="utf-8")
    files, count, truncated = _scan_disk_files(tmp_path, cap=10)
    assert truncated is True
    assert count == 11  # кап+1
    assert len(files) == 10


def test_nested_git_repo_pruned(tmp_path):
    """Клон/чек-аут (каталог с собственным .git) не исходники проекта (2026-08-18)."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("x", encoding="utf-8")
    nested = tmp_path / "external_clone"
    (nested / ".git").mkdir(parents=True)
    for i in range(20):
        (nested / f"f{i}.py").write_text("x", encoding="utf-8")
    files, count, truncated = _scan_disk_files(tmp_path)
    # внешний клон с 20 файлами не ломает счётчик/cap — прунится
    assert not any("external_clone" in f for f in files)
    assert truncated is False
    assert count == 2  # src + src/main.py


def test_real_project_scan_without_venv():
    """На реальном проекте скан без venv даёт ~1.5k файлов, не 24k (без среза)."""
    files, count, truncated = _scan_disk_files(ROOT)
    assert truncated is False, "проект без venv не должен упираться в кап"
    assert not any("venv" in f for f in files)
    assert count < 10000
