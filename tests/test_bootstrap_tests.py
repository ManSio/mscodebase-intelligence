# -*- coding: utf-8 -*-
"""Tests для bootstrap_tests.build_tests_edges (TESTS-рёбра из trace_result.json)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.core.bootstrap_tests import _project_name, build_tests_edges
from src.core.graph import EdgeType, NodeLabel, PropertyGraph


def _project(path: str) -> str:
    return _project_name(path.replace("\\", "/"))


def _seed_src_functions(pg: PropertyGraph, project_root: str, funcs):
    """Создаёт Function-узлы как их создаёт индексатор (qname = proj.abs_path.name)."""
    for file_rel, name in funcs:
        abs_path = str((Path(project_root) / "src" / file_rel).resolve()).replace("\\", "/")
        pg.add_node(
            name=name,
            label=NodeLabel.FUNCTION,
            qualified_name=f"{_project(str(project_root))}.{abs_path}.{name}",
            file_path=abs_path,
        )


def _seed_existing_test(pg: PropertyGraph, project_root: str, nodeid: str):
    """Создаёт тестовый Function-узел как это делает индексатор (label=Function)."""
    path_part, _, name = nodeid.partition("::")
    name = name.split("[")[0]
    abs_path = str(Path(project_root) / path_part.replace("\\", "/")).replace("\\", "/")
    pg.add_node(
        name=name,
        label=NodeLabel.FUNCTION,
        qualified_name=f"{_project(str(project_root))}.{abs_path}.{name}",
        file_path=abs_path,
    )


@pytest.fixture
def graph(tmp_path):
    return PropertyGraph(tmp_path / "g.db")


TRACE = {
    "tests/test_action_receipt.py::test_verdict_all_pass_is_verified": [
        "_is_inconclusive_result@core\\action_receipt.py",
        "verdict_from_results@core\\action_receipt.py",
    ],
    "tests/test_action_receipt.py::test_verdict_fail_is_refuted": [
        "_is_inconclusive_result@core\\action_receipt.py",
    ],
}


def test_creates_missing_test_nodes_and_tests_edges(graph, tmp_path):
    root = tmp_path / "proj"
    _seed_src_functions(
        graph,
        str(root),
        [
            ("core/action_receipt.py", "_is_inconclusive_result"),
            ("core/action_receipt.py", "verdict_from_results"),
        ],
    )
    stats = build_tests_edges(TRACE, root, graph)

    assert stats.tests_total == 2
    assert stats.tests_created == 2
    assert stats.tests_reused == 0
    assert stats.function_entries == 3
    assert stats.functions_matched == 3
    assert stats.functions_missing == 0
    assert stats.edges_added == 3

    # Тестовые узлы помечены NodeLabel.TEST
    for nodeid, _ in TRACE.items():
        path_part, _, name = nodeid.partition("::")
        abs_path = str((Path(root) / path_part).resolve()).replace("\\", "/")
        proj = _project(str(root))
        node = graph.get_node(f"{proj}.{abs_path}.{name}")
        assert node is not None
        assert node.label == NodeLabel.TEST

    assert graph.count_edges(EdgeType.TESTS) == 3


def test_reuses_existing_function_test_node_without_overwriting_label(graph, tmp_path):
    root = tmp_path / "proj"
    _seed_src_functions(
        graph,
        str(root),
        [("core/action_receipt.py", "_is_inconclusive_result")],
    )
    # Индексатор уже создал тест как Function (случай 160 живых узлов)
    _seed_existing_test(graph, str(root), "tests/test_action_receipt.py::test_existing")

    stats = build_tests_edges(
        {
            "tests/test_action_receipt.py::test_existing": [
                "_is_inconclusive_result@core\\action_receipt.py"
            ]
        },
        root,
        graph,
    )

    assert stats.tests_created == 0
    assert stats.tests_reused == 1
    # Лейбл не перетёрт на TEST
    path_part, _, name = "tests/test_action_receipt.py::test_existing".partition("::")
    proj = _project(str(root))
    test_abs = str((Path(root) / path_part).resolve()).replace("\\", "/")
    node = graph.get_node(f"{proj}.{test_abs}.{name}")
    assert node is not None
    assert node.label == NodeLabel.FUNCTION
    assert graph.count_edges(EdgeType.TESTS) == 1


def test_idempotent_second_run(graph, tmp_path):
    root = tmp_path / "proj"
    _seed_src_functions(graph, str(root), [("core/action_receipt.py", "_is_inconclusive_result")])

    first = build_tests_edges(TRACE, root, graph)
    second = build_tests_edges(TRACE, root, graph)

    assert second.tests_created == 0
    assert second.tests_reused == 2
    # add_edge UPSERT по (source,target,type) — дублей рёбер нет
    assert first.edges_added == 2  # один test-узел × одна src-функция (verdict отсутствует в сиде)
    assert second.edges_added == 2  # UPSERT повторён, но дублей в БД нет
    assert graph.count_edges(EdgeType.TESTS) == 2  # идемпотентность: count не растёт


def test_parametrized_nodeid_no_extra_nodes(graph, tmp_path):
    root = tmp_path / "proj"
    _seed_src_functions(graph, str(root), [("core/math_utils.py", "add")])

    stats = build_tests_edges(
        {
            "tests/test_math.py::test_add[1+1=2]": ["add@core/math_utils.py"],
            "tests/test_math.py::test_add[2+2=4]": ["add@core/math_utils.py"],
        },
        root,
        graph,
    )

    # Оба параметра указали на один узел test_add (имя без [param])
    assert stats.tests_created == 1
    assert stats.tests_reused == 1
    assert graph.count_edges(EdgeType.TESTS) == 1  # узел test_add — одна функция add


def test_missing_function_entries_skipped_gracefully(graph, tmp_path):
    root = tmp_path / "proj"
    stats = build_tests_edges(
        {"tests/test_x.py::test_no_src": ["<lambda>@core\\builtin_no.py"]},
        root,
        graph,
    )

    assert stats.tests_created == 1
    assert stats.function_entries == 1
    assert stats.functions_missing == 1
    assert stats.edges_added == 0
    assert graph.count_edges(EdgeType.TESTS) == 0


def test_method_suffix_matching(graph, tmp_path):
    """Метод в trace голым co_name, в графе — Class.method."""
    root = tmp_path / "proj"
    _seed_src_functions(
        graph,
        str(root),
        [
            ("mcp/tools/write_tools.py", "WriteTool._apply_move"),
            ("mcp/tools/write_tools.py", "WriteTool._apply_delete"),
        ],
    )

    stats = build_tests_edges(
        {"tests/test_write_tools.py::test_move": ["_apply_move@mcp\\tools\\write_tools.py"]},
        root,
        graph,
    )

    assert stats.functions_matched == 1
    assert stats.edges_added == 1
    assert graph.count_edges(EdgeType.TESTS) == 1


def test_index_src_functions_creates_class_method_function_nodes(graph, tmp_path):
    """Статический индексатор: ФУНКЦИЯ, МЕТОД Class.method, КЛАСС."""
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "mod.py").write_text(
        "def free(a):\n    return a\n\n"
        "class Service:\n"
        "    def handle(self):\n        return 1\n",
        encoding="utf-8",
    )

    from src.core.bootstrap_tests import index_src_functions

    created = index_src_functions(root / "src", graph)

    assert created >= 3
    abs_posix = (root / "src" / "mod.py").as_posix()
    suff = f"{_project_name(abs_posix)}.{abs_posix}"
    free = graph.get_node(f"{suff}.free")
    assert free is not None and free.label == NodeLabel.FUNCTION
    svc = graph.get_node(f"{suff}.Service")
    assert svc is not None and svc.label == NodeLabel.CLASS
    meth = graph.get_node(f"{suff}.Service.handle")
    assert meth is not None and meth.label == NodeLabel.METHOD


def test_index_src_functions_skips_methods_as_functions(graph, tmp_path):
    """Метод не должен дублироваться как FUNCTION верхнего уровня."""
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "mod.py").write_text(
        "class Service:\n    def handle(self):\n        return 1\n",
        encoding="utf-8",
    )

    from src.core.bootstrap_tests import index_src_functions

    index_src_functions(root / "src", graph)
    abs_posix = (root / "src" / "mod.py").as_posix()
    suff = f"{_project_name(abs_posix)}.{abs_posix}"
    assert graph.get_node(f"{suff}.handle") is None
    assert graph.get_node(f"{suff}.Service.handle") is not None


def test_index_src_functions_reads_bom_files(graph, tmp_path):
    """Файлы с BOM (\ufeff) читаются: utf-8-sig, а не падает ast.parse."""
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "mod.py").write_bytes(b"\xef\xbb\xbfdef bomed():\n    return 1\n")

    from src.core.bootstrap_tests import index_src_functions

    created = index_src_functions(root / "src", graph)
    assert created == 1
