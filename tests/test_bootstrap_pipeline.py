# -*- coding: utf-8 -*-
"""Tests для Bootstrap Pipeline Step 3: detect_entities + trace + TESTS-рёбра.

Интеграционные: реальный pytest subprocess (плагин bootstrap_trace_plugin),
реальный PropertyGraph в tmp каталоге. Мок не используется — это правило
live-smoke для runtime-изменений (сервер/индекс/провайдер).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.bootstrap_pipeline import run_bootstrap_pipeline


def _make_project(root: Path) -> None:
    """Мини-проект src-layout: сущности + 2 теста, вызывающие src-функцию."""
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir(parents=True)
    (root / "src" / "mathz.py").write_text(
        "from dataclasses import dataclass\n"
        "\n"
        "@dataclass\n"
        "class Point:\n"
        "    x: int\n"
        "    y: int\n"
        "\n"
        "def add(a: int, b: int) -> int:\n"
        "    return a + b\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_mathz.py").write_text(
        "import sys, pathlib\n"
        "sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src'))\n"
        "from mathz import add\n"
        "\n"
        "def test_add_positive():\n"
        "    assert add(1, 2) == 3\n"
        "\n"
        "def test_add_zero():\n"
        "    assert add(0, 0) == 0\n",
        encoding="utf-8",
    )


def test_full_pipeline_creates_tests_edges(tmp_path):
    root = tmp_path / "proj"
    _make_project(root)
    graph_path = tmp_path / "g.db"

    stats = run_bootstrap_pipeline(root, graph_path=graph_path, trace_timeout=120)

    # B1: сущности найдены авто-детектом (нет src/ в явном виде — src/ определён автоматически)
    assert stats.src_root is not None
    assert Path(stats.src_root).name == "src"
    assert stats.entities.dataclass_count == 1
    assert stats.entities.entities[0].name == "Point"

    # Шаг 3: реальный прогон pytest с трассой — 2 теста, оба линкуются
    assert stats.tests_total == 2
    assert stats.tests_linked == 2
    assert stats.linked_pct == 100.0
    assert stats.unique_src_functions >= 1
    assert stats.pytest_exit_code == 0

    # A2: TESTS-рёбра записаны в PropertyGraph
    assert stats.graph.tests_created == 2
    assert stats.graph.edges_added >= 2  # add + dataclass-методы/typedef


def test_no_src_root_returns_empty(tmp_path):
    name_only = tmp_path / "empty"
    name_only.mkdir()

    stats = run_bootstrap_pipeline(name_only, graph_path=tmp_path / "g.db")

    assert stats.src_root is None
    assert stats.entities.files_scanned == 0
    assert stats.pytest_exit_code is None  # trace не запускался


def test_explicit_src_dir_wins(tmp_path):
    root = tmp_path / "proj"
    (root / "custom").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "custom" / "mod.py").write_text(
        "def f():\n    return 1\n", encoding="utf-8"
    )
    (root / "tests" / "test_mod.py").write_text(
        "from custom.mod import f\n"
        "def test_f():\n    assert f() == 1\n",
        encoding="utf-8",
    )

    stats = run_bootstrap_pipeline(
        root, src_dir=root / "custom", graph_path=tmp_path / "g.db", trace_timeout=120
    )

    assert Path(stats.src_root).name == "custom"
    assert stats.entities.files_scanned == 1


def test_exit_code_nonzero_still_yields_trace(tmp_path):
    """Упавшие тесты → exit=1, но trace пишется (pytest_sessionfinish)."""
    root = tmp_path / "proj"
    _make_project(root)
    (root / "tests" / "test_mathz.py").write_text(
        "import sys, pathlib\n"
        "sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src'))\n"
        "from mathz import add\n"
        "def test_fail():\n    assert add(1, 2) == 4\n",
        encoding="utf-8",
    )

    stats = run_bootstrap_pipeline(root, graph_path=tmp_path / "g.db", trace_timeout=120)

    assert stats.pytest_exit_code == 1
    assert stats.tests_total == 1
    assert stats.tests_linked == 1  # трасса написана несмотря на падение


def test_no_pytest_raises_clear_error(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    _make_project(root)
    monkeypatch.setenv(
        "MSCODEBASE_BOOTSTRAP_PYTHON", str(tmp_path / "nonexistent_python.exe")
    )

    with pytest.raises(RuntimeError, match="interpreter not found"):
        run_bootstrap_pipeline(root, graph_path=tmp_path / "g.db")
