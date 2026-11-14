"""
Root conftest.py — adds project root to sys.path so `from src.*` imports work.

⚠️ Autouse-фикстура _isolated_data_root изолирует data_root от реального
каталога пользователя для ВСЕХ тестов (аудит 2026-08-13): исторически тесты,
создающие Indexer/JobHistoryStore/CommitMemory с pytest tmp_path, писали папки
<data_root>/projects/<hash> в реальный %LOCALAPPDATA%/mscodebase — каждый
прогон создавал новую папку (pytest tmp_path уникален на запуск), итог —
>2400 папок при ~2 реальных проектах. Теперь каждая тестовая сессия пишет
в свой tmp_path, который pytest удаляет автоматически.
"""

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(autouse=True)
def _no_console_windows(monkeypatch):
    """Windows: дочерние процессы тестов не создают видимых окон консоли.

    Терминальная панель Zed запускается без консоли → любой console-процесс
    без CREATE_NO_WINDOW получает собственное окно (наблюдалось: 2 окна при
    прогоне тестов). Патчим subprocess.Popen — базовый примитив: run,
    check_output, check_call, call используют его, фикстура покрывает все
    вызовы без явных creationflags. Не влияет на POSIX.
    """
    if sys.platform != "win32":
        return

    import subprocess

    _orig_popen = subprocess.Popen

    def _popen_no_window(*args, **kwargs):
        if "creationflags" not in kwargs:
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return _orig_popen(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", _popen_no_window)


@pytest.fixture(autouse=True)
def _isolated_data_root(tmp_path: Path, monkeypatch) -> Path:
    """Изолирует data_root в pytest tmp для всех тестов (см. docstring)."""
    root = tmp_path / "mscodebase_data"
    monkeypatch.setenv("MSCODEBASE_DATA_DIR", str(root))
    return root


@pytest.fixture(autouse=True)
def _reset_consistency_tracker():
    """Сброс глобального ConsistencyTracker между тестами (синглтон).

    С Edition 2026-09-10 (fail-closed freshness gate) глобальный синглтон
    consistency-tracker живёт между тестами и может оставить STALE-состояние,
    которое блокирует intel_add_memory_node в последующих тестах. Invalidate
    до и после теста гарантирует UNKNOWN (default) для каждого теста.
    """
    from src.core.consistency import get_consistency_tracker

    get_consistency_tracker().invalidate()
    yield
    get_consistency_tracker().invalidate()


@pytest.fixture(autouse=True)
def _fusion_default(monkeypatch):
    """The suite must not depend on the shell: fusion defaults to `weights`.

    `MSCODEBASE_FUSION` is a process-global experiment switch; without this an
    exported variable makes local runs disagree with CI (found in review).
    Tests that exercise another arm set it themselves — their `monkeypatch`
    runs after this fixture, so it wins.
    """
    monkeypatch.delenv("MSCODEBASE_FUSION", raising=False)



# --- One suite per tree -------------------------------------------------------
# Observed 2026-11-14: a timed-out commit left `verify_diary -> pytest` running,
# then a second full suite started. The two competed for CPU; a test that takes
# <0.01s alone was reported at 654s, and the run looked like a hang. The OS
# releases this lock when the process dies, so a crash cannot leave it stale.

SUITE_LOCK = PROJECT_ROOT / ".pytest_cache" / "suite.lock"
_LOCK_INHERITED = "MSCB_SUITE_LOCK_INHERITED"


def _acquire_file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"x")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def _release_file_lock(handle) -> None:
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    finally:
        handle.close()


@pytest.fixture(scope="session", autouse=True)
def _one_suite_per_tree():
    """Refuse to start a second pytest on the same checkout.

    A nested pytest spawned by a test inherits MSCB_SUITE_LOCK_INHERITED=1 and
    skips the check, so `test_bootstrap_pipeline` still works.
    """
    if os.environ.get(_LOCK_INHERITED) == "1":
        yield
        return
    handle = _acquire_file_lock(SUITE_LOCK)
    if handle is None:
        pytest.exit(
            "Another pytest run already holds .pytest_cache/suite.lock. Two suites on "
            "one tree make timings meaningless and can race on shared temp data. Wait "
            "for it to finish; if no run is active, delete the file and retry.",
            returncode=3,
        )
    os.environ[_LOCK_INHERITED] = "1"
    try:
        yield
    finally:
        os.environ.pop(_LOCK_INHERITED, None)
        _release_file_lock(handle)
