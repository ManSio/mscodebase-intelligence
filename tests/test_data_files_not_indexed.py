"""Данные (.json) не индексируются по умолчанию — MSCODEBASE_INDEX_DATA.

Замер 2026-11-17: .json — 62.3% индекса engraphis (31 123 из 49 920 чанков),
ни одна кодовая выдача от них не выигрывала. Флаг возвращает старое поведение.
"""

from __future__ import annotations

from src.core.indexing.file_guard import FileGuard, data_index_enabled


def _file(tmp_path, name: str) -> str:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"a": 1}' if name.endswith(".json") else "x = 1\n", encoding="utf-8"
    )
    return path


def test_json_is_not_indexed_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("MSCODEBASE_INDEX_DATA", raising=False)
    guard = FileGuard(tmp_path)
    assert guard.is_safe_to_index(_file(tmp_path, "config.json")) is False
    assert guard.is_safe_to_index(_file(tmp_path, "package.json")) is False


def test_json_returns_with_the_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("MSCODEBASE_INDEX_DATA", "1")
    guard = FileGuard(tmp_path)
    assert guard.is_safe_to_index(_file(tmp_path, "config.json")) is True


def test_code_is_indexed_either_way(tmp_path, monkeypatch):
    guard = FileGuard(tmp_path)
    for value in ("0", "1"):
        monkeypatch.setenv("MSCODEBASE_INDEX_DATA", value)
        assert guard.is_safe_to_index(_file(tmp_path, "mod.py")) is True
        assert guard.is_safe_to_index(_file(tmp_path, "app.js")) is True


def test_notebooks_are_code_not_data(tmp_path, monkeypatch):
    """`.ipynb` — тоже JSON, но индексируется всегда: это код внутри ячеек."""
    monkeypatch.delenv("MSCODEBASE_INDEX_DATA", raising=False)
    guard = FileGuard(tmp_path)
    assert guard.is_safe_to_index(_file(tmp_path, "notebook.ipynb")) is True


def test_flag_parsing(monkeypatch):
    for value, expected in (("1", True), ("true", True), ("on", True),
                            ("0", False), ("", False), ("нет", False)):
        monkeypatch.setenv("MSCODEBASE_INDEX_DATA", value)
        assert data_index_enabled() is expected, value
