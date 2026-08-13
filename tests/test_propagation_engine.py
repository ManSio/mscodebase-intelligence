"""ADR-0004 Propagation Engine: каскадная ретракция зависимых узлов памяти.

Покрывает:
- прямые зависимые (data.depends_on) отзываются при отзыве корня;
- superseded_by-связь отзывается;
- транзитивная цепочка A->B->C;
- циклы не зацикливаются;
- уже REFUTED зависимые не перезаписываются (история, ADR-0002);
- независимые узлы не тронуты;
- интеграция с layer: intel_retract_memory_node каскадит, причина трассируется
  (PROPAGATED_FROM:<root> | <root_reason>, retract_source="propagation").
"""

import asyncio
import json
from pathlib import Path

import pytest

from src.core.intelligence.layer import ProjectIntelligenceLayer
from src.core.intelligence.propagation_engine import (
    RETRACT_SOURCE_PROPAGATION,
    PropagationEngine,
)
from src.core.intelligence.store import IntelligenceStore


@pytest.fixture
def isolated_data(tmp_path: Path, monkeypatch):
    """Изолирует <data_root> от реального: MSCODEBASE_DATA_DIR -> tmp_path."""
    data_root = tmp_path / "data_root"
    monkeypatch.setenv("MSCODEBASE_DATA_DIR", str(data_root))
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    return project


def _node(node_id: str, depends_on=None, superseded_by=None) -> dict:
    data = {"claim": "x"}
    if depends_on:
        data["depends_on"] = depends_on
    n = {
        "node_id": node_id,
        "section": "adrs",
        "timestamp": "t",
        "data": data,
        "status": "ACTIVE",
    }
    if superseded_by:
        n["superseded_by"] = superseded_by
    return n


def _seed(store: IntelligenceStore, nodes) -> None:
    store.save_memory(nodes)


# =====================================================================
# PROPAGATION ENGINE (unit)
# =====================================================================


def test_direct_dependent_retracted(isolated_data: Path):
    store = IntelligenceStore(isolated_data)
    _seed(store, [_node("A"), _node("B", depends_on=["A"]), _node("C")])
    nodes = store._load_json("project_memory.json")

    transitions = PropagationEngine.retract_cascade(nodes, "A", "факт устарел")
    assert [t["node_id"] for t in transitions] == ["B"]
    t = transitions[0]
    assert t["retract_source"] == RETRACT_SOURCE_PROPAGATION
    assert t["retract_reason"].startswith("PROPAGATED_FROM:A")
    assert "факт устарел" in t["retract_reason"]


def test_superseded_by_relation_retracted(isolated_data: Path):
    store = IntelligenceStore(isolated_data)
    _seed(store, [_node("A"), _node("B", superseded_by="A")])
    nodes = store._load_json("project_memory.json")

    transitions = PropagationEngine.retract_cascade(nodes, "A", "r")
    assert [t["node_id"] for t in transitions] == ["B"]


def test_transitive_chain(isolated_data: Path):
    store = IntelligenceStore(isolated_data)
    _seed(store, [
        _node("A"),
        _node("B", depends_on=["A"]),
        _node("C", depends_on=["B"]),
    ])
    nodes = store._load_json("project_memory.json")

    transitions = PropagationEngine.retract_cascade(nodes, "A", "r")
    assert {t["node_id"] for t in transitions} == {"B", "C"}


def test_cycle_safe(isolated_data: Path):
    store = IntelligenceStore(isolated_data)
    _seed(store, [
        _node("A", depends_on=["B"]),
        _node("B", depends_on=["A"]),
    ])
    nodes = store._load_json("project_memory.json")

    transitions = PropagationEngine.retract_cascade(nodes, "A", "r")
    assert [t["node_id"] for t in transitions] == ["B"]


def test_already_refuted_dependent_skipped(isolated_data: Path):
    store = IntelligenceStore(isolated_data)
    dep = _node("B", depends_on=["A"])
    dep["status"] = "REFUTED"
    _seed(store, [_node("A"), dep])
    nodes = store._load_json("project_memory.json")

    transitions = PropagationEngine.retract_cascade(nodes, "A", "r")
    assert transitions == []


def test_independent_nodes_not_touched(isolated_data: Path):
    store = IntelligenceStore(isolated_data)
    _seed(store, [_node("A"), _node("X"), _node("Y")])
    nodes = store._load_json("project_memory.json")

    assert PropagationEngine.retract_cascade(nodes, "A", "r") == []


def test_find_dependents_returns_direct_only(isolated_data: Path):
    store = IntelligenceStore(isolated_data)
    _seed(store, [
        _node("A"),
        _node("B", depends_on=["A"]),
        _node("C", depends_on=["B"]),
    ])
    nodes = store._load_json("project_memory.json")

    assert [n["node_id"] for n in PropagationEngine.find_dependents(nodes, "A")] == ["B"]
    assert [n["node_id"] for n in PropagationEngine.find_dependents(nodes, "B")] == ["C"]


# =====================================================================
# ИНТЕГРАЦИЯ С LAYER (intel_retract_memory_node)
# =====================================================================


def test_layer_retract_cascades_to_dependents(isolated_data: Path):
    layer = ProjectIntelligenceLayer(isolated_data, None, None, None)  # type: ignore[arg-type]

    async def _setup() -> str:
        await layer.intel_add_memory_node("adrs", json.dumps({"claim": "базовый факт"}))
        node_a = layer.store._load_json("project_memory.json")[-1]["node_id"]
        await layer.intel_add_memory_node(
            "adrs", json.dumps({"claim": "производный факт", "depends_on": [node_a]})
        )
        return node_a

    node_a = asyncio.run(_setup())

    resp = asyncio.run(layer.intel_retract_memory_node(node_a, "базовый факт опровергнут"))
    assert "отозван" in resp and "+1 зависимых отозвано" in resp

    # Оба скрыты из retrieval по умолчанию
    assert layer.store.load_memory()["adrs"] == []

    full = {n["node_id"]: n for n in layer.store.load_memory(include_retracted=True)["adrs"]}
    assert full[node_a]["status"] == "REFUTED"
    assert full[node_a]["retract_reason"] == "базовый факт опровергнут"

    dep = [n for n in full.values() if n["node_id"] != node_a][0]
    assert dep["status"] == "REFUTED"
    assert dep["retract_source"] == RETRACT_SOURCE_PROPAGATION
    assert dep["retract_reason"].startswith("PROPAGATED_FROM:")
    assert node_a in dep["retract_reason"]
    assert "retracted_at" in dep


def test_layer_retract_no_cascade_without_dependencies(isolated_data: Path):
    layer = ProjectIntelligenceLayer(isolated_data, None, None, None)  # type: ignore[arg-type]

    async def _setup() -> str:
        await layer.intel_add_memory_node("adrs", json.dumps({"claim": "самостоятельный факт"}))
        node_a = layer.store._load_json("project_memory.json")[-1]["node_id"]
        await layer.intel_add_memory_node("adrs", json.dumps({"claim": "другой факт"}))
        return node_a

    node_a = asyncio.run(_setup())

    resp = asyncio.run(layer.intel_retract_memory_node(node_a, "устарел"))
    assert "+1 зависимых" not in resp

    full = {n["node_id"]: n for n in layer.store.load_memory(include_retracted=True)["adrs"]}
    assert len([n for n in full.values() if n["status"] == "REFUTED"]) == 1
