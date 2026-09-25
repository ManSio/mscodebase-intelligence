"""Тесты quiet-break gate (дельта-изоляция узлов графа на коммите).

Покрытие: parse_diff (removed calls/defs, new defs, decorated, комментарии),
is_whitelisted, run_quiet_break_gate (A removed_last_caller + rename-guard,
B new_orphan + called/decorated, fail-open unavailable/empty).
"""
from pathlib import Path

from src.core.graph import EdgeType, NodeLabel, PropertyGraph
from src.core.quiet_break_gate import is_whitelisted, parse_diff, run_quiet_break_gate


def _mk_graph(tmp_path: Path) -> PropertyGraph:
    return PropertyGraph(tmp_path / "graph.db")


def _add_func(pg: PropertyGraph, name: str, rel: str, root: Path) -> None:
    pg.add_node(
        name=name,
        label=NodeLabel.FUNCTION,
        qualified_name=f"proj.{rel}.{name}",
        file_path=str(root / rel),
    )


# ── parse_diff ──

def test_parse_diff_removed_calls_and_new_defs():
    diff = (
        "diff --git a/pkg/caller.py b/pkg/caller.py\n"
        "--- a/pkg/caller.py\n"
        "+++ b/pkg/caller.py\n"
        "@@ -1,3 +1,3 @@\n"
        "-    target()\n"
        "+def helper():\n"
        "+    pass\n"
    )
    d = parse_diff(diff)
    assert d["changed_files"] == ["pkg/caller.py"]
    assert d["removed_calls"] == {"target": ["pkg/caller.py"]}
    assert d["removed_defs"] == set()
    assert [x["name"] for x in d["new_defs"]] == ["helper"]
    assert d["new_defs"][0]["decorated"] is False


def test_parse_diff_rename_guard_and_decorator_and_comment():
    diff = (
        "diff --git a/x.py b/x.py\n"
        "--- a/x.py\n"
        "+++ b/x.py\n"
        "@@ -1,4 +1,4 @@\n"
        "-def old_name():\n"
        "-    # note: commented(target)\n"
        "+@register\n"
        "+def new_name():\n"
        "+    pass\n"
    )
    d = parse_diff(diff)
    assert "old_name" in d["removed_defs"]
    assert "target" not in d["removed_calls"]  # строки-комментарии игнорируются
    nd = {x["name"]: x for x in d["new_defs"]}
    assert nd["new_name"]["decorated"] is True


# ── is_whitelisted ──

def test_whitelist():
    assert is_whitelisted("main")
    assert is_whitelisted("test_something")
    assert is_whitelisted("step_lm")
    assert is_whitelisted("__init__")
    assert is_whitelisted("anything", decorated=True)
    assert not is_whitelisted("helper")
    assert not is_whitelisted("process_order")


# ── run_quiet_break_gate ──

def test_removed_last_caller_fires(tmp_path):
    root = tmp_path
    (root / "pkg").mkdir()
    (root / "pkg" / "caller.py").write_text("def caller():\n    pass\n", encoding="utf-8")
    pg = _mk_graph(root)
    _add_func(pg, "caller", "pkg/caller.py", root)
    _add_func(pg, "target", "pkg/target.py", root)
    pg.add_edge("proj.pkg/caller.py.caller", "proj.pkg/target.py.target", EdgeType.CALLS)

    diff = (
        "--- a/pkg/caller.py\n+++ b/pkg/caller.py\n@@ -1,2 +1,2 @@\n"
        " def caller():\n-    target()\n+    pass\n"
    )
    res = run_quiet_break_gate(root, pg, diff_text=diff)
    assert res["status"] == "ok"
    assert res["counts"]["removed_last_caller"] == 1
    assert res["findings"][0]["symbol"] == "target"


