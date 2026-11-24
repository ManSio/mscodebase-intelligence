"""NOOP-дедуп и ссылки память→символ."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

import src.core.intelligence.links as links_mod
from src.core.intelligence.layer import (
    ProjectIntelligenceLayer,
    _find_noop,
    _same_fact,
)
from src.core.intelligence.links import MAX_LINKS, extract_symbol_links


def test_same_fact_ignores_volatile_fields():
    base = {"title": "FileGuard skip", "status": "open"}
    left = {**base, "anchors": [{"kind": "file", "value": "a.py"}], "symbols": [{"name": "X"}]}
    right = {**base, "anchors": [{"kind": "file", "value": "b.py"}], "symbols": []}

    assert _same_fact(left, right) is True


def test_same_fact_detects_real_change():
    assert _same_fact({"title": "a"}, {"title": "b"}) is False
    assert _same_fact({"title": "a", "n": 1}, {"title": "a", "n": 2}) is False


def test_same_fact_handles_non_serializable():
    class Weird:
        pass

    assert _same_fact({"x": Weird()}, {"x": Weird()}) is False


def test_links_require_a_declaration(tmp_path: Path, monkeypatch):
    src = tmp_path / "mod.py"
    src.write_text("class FileGuard:\n    pass\n", encoding="utf-8")
    fake = {
        "FileGuard": {"name": "FileGuard", "file": str(src), "kind": "Class"},
        "NotDeclared": {"name": "NotDeclared", "file": str(src), "kind": "Class"},
    }
    monkeypatch.setattr(links_mod, "_graph_symbols", lambda _root: fake)

    data = {"detail": "FileGuard guards dirs; NotDeclared is only mentioned"}
    found = extract_symbol_links(data, tmp_path)

    assert [item["name"] for item in found] == ["FileGuard"]


def test_links_respect_the_cap(monkeypatch, tmp_path: Path):
    files = []
    for i in range(MAX_LINKS + 3):
        p = tmp_path / f"m{i}.py"
        p.write_text(f"def symbol_name_{i}():\n    pass\n", encoding="utf-8")
        files.append(p)
    fake = {
        f"symbol_name_{i}": {"name": f"symbol_name_{i}", "file": str(p), "kind": "Function"}
        for i, p in enumerate(files)
    }
    monkeypatch.setattr(links_mod, "_graph_symbols", lambda _root: fake)

    data = {"x": " ".join(f"symbol_name_{i}" for i in range(len(files)))}
    found = extract_symbol_links(data, tmp_path)

    assert len(found) == MAX_LINKS


def test_links_without_graph_are_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(links_mod, "_graph_symbols", lambda _root: {})
    assert extract_symbol_links({"x": "FileGuard"}, tmp_path) == []


def test_missing_graph_db_does_not_open_sqlite(tmp_path: Path, monkeypatch):
    """Нет файла — не открываем соединение (а не «открыли и поймали ошибку»)."""
    monkeypatch.setenv("MSCODEBASE_DATA_DIR", str(tmp_path / "data_root"))
    root = tmp_path / "proj"
    root.mkdir()

    calls: list = []

    def _spy(*args, **kwargs):
        calls.append(args)
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(links_mod.sqlite3, "connect", _spy)
    assert extract_symbol_links({"x": "Anything"}, root) == []
    assert calls == [], "sqlite3.connect вызван при отсутствующем graph.db"


def test_relative_path_in_graph_is_resolved_against_the_project(tmp_path: Path, monkeypatch):
    """Относительный file_path в graph.db — от корня проекта, не от cwd сервера."""
    monkeypatch.setenv("MSCODEBASE_DATA_DIR", str(tmp_path / "data_root"))
    root = tmp_path / "proj"
    root.mkdir()
    (root / "mod.py").write_text("class RelativeSymbol:\n    pass\n", encoding="utf-8")
    _write_graph(root, [("RelativeSymbol", "Class", "mod.py")])

    found = extract_symbol_links({"x": "RelativeSymbol"}, root)
    assert [item["name"] for item in found] == ["RelativeSymbol"]


def test_noop_keeps_links_computed_on_the_second_write(tmp_path: Path, monkeypatch):
    """Повторная запись дополняет узел ссылками, а не выбрасывает их."""
    from src.core.intelligence.layer import ProjectIntelligenceLayer

    monkeypatch.setenv("MSCODEBASE_DATA_DIR", str(tmp_path / "data_root"))
    root = tmp_path / "project"
    root.mkdir()
    layer = ProjectIntelligenceLayer(root, None, None, None)  # type: ignore[arg-type]
    payload = json.dumps({"title": "факт про FileGuard"})

    monkeypatch.setattr(links_mod, "extract_symbol_links", lambda _data, _root: [])
    asyncio.run(layer.intel_add_memory_node("tech_debt", payload))

    link = {"name": "FileGuard", "file": str(root / "mod.py"), "kind": "Class"}
    monkeypatch.setattr(links_mod, "extract_symbol_links", lambda _data, _root: [link])
    asyncio.run(layer.intel_add_memory_node("tech_debt", payload))

    nodes = layer.store._load_json("project_memory.json")
    assert len(nodes) == 1
    assert nodes[0]["data"]["symbols"] == [link]


def test_find_noop_returns_the_existing_node():
    nodes = [
        {"node_id": "NODE-1", "section": "adrs", "status": "ACTIVE",
         "data": {"title": "x", "anchors": [1]}},
    ]
    found = _find_noop(nodes, "adrs", {"title": "x", "symbols": [2]})
    assert found is not None and found["node_id"] == "NODE-1"


def test_find_noop_ignores_other_section_or_status():
    nodes = [
        {"node_id": "A", "section": "adrs", "status": "ACTIVE", "data": {"t": 1}},
        {"node_id": "B", "section": "tech_debt", "status": "ACTIVE", "data": {"t": 1}},
        {"node_id": "C", "section": "adrs", "status": "REFUTED", "data": {"t": 1}},
    ]
    assert _find_noop(nodes, "adrs", {"t": 1})["node_id"] == "A"
    assert _find_noop(nodes, "known_issues", {"t": 1}) is None
    assert _find_noop(nodes, "adrs", {"t": 2}) is None


def test_find_noop_tolerates_garbage_nodes():
    assert _find_noop([None, 42, "x"], "adrs", {"t": 1}) is None


# ── wiring: решения проверяются через настоящий write-path ─────────────────

@pytest.fixture()
def project(tmp_path: Path, monkeypatch) -> Path:
    """Изолирует data_root: иначе тест пишет в память реального проекта."""
    monkeypatch.setenv("MSCODEBASE_DATA_DIR", str(tmp_path / "data_root"))
    root = tmp_path / "project"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _layer(project: Path) -> ProjectIntelligenceLayer:
    return ProjectIntelligenceLayer(project, None, None, None)  # type: ignore[arg-type]


def _add(layer, payload: dict, status: str = "ACTIVE") -> str:
    return asyncio.run(
        layer.intel_add_memory_node("tech_debt", json.dumps(payload, ensure_ascii=False), status)
    )


def _nodes(layer) -> list:
    return layer.store._load_json("project_memory.json") or []


def test_repeated_fact_is_a_noop_and_writes_one_node(project: Path):
    """Без этого теста ``op: noop`` можно отключить — набор остаётся зелёным.

    Ревью 2026-11-17: wiring (layer.py:1492-1507) не был покрыт ни одним тестом.
    """
    layer = _layer(project)
    first = _add(layer, {"title": "дубль", "detail": "одинаковый текст"})
    second = _add(layer, {"title": "дубль", "detail": "одинаковый текст"})

    assert "добавлена" in first
    assert "op: noop" in second
    assert len(_nodes(layer)) == 1
    node_id = first.split("Запись ")[1].split(" ")[0]
    assert node_id in second


def test_noop_promotes_active_to_verified(project: Path):
    layer = _layer(project)
    _add(layer, {"title": "факт"})
    promoted = _add(layer, {"title": "факт"}, status="VERIFIED")

    assert "VERIFIED" in promoted
    nodes = _nodes(layer)
    assert len(nodes) == 1
    assert nodes[0]["status"] == "VERIFIED"


def test_links_are_written_into_the_node(project: Path):
    """Ссылки память→символ доходят до узла, а не только до функции."""
    (project / "guard.py").write_text(
        "class FileGuard:\n    pass\n", encoding="utf-8"
    )
    from src.core.artifact_paths import get_graph_db_path

    db = Path(str(get_graph_db_path(project)))
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db))
    try:
        con.execute(
            "create table if not exists nodes (name text, label text, file_path text)"
        )
        con.execute(
            "insert into nodes values (?, ?, ?)",
            ("FileGuard", "Class", str(project / "guard.py")),
        )
        con.commit()
    finally:
        con.close()

    layer = _layer(project)
    _add(layer, {"title": "FileGuard не пропускает каталоги"})

    node = _nodes(layer)[0]
    symbols = node["data"].get("symbols") or []
    assert [item["name"] for item in symbols] == ["FileGuard"]


# ── границы links (ревью: substring-контейнмент и docstring) ───────────────

def _write_graph(root: Path, rows) -> None:
    """Граф проекта в изолированном data-root: настоящий sqlite-путь links.py."""
    from src.core.artifact_paths import get_graph_db_path

    db = Path(str(get_graph_db_path(root)))
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db))
    try:
        con.execute(
            "create table if not exists nodes (name text, label text, file_path text)"
        )
        con.executemany("insert into nodes values (?, ?, ?)", rows)
        con.commit()
    finally:
        con.close()


def test_symbol_outside_the_project_is_rejected(tmp_path: Path, monkeypatch):
    """Соседний каталог с тем же префиксом — не «внутри проекта»."""
    monkeypatch.setenv("MSCODEBASE_DATA_DIR", str(tmp_path / "data_root"))
    root = tmp_path / "proj"
    sibling = tmp_path / "projx"
    root.mkdir()
    sibling.mkdir()
    outside = sibling / "mod.py"
    outside.write_text("class OutsideSymbol:\n    pass\n", encoding="utf-8")

    _write_graph(root, [("OutsideSymbol", "Class", str(outside))])

    assert extract_symbol_links({"x": "OutsideSymbol"}, root) == []


def test_corrupt_graph_db_yields_no_links(tmp_path: Path, monkeypatch):
    """Битый файл графа — пустые ссылки, а не исключение."""
    monkeypatch.setenv("MSCODEBASE_DATA_DIR", str(tmp_path / "data_root"))
    root = tmp_path / "proj"
    root.mkdir()
    from src.core.artifact_paths import get_graph_db_path

    db = Path(str(get_graph_db_path(root)))
    db.parent.mkdir(parents=True, exist_ok=True)
    db.write_bytes(b"not a sqlite database at all" * 10)

    assert extract_symbol_links({"x": "Anything"}, root) == []


def test_docstring_is_not_a_declaration(tmp_path: Path, monkeypatch):
    src = tmp_path / "mod.py"
    src.write_text(
        'TEXT = """\nclass DocstringSymbol:\n    pass\n"""\n', encoding="utf-8"
    )
    monkeypatch.setattr(
        links_mod, "_graph_symbols", lambda _root: {
            "DocstringSymbol": {"name": "DocstringSymbol", "file": str(src), "kind": "Class"}
        }
    )

    assert extract_symbol_links({"x": "DocstringSymbol"}, tmp_path) == []


def test_real_declaration_still_passes_with_ast(tmp_path: Path, monkeypatch):
    src = tmp_path / "mod.py"
    src.write_text(
        "class FirstSymbol:\n    pass\n\n\nclass WantedSymbol:\n    def method(self):\n        pass\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        links_mod, "_graph_symbols", lambda _root: {
            "WantedSymbol": {"name": "WantedSymbol", "file": str(src), "kind": "Class"}
        }
    )

    found = extract_symbol_links({"x": "WantedSymbol"}, tmp_path)
    assert [item["name"] for item in found] == ["WantedSymbol"]


def test_parallel_identical_writes_create_one_node(project: Path):
    """NOOP под локом: 8 одновременных записей одного факта дают 1 узел."""
    import threading

    layer = _layer(project)
    payload = json.dumps({"title": "одновременный факт"})
    errors: list[str] = []

    def writer() -> None:
        try:
            asyncio.run(layer.intel_add_memory_node("tech_debt", payload))
        except Exception as exc:  # noqa: BLE001 — тест должен показать ошибку
            errors.append(repr(exc))

    threads = [threading.Thread(target=writer) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, errors
    assert len(_nodes(layer)) == 1
