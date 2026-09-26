"""Guard for PropertyGraph.batch() (E18, 2026-09-25).

Per-row named-mutex + BEGIN/commit gave ~142 entities/s; batching all node/edge
writes of one file into a single transaction is ~67k/s (exp_graph_write_throughput).
These tests prove the batched path is CORRECT (same counts), ATOMIC (rollback on
error), REENTRANT, and leaves non-batch behaviour unchanged.

Run: PYTHONPATH=src python -m pytest tests/test_graph_batch.py -q
"""
from __future__ import annotations

import pytest

from src.core.graph import PropertyGraph

N_NODES = 40
N_EDGES = 80


def _seed(pg: PropertyGraph, batched: bool) -> None:
    def _do():
        for i in range(N_NODES):
            pg.add_node(name=f"n{i}", qualified_name=f"p.f{i}", label="Function")
        for i in range(N_EDGES):
            pg.add_edge(f"p.f{i % N_NODES}", f"p.f{(i + 1) % N_NODES}", type="CALLS")

    if batched:
        with pg.batch():
            _do()
    else:
        _do()


def test_batch_counts_match_nonbatch(tmp_path):
    pg1 = PropertyGraph(tmp_path / "a.db")
    pg2 = PropertyGraph(tmp_path / "b.db")
    _seed(pg1, batched=False)
    _seed(pg2, batched=True)

    assert pg1.count_nodes() == pg2.count_nodes() == N_NODES
    assert pg1.count_edges() == pg2.count_edges()
    assert pg2.count_edges() > 0


def test_batch_is_atomic_rolls_back_on_error(tmp_path):
    pg = PropertyGraph(tmp_path / "c.db")
    with pytest.raises(RuntimeError):
        with pg.batch():
            pg.add_node(name="x", qualified_name="p.x", label="Function")
            raise RuntimeError("boom")
    assert pg.count_nodes() == 0, "partial batch must be rolled back"

    # Graph stays usable after a rolled-back batch.
    pg.add_node(name="y", qualified_name="p.y", label="Function")
    assert pg.count_nodes() == 1


def test_nested_batch_reuses_one_transaction(tmp_path):
    pg = PropertyGraph(tmp_path / "d.db")
    with pg.batch():
        pg.add_node(name="a", qualified_name="p.a", label="Function")
        with pg.batch():  # nested -> same tx
            pg.add_node(name="b", qualified_name="p.b", label="Function")
        pg.add_node(name="c", qualified_name="p.c", label="Function")
    assert pg.count_nodes() == 3


def test_batch_commits_and_persists(tmp_path):
    db = tmp_path / "e.db"
    pg = PropertyGraph(db)
    with pg.batch():
        pg.add_node(name="a", qualified_name="p.a", label="Function")
    pg.close()

    reopened = PropertyGraph(db)
    assert reopened.count_nodes() == 1


def test_concurrent_batches_do_not_share_a_transaction(tmp_path):
    # Multi-threaded parse phase (4 _parse_worker threads) wrote into one
    # shared batch and corrupted each other ("cannot start a transaction within
    # a transaction"). A different thread must NOT join an open batch; it must
    # block and get its own. Barrier forces overlap; without the owner check
    # this raises OperationalError and/or miscounts.
    import threading

    pg = PropertyGraph(tmp_path / "f.db")
    barrier = threading.Barrier(2)
    errors: list = []
    n = 60

    def worker(tag: str):
        try:
            barrier.wait(timeout=10)
            with pg.batch():
                for i in range(n):
                    pg.add_node(
                        name=f"{tag}{i}",
                        qualified_name=f"p.{tag}{i}",
                        label="Function",
                    )
        except Exception as e:  # noqa: BLE001 — collected, asserted below
            errors.append(e)

    ts = [
        threading.Thread(target=worker, args=("a",)),
        threading.Thread(target=worker, args=("b",)),
    ]
    for t in ts:
        t.start()
    for t in ts:
        t.join(30)
    assert not [t for t in ts if t.is_alive()], "batch deadlocked across threads"
    assert not errors, f"concurrent batches interfered: {errors!r}"
    assert pg.count_nodes() == 2 * n
