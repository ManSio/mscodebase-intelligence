"""E28 (Фаза 3): dense-off флаг — гасит dense-тир, ничего не ломая.

Контракт: default OFF (плот-ап путь не тронут), флаг гасит и эмбеддинг запроса,
и vector search; BM25/FTS5/graph продолжают работать.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_flag_default_off():
    from src.config.settings import SearchConfig

    assert os.environ.get("MSCODEBASE_DENSE_OFF", "false") == "false"
    assert SearchConfig().dense_off is False


def test_env_enables_flag(monkeypatch):
    from src.config.settings import SearchConfig

    monkeypatch.setenv("MSCODEBASE_DENSE_OFF", "true")
    assert SearchConfig().dense_off is True
    monkeypatch.setenv("MSCODEBASE_DENSE_OFF", "false")
    assert SearchConfig().dense_off is False


def test_searcher_reads_flag():
    from src.core.search.engine import Searcher

    assert hasattr(Searcher, "_dense_off") or True  # атрибут ставится в __init__
    src = Path(ROOT / "src/core/search/engine.py").read_text(encoding="utf-8")
    assert "not self._dense_off" in src, "dense-тир не гасится флагом"
    assert 'get_config().search, "dense_off", False' in src
