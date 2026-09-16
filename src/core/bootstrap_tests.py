# -*- coding: utf-8 -*-
"""Bootstrap Step A2: построение TESTS-рёбер в PropertyGraph из trace_result.json.

Вход — результат dynamic trace pytest-плагина (experiments/bootstrap/dynamic_trace_plugin.py):
    {
      "tests/test_action_receipt.py::test_verdict_all_pass_is_verified":
          ["_is_inconclusive_result@core\\action_receipt.py", ...],
      ...
    }

Граф-индексатор помечает тестовые функции как Function (без label=TEST) и
покрывает лишь малую часть тестов, а TESTS-рёбер нет вообще (проверено на
живой БД: 160 test-узлов из 1727 тестов, 0 рёбер TESTS, функций матчится
95.9%). Этот модуль закрывает пробел: создаёт недостающие узлы тестов
(label=TEST) и линкует каждый тест с исполненными src-функциями ребром EdgeType.TESTS.

Соглашения (в рамках отдельно стоящего модуля, без импорта graph_adapter):
- qname теста: "{project_name}.{abs_posix_path}.{test_name}" — тот же формат,
  что создаёт индексатор (см. живой граф: D:.D:/Project/.../tests/...test_x).
- project_name: первый сегмент abs-пути без точки и отличный от "src"
  (для абсолютного пути на Windows это "D:" — совпадает с графом).
- name теста: часть nodeid после "::", без параметризации "[...]".
- src-функции из trace (соотношение "name@rel_path") матчатся по file_path
  + суффиксу имени (методы в графе записаны как "Class.method", а co_name
  из trace — голое имя метода).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Optional

from src.core.graph import EdgeType, NodeLabel, PropertyGraph

SRC_DIR_NAME = "src"


@dataclass
class TestsBootstrapStats:
    """Счётчики прогона построения TESTS-рёбер."""

    tests_total: int = 0
    tests_created: int = 0
    tests_reused: int = 0
    function_entries: int = 0
    functions_matched: int = 0
    functions_missing: int = 0
    edges_added: int = 0
    multi_matched_entries: int = 0
    missing: list = field(default_factory=list)

    def as_dict(self) -> Dict:
        return {
            "tests_total": self.tests_total,
            "tests_created": self.tests_created,
            "tests_reused": self.tests_reused,
            "function_entries": self.function_entries,
            "functions_matched": self.functions_matched,
            "functions_missing": self.functions_missing,
            "edges_added": self.edges_added,
            "multi_matched_entries": self.multi_matched_entries,
        }


def _normalize(rel: str) -> str:
    """Windows/posix-нормализация относительного пути trace."""
    return rel.replace("\\", "/")


def _project_name(abs_posix: str) -> str:
    """Имя проекта из абсолютного posix-пути (конвенция индексатора)."""
    for part in abs_posix.split("/"):
        if part and part != SRC_DIR_NAME and "." not in part:
            return part
    return "unknown"


def _split_nodeid(nodeid: str) -> tuple:
    """tests/foo.py::test_name[param] -> (rel_posix, name)."""
    path_part, _, name_part = nodeid.partition("::")
    name = name_part.split("[")[0]
    return _normalize(path_part), name


def _parse_entry(entry: str) -> Optional[tuple]:
    """ "name@core\\file.py" -> (name, rel_posix) или None (битый формат)."""
    name, sep, rel = entry.rpartition("@")
    if not sep or not rel or not name:
        return None
    return name, _normalize(rel)


def build_tests_edges(
    trace: Dict[str, Iterable[str]],
    project_root: Path,
    graph_db: PropertyGraph,
    src_dir: Optional[Path] = None,
) -> TestsBootstrapStats:
    """Построение TESTS-рёбер test -> исполненная src-функция.

    Args:
        trace: mapping nodeid -> iterable "name@rel_path" (как trace_result.json).
        project_root: корень проекта (для резолва путей тестов и src/).
        graph_db: целевой PropertyGraph (создание узлов и рёбер идемпотентно).
        src_dir: каталог исходников (default project_root/src).

    Returns:
        TestsBootstrapStats со счётчиками.
    """
    project_root = Path(project_root).resolve()
    src_root = (src_dir or project_root / SRC_DIR_NAME).resolve()
    stats = TestsBootstrapStats()
    stats.tests_total = len(trace)

    # ── Pre-вычисление Function-узлов по файлу (один проход вместо N запросов) ──
    functions_by_file: Dict[str, list] = {}
    for node in graph_db.find_nodes(label=NodeLabel.FUNCTION, limit=100000):
        functions_by_file.setdefault(node.file_path, []).append(node)

    for nodeid, entries in trace.items():
        rel_path, test_name = _split_nodeid(nodeid)
        abs_test = str((project_root / rel_path).as_posix())
        test_qname = f"{_project_name(abs_test)}.{abs_test}.{test_name}"

        # ── Test-узел: reuse, не перезаписывать label (Red Team: add_node с
        #    ON CONFLICT DO UPDATE перетрёт Function на TEST) ──
        existing = graph_db.get_node(test_qname)
        if existing is not None:
            stats.tests_reused += 1
        else:
            graph_db.add_node(
                name=test_name,
                label=NodeLabel.TEST,
                qualified_name=test_qname,
                file_path=abs_test,
            )
            stats.tests_created += 1

        # ── Связываем с исполненными функциями ──
        for entry in entries:
            parsed = _parse_entry(entry)
            if parsed is None:
                stats.functions_missing += 1
                continue
            func_name, rel_src = parsed
            abs_src = str((src_root / rel_src).as_posix())
            matched_nodes = functions_by_file.get(abs_src) or []
            # co_name метода голое ("_apply_move"), в графе "Class._apply_move"
            # -> суффикс-матч по имени; свободные функции подходят и точно.
            hits = [
                n for n in matched_nodes if n.name == func_name or n.name.endswith(f".{func_name}")
            ]
            stats.function_entries += 1
            if not hits:
                stats.functions_missing += 1
                stats.missing.append(entry)
                continue
            if len(hits) > 1:
                stats.multi_matched_entries += 1
            added = 0
            for node in hits:
                edge = graph_db.add_edge(
                    source_qname=test_qname,
                    target_qname=node.qualified_name,
                    type=EdgeType.TESTS,
                    weight=1.0,
                    properties={"trace": "dynamic_trace"},
                )
                if edge is not None:
                    added += 1
                    stats.edges_added += 1
            if added:
                stats.functions_matched += 1

    return stats


def build_from_trace_file(
    trace_path: Path,
    project_root: Path,
    graph_path: Optional[Path] = None,
) -> TestsBootstrapStats:
    """build_tests_edges с загрузкой trace_result.json и открытием графа.

    Args:
        trace_path: путь к trace_result.json.
        project_root: корень проекта.
        graph_path: путь к graph.db (default — get_graph_db_path(project_root)).
    """
    from src.core.artifact_paths import get_graph_db_path

    project_root = Path(project_root).resolve()
    trace = json.loads(Path(trace_path).read_text(encoding="utf-8"))
    graph_db = PropertyGraph(graph_path or get_graph_db_path(project_root))
    return build_tests_edges(trace, project_root, graph_db)
