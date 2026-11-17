"""Данные (.json) не индексируются по умолчанию — MSCODEBASE_INDEX_DATA.

Замер 2026-11-17: .json — 62.3% индекса engraphis (31 123 из 49 920 чанков),
90% объёма — замороженные артефакты бенчмарка. Исключение — то, что нужно
агенту: манифесты (как проект подключается) и контракты инструментов.
"""

from __future__ import annotations

from src.core.indexing.file_guard import FileGuard, data_index_enabled, is_agent_json


def _json(tmp_path, name: str, body: str = '{"a": 1}') -> str:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_dataset_json_is_not_indexed_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("MSCODEBASE_INDEX_DATA", raising=False)
    guard = FileGuard(tmp_path)
    dataset = _json(
        tmp_path, "eval/datasets/runtime.json",
        '{"scenarios": [{"task": "x"}]}',
    )
    evidence = _json(
        tmp_path, "docs/benchmark-evidence/run.json",
        '{"command": "pytest", "result": {"passed": 3}, "source_sha256": "ab"}',
    )
    assert guard.is_safe_to_index(dataset) is False
    assert guard.is_safe_to_index(evidence) is False


def test_manifests_are_indexed(tmp_path, monkeypatch):
    monkeypatch.delenv("MSCODEBASE_INDEX_DATA", raising=False)
    guard = FileGuard(tmp_path)
    assert guard.is_safe_to_index(
        _json(tmp_path, "package.json", '{"name": "app", "dependencies": {}}')
    ) is True
    assert guard.is_safe_to_index(
        _json(tmp_path, "plugins/my.plugin.json", '{"name": "p"}')
    ) is True
    assert guard.is_safe_to_index(
        _json(tmp_path, ".claude-plugin/plugin.json", '{"name": "p"}')
    ) is True


def test_tool_contract_is_indexed_by_its_keys(tmp_path, monkeypatch):
    monkeypatch.delenv("MSCODEBASE_INDEX_DATA", raising=False)
    guard = FileGuard(tmp_path)
    contract = _json(
        tmp_path, "docs/MCP_CONTRACT.json",
        '{"schema": "x/v1", "surfaces": {"classic": [{"inputSchema": {}}]}}',
    )
    assert guard.is_safe_to_index(contract) is True
    assert is_agent_json(contract) is True


def test_flag_indexes_everything(tmp_path, monkeypatch):
    monkeypatch.setenv("MSCODEBASE_INDEX_DATA", "1")
    guard = FileGuard(tmp_path)
    dataset = _json(tmp_path, "eval/datasets/runtime.json", '{"a": 1}')
    assert guard.is_safe_to_index(dataset) is True


def test_oversized_contract_is_not_sniffed(tmp_path, monkeypatch):
    monkeypatch.delenv("MSCODEBASE_INDEX_DATA", raising=False)
    guard = FileGuard(tmp_path)
    big = '{"surfaces": "' + "x" * (600 * 1024) + '"}'
    path = _json(tmp_path, "huge_contract.json", big)
    assert is_agent_json(path) is False
    assert guard.is_safe_to_index(path) is False


def test_code_is_indexed_either_way(tmp_path, monkeypatch):
    guard = FileGuard(tmp_path)
    for value in ("0", "1"):
        monkeypatch.setenv("MSCODEBASE_INDEX_DATA", value)
        py = tmp_path / "mod.py"
        py.write_text("x = 1\n", encoding="utf-8")
        assert guard.is_safe_to_index(py) is True


def test_notebooks_are_code_not_data(tmp_path, monkeypatch):
    """`.ipynb` — тоже JSON, но индексируется всегда: это код внутри ячеек."""
    monkeypatch.delenv("MSCODEBASE_INDEX_DATA", raising=False)
    guard = FileGuard(tmp_path)
    nb = tmp_path / "notebook.ipynb"
    nb.write_text('{"cells": []}', encoding="utf-8")
    assert guard.is_safe_to_index(nb) is True


def test_flag_parsing(monkeypatch):
    for value, expected in (("1", True), ("true", True), ("on", True),
                            ("0", False), ("", False), ("нет", False)):
        monkeypatch.setenv("MSCODEBASE_INDEX_DATA", value)
        assert data_index_enabled() is expected, value
