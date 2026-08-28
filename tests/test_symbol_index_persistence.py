"""Guard for SymbolIndex JSON persistence (2026-08-26 incident).

Covers two corruption triggers found in index_guard.save_symbol_index:
1. graph-backed SymbolIndexAdapter (no _definitions/_references/_file_to_symbols
   maps) must NOT write empty JSON over a populated file — graph.db is its
   persistence.
2. An empty plain SymbolIndex must NOT overwrite a non-empty file on disk.
"""
import json

import pytest

from src.core.graph import PropertyGraph
from src.core.indexing.index_guard import IndexGuard
from src.core.indexing.symbol_index import SymbolIndex
from src.core.search.graph_adapter import SymbolIndexAdapter


class _FakeSymbolRef:
    def __init__(self, symbol: str, file: str, line: int = 1, kind: str = "def", is_def: bool = True):
        self.symbol = symbol
        self.file = file
        self.line = line
        self.kind = kind
        self.is_def = is_def

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "file": self.file,
            "line": self.line,
            "kind": self.kind,
            "is_def": self.is_def,
        }


@pytest.fixture()
def guard(tmp_path):
    return IndexGuard(db_path=tmp_path, project_path=tmp_path)


def _make_symbol_index() -> SymbolIndex:
    si = SymbolIndex()
    si._definitions["UserAuthService"] = [
        _FakeSymbolRef("UserAuthService", "src/auth/service.py")
    ]
    si._references["login"] = [
        _FakeSymbolRef("login", "src/api/v1/auth_router.py", is_def=False)
    ]
    si._file_to_symbols["src/auth/service.py"] = {"UserAuthService"}
    return si


def test_save_populated_and_load_roundtrip(guard):
    si = _make_symbol_index()
    assert guard.save_symbol_index(si) is True
    cache = guard.db_path / "symbol_index.json"
    assert cache.exists()
    raw = json.loads(cache.read_text(encoding="utf-8"))
    assert raw["definitions"]["UserAuthService"][0]["file"] == "src/auth/service.py"

    loaded = SymbolIndex()
    assert guard.load_symbol_index(loaded) is True
    assert loaded.get_symbol_count() == 1


def test_empty_instance_does_not_overwrite_populated_file(guard):
    si = _make_symbol_index()
    assert guard.save_symbol_index(si) is True
    cache = guard.db_path / "symbol_index.json"
    before = cache.read_text(encoding="utf-8")

    empty = SymbolIndex()  # пустые все три карты
    assert guard.save_symbol_index(empty) is True  # не упал
    assert cache.read_text(encoding="utf-8") == before  # файл НЕ перезаписан


def test_adapter_does_not_write_empty_json(guard, tmp_path):
    si = _make_symbol_index()
    assert guard.save_symbol_index(si) is True
    cache = guard.db_path / "symbol_index.json"
    before = cache.read_text(encoding="utf-8")

    # graph-backed adapter: не имеет _definitions/_references -> обязан пропустить запись
    pg = PropertyGraph(tmp_path / "graph.db")
    adapter = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)
    assert guard.save_symbol_index(adapter) is True
    assert cache.read_text(encoding="utf-8") == before  # файл не тронут


def test_empty_file_can_be_created_for_fresh_project(guard):
    empty = SymbolIndex()
    assert guard.save_symbol_index(empty) is True
    cache = guard.db_path / "symbol_index.json"
    assert cache.exists()
    raw = json.loads(cache.read_text(encoding="utf-8"))
    assert raw["definitions"] == {}  # свежий проект без данных — пустой файл легитимен