def test_removed_last_caller_not_fired_when_caller_unchanged(tmp_path):
    root = tmp_path
    (root / "pkg").mkdir()
    (root / "pkg" / "other.py").write_text("other.py placeholder", encoding="utf-8")
    pg = _mk_graph(root)
    _add_func(pg, "target", "pkg/target.py", root)
    _add_func(pg, "other", "pkg/other.py", root)
    pg.add_edge("proj.pkg/other.py.other", "proj.pkg/target.py.target", EdgeType.CALLS)

    # изменён ДРУГОЙ файл, вызывающий в other.py не тронут
    diff = (
        "--- a/pkg/some.py\n+++ b/pkg/some.py\n@@ -1,1 +1,1 @@\n-old()\n+new()\n"
    )
    res = run_quiet_break_gate(root, pg, diff_text=diff)
    assert res["counts"]["removed_last_caller"] == 0


def test_removed_last_caller_rename_guard(tmp_path):
    root = tmp_path
    (root / "pkg").mkdir()
    (root / "pkg" / "caller.py").write_text("def caller():\n    pass\n", encoding="utf-8")
    pg = _mk_graph(root)
    _add_func(pg, "caller", "pkg/caller.py", root)
    _add_func(pg, "target", "pkg/target.py", root)
    pg.add_edge("proj.pkg/caller.py.caller", "proj.pkg/target.py.target", EdgeType.CALLS)

    diff = (
        "--- a/pkg/target.py\n+++ b/pkg/target.py\n@@ -1,2 +1,2 @@\n"
        "-def target():\n"
        "+def target_renamed():\n"
        "-    target()\n"
    )
    res = run_quiet_break_gate(root, pg, diff_text=diff)
    assert res["counts"]["removed_last_caller"] == 0


def test_new_orphan_fires(tmp_path):
    root = tmp_path
    (root / "pkg").mkdir()
    (root / "pkg" / "mod.py").write_text(
        "def helper():\n    pass\n", encoding="utf-8"
    )
    pg = _mk_graph(root)
    _add_func(pg, "use", "pkg/mod.py", root)

    orphan_diff = (
        "--- a/pkg/mod.py\n+++ b/pkg/mod.py\n@@ -1,1 +1,3 @@\n"
        "+def helper():\n+    pass\n+\n"
    )
    res = run_quiet_break_gate(root, pg, diff_text=orphan_diff)
    assert res["counts"]["new_orphan"] == 1


def test_new_orphan_called_not_fired(tmp_path):
    root = tmp_path
    (root / "pkg").mkdir()
    (root / "pkg" / "mod.py").write_text(
        "def helper():\n    pass\n\ndef use():\n    helper()\n", encoding="utf-8"
    )
    pg = _mk_graph(root)
    _add_func(pg, "use", "pkg/mod.py", root)

    called_diff = (
        "--- a/pkg/mod.py\n+++ b/pkg/mod.py\n@@ -1,3 +1,3 @@\n"
        "+def helper():\n+    pass\n+\n"
        " def use():\n     helper()\n"
    )
    res = run_quiet_break_gate(root, pg, diff_text=called_diff)
    assert res["counts"]["new_orphan"] == 0


def test_new_orphan_decorated_skipped(tmp_path):
    root = tmp_path
    (root / "pkg").mkdir()
    (root / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    pg = _mk_graph(root)
    diff = (
        "--- a/pkg/mod.py\n+++ b/pkg/mod.py\n@@ -1,1 +1,3 @@\n"
        "+@register\n+def handler():\n+    pass\n"
    )
    res = run_quiet_break_gate(root, pg, diff_text=diff)
    assert res["counts"]["new_orphan"] == 0


def test_unavailable_and_empty(tmp_path):
    root = tmp_path
    res = run_quiet_break_gate(root, None, diff_text="")
    assert res["status"] == "unavailable"
    assert res["findings"] == []

    pg = _mk_graph(root)
    _add_func(pg, "seed", "pkg/seed.py", root)
    res2 = run_quiet_break_gate(root, pg, diff_text="")
    assert res2["status"] == "empty"
    assert res2["findings"] == []
