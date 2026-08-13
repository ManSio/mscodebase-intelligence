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
def _isolated_data_root(tmp_path: Path, monkeypatch) -> Path:
    """Изолирует data_root в pytest tmp для всех тестов (см. docstring)."""
    root = tmp_path / "mscodebase_data"
    monkeypatch.setenv("MSCODEBASE_DATA_DIR", str(root))
    return root
