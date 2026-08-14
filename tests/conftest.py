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
