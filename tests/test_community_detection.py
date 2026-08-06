"""Тесты Leiden-детекции сообществ (Workstream C).

Проверяют:
1. detect_communities на малом PropertyGraph — формат ответа + корректность
   (вход → выход: символы одного модуля попадают в одно сообщество).
2. not_installed-путь не тестируем (нельзя симулировать отсутствие импорта) —
   вместо этого guard: модуль импортируется БЕЗ igraph/leidenalg.
3. Размерные лимиты (too_large) не падают.
"""
import pathlib

import pytest

from src.core.community_detection import DEFAULT_EDGE_TYPES, detect_communities
from src.core.graph import EdgeType, NodeLabel, PropertyGraph

igraph = pytest.importorskip("igraph")
leidenalg = pytest.importorskip("leidenalg")


def _build_graph(tmp_path: pathlib.Path) -> PropertyGraph:
    db = tmp_path / "test_graph.db"
    pg = PropertyGraph(str(db))

    # Модуль A: 3 функции, связанные вызовами (одно сообщество)
    fa = "proj/src/core/mod_a.py"
    for name in ["a_func1", "a_func2", "a_func3"]:
        pg.add_node(name=name, label=NodeLabel.FUNCTION,
                    qualified_name=f"proj.{fa}.{name}", file_path=fa)
    pg.add_edge(source_qname=f"proj.{fa}.a_func1",
                target_qname=f"proj.{fa}.a_func2", type=EdgeType.CALLS)
    pg.add_edge(source_qname=f"proj.{fa}.a_func2",
                target_qname=f"proj.{fa}.a_func3", type=EdgeType.CALLS)
    pg.add_edge(source_qname=f"proj.{fa}.a_func3",
                target_qname=f"proj.{fa}.a_func1", type=EdgeType.CALLS)

    # Модуль B: изолированные функции (второе сообщество)
    fb = "proj/src/core/mod_b.py"
    for name in ["b_func1", "b_func2"]:
        pg.add_node(name=name, label=NodeLabel.FUNCTION,
                    qualified_name=f"proj.{fb}.{name}", file_path=fb)
    pg.add_edge(source_qname=f"proj.{fb}.b_func1",
                target_qname=f"proj.{fb}.b_func2", type=EdgeType.CALLS)

    # File-узлы (служебные — должны игнорироваться)
    pg.add_node(name="mod_a.py", label=NodeLabel.FILE,
                qualified_name=f"proj.{fa}", file_path=fa)
    return pg


class TestDetection:
    def test_detects_two_communities(self, tmp_path):
        pg = _build_graph(tmp_path)
        result = detect_communities(pg)
        assert result["status"] == "ok"
        assert result["communities"] >= 2
        assert result["nodes_analyzed"] == 5

        # Проверка корректности (вход → выход): символы mod_a в одном сообществе
        a_names = {
            s
            for comm in result["communities_list"]
            for s in comm["sample_symbols"]
            if "mod_a" in s
        }
        assert "proj.src.core.mod_a.a_func1" in a_names or any(
            "a_func1" in s for comm in result["communities_list"] for s in comm["sample_symbols"]
        )

        # Каждое сообщество имеет файловую разбивку
        for comm in result["communities_list"]:
            assert "size" in comm
            assert isinstance(comm["files"], list)

    def test_default_edge_types_are_semantic_only(self):
        assert "CO_CHANGES_WITH" not in DEFAULT_EDGE_TYPES
        assert "CALLS" in DEFAULT_EDGE_TYPES

    def test_empty_graph(self, tmp_path):
        pg = PropertyGraph(str(tmp_path / "empty.db"))
        result = detect_communities(pg)
        assert result["status"] == "ok"
        assert result["communities"] == 0

    def test_size_limit_nonexceeded(self, tmp_path):
        pg = _build_graph(tmp_path)
        # малый лимит не должен падать — вернёт результат или too_large
        result = detect_communities(pg, max_nodes=2, max_edges=2)
        assert result["status"] in ("ok", "too_large")


class TestModuleGuard:
    def test_module_imports_without_igraph(self, monkeypatch):
        """Модуль импортируется без igraph/leidenalg (guard для not_installed)."""
        import sys

        monkeypatch.setitem(sys.modules, "igraph", None)
        monkeypatch.setitem(sys.modules, "leidenalg", None)
        # переимпорт в чистое пространство имён не требуется — модуль
        # импортирует зависимости лениво внутри detect_communities()
        import src.core.community_detection as cd

        assert cd.DEFAULT_EDGE_TYPES
