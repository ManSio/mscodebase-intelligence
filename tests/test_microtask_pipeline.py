"""Unit tests for the microtask pipeline (tools/microtask_pipeline).

Import convention follows the repo: the module is loaded from its path, so the
test does not depend on the package layout.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PIPELINE_DIR = ROOT / "tools" / "microtask_pipeline"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, PIPELINE_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


engine = _load("engine")


@pytest.fixture()
def repo(tmp_path: Path) -> tuple[Path, Path]:
    work = tmp_path / "repo"
    (work / "src").mkdir(parents=True)
    (work / "tests").mkdir()
    (work / "src" / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (work / "tests" / "test_mod.py").write_text(
        "from src.mod import f\n\n\ndef test_f():\n    assert f() == 2\n", encoding="utf-8"
    )
    pristine = tmp_path / "pristine"
    pristine.mkdir()
    (pristine / "src").mkdir()
    (pristine / "tests").mkdir()
    (pristine / "src" / "mod.py").write_text((work / "src" / "mod.py").read_text(encoding="utf-8"), encoding="utf-8")
    (pristine / "tests" / "test_mod.py").write_text(
        (work / "tests" / "test_mod.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    return work, pristine


# ── the diff applier ────────────────────────────────────────────────────────


def test_apply_unified_diff_replaces_the_block():
    original = "a = 1\nb = 2\nc = 3\n"
    diff = "@@ -1,3 +1,3 @@\n a = 1\n-b = 2\n+b = 22\n c = 3\n"
    patched, error = engine.apply_unified_diff(original, diff)
    assert not error
    assert patched == "a = 1\nb = 22\nc = 3\n"


def test_apply_unified_diff_refuses_when_context_is_absent():
    patched, error = engine.apply_unified_diff("a = 1\n", "@@ -1 +1 @@\n-nope\n+yes\n")
    assert patched is None
    assert "not found" in error


def test_apply_unified_diff_needs_a_diff():
    patched, error = engine.apply_unified_diff("a = 1\n", "just prose")
    assert patched is None
    assert "no unified diff" in error


# ── the guards ──────────────────────────────────────────────────────────────


def test_write_outside_the_repo_is_refused(repo):
    work, pristine = repo
    guard = engine.Guard(repo=work, pristine=pristine, allowed_writes={"src/mod.py"})
    harness = engine.Harness(work, pristine, guard)
    result = harness.run_tool("write_file", {"path": "../escaped.txt", "content": "x"})
    assert result.ok is False
    assert "escapes" in (result.error or "")
    assert not (work.parent / "escaped.txt").exists()


def test_write_to_a_test_file_is_refused(repo):
    work, pristine = repo
    guard = engine.Guard(repo=work, pristine=pristine, allowed_writes={"src/mod.py"})
    harness = engine.Harness(work, pristine, guard)
    result = harness.run_tool("write_file", {"path": "tests/test_mod.py", "content": "x"})
    assert result.ok is False
    assert "test files" in (result.error or "")


def test_write_outside_the_scope_is_refused(repo):
    work, pristine = repo
    guard = engine.Guard(repo=work, pristine=pristine, allowed_writes={"src/mod.py"})
    harness = engine.Harness(work, pristine, guard)
    result = harness.run_tool("write_file", {"path": "src/other.py", "content": "x"})
    assert result.ok is False
    assert "allowed scope" in (result.error or "")


def test_tampered_test_is_restored(repo):
    work, pristine = repo
    guard = engine.Guard(repo=work, pristine=pristine, allowed_writes={"src/mod.py"})
    original = (work / "tests" / "test_mod.py").read_text(encoding="utf-8")
    (work / "tests" / "test_mod.py").write_text("def test_f():\n    assert True\n", encoding="utf-8")
    restored = guard.restore_tests()
    assert restored == ["tests/test_mod.py"]
    assert (work / "tests" / "test_mod.py").read_text(encoding="utf-8") == original
    assert guard.violations


def test_command_output_is_summarised_not_inlined(repo):
    work, pristine = repo
    guard = engine.Guard(repo=work, pristine=pristine, allowed_writes={"src/mod.py"})
    harness = engine.Harness(work, pristine, guard)
    result = harness.run_tool("run_command", {"cmd": "python -c \"print('x'*5000)\""})
    assert len(result.observation) < 500
    assert "exit=" in result.observation


def test_output_slice_is_capped(repo):
    work, pristine = repo
    guard = engine.Guard(repo=work, pristine=pristine, allowed_writes={"src/mod.py"})
    harness = engine.Harness(work, pristine, guard)
    run = harness.run_tool("run_command", {"cmd": "python -c \"print('\\n'.join(str(i) for i in range(500)))\""})
    sliced = harness.run_tool("read_output", {"handle": run.handle, "from": 0, "to": 500})
    assert len(sliced.observation.splitlines()) <= engine.MAX_OUTPUT_LINES


def test_unknown_tool_is_refused(repo):
    work, pristine = repo
    guard = engine.Guard(repo=work, pristine=pristine, allowed_writes=set())
    harness = engine.Harness(work, pristine, guard)
    result = harness.run_tool("rm_rf", {"path": "src"})
    assert result.ok is False


# ── the plan and the brief ──────────────────────────────────────────────────


def test_code_first_plan_names_the_source_file_not_the_test(repo):
    work, pristine = repo
    plan = engine.code_first_plan("fix it", work, pairs=[("src/mod.py", "tests/test_mod.py")])
    assert len(plan) == 1
    assert plan[0].file == "src/mod.py"
    assert plan[0].test_file == "tests/test_mod.py"
    assert "tests/test_mod.py" in plan[0].acceptance


def test_brief_shrinks_to_fit_the_budget(repo):
    work, pristine = repo
    task = engine.Microtask(
        id="T1", file="src/mod.py", goal="fix", acceptance="pytest -q", test_file="tests/test_mod.py"
    )
    (work / "src" / "mod.py").write_text("\n".join(f"line {i}" for i in range(2000)), encoding="utf-8")
    context = engine._context_for(task, work, "tests/test_mod.py::test_f")
    assert engine.estimate_tokens(context) <= engine.MAX_PROMPT_TOKENS


def test_relevant_slice_finds_the_function_the_test_calls(repo):
    work, pristine = repo
    (work / "src" / "mod.py").write_text(
        "def unrelated():\n    return 0\n\n\ndef target_helper():\n    return 1\n", encoding="utf-8"
    )
    task = engine.Microtask(
        id="T1", file="src/mod.py", goal="fix", acceptance="pytest -q", test_file="tests/test_mod.py"
    )
    context = engine._context_for(task, work, "tests/test_mod.py::test_f")
    assert "target_helper" in context


def test_relevant_slice_keeps_a_multi_line_signature_body(tmp_path):
    """Regression: the audit showed the model only receiving a signature.

    An indentation-based block guess stops at the closing line of a multi-line
    signature, so the body was cut and the model had nothing to fix. The slice
    must come from the AST.
    """
    source = (
        "def run_bounded(\n"
        "    fn,\n"
        "    timeout,\n"
        "    *,\n"
        "    default=None,\n"
        ") -> Any:\n"
        '    """Doc."""\n'
        "    if 'error' in box:\n"
        "        raise box['error']\n"
        "    return box['result']\n"
    )
    blocks = engine._ast_blocks(source.splitlines(keepends=True), {"run_bounded"}, 80)
    joined = "".join(blocks)
    assert "return box['result']" in joined
    assert "if 'error' in box" in joined


def test_brief_of_a_real_function_includes_its_body(tmp_path):
    source = (
        "def compute(\n"
        "    values,\n"
        ") -> int:\n"
        "    total = 0\n"
        "    for value in values:\n"
        "        total += value\n"
        "    return total\n"
    )
    lines = source.splitlines(keepends=True)
    blocks = engine._ast_blocks(lines, {"compute"}, 80)
    assert "total += value" in "".join(blocks)


# ── receipts and the verdict ───────────────────────────────────────────────


def test_receipt_binds_the_artifact_hash(repo):
    work, pristine = repo
    task = engine.Microtask(
        id="T1", file="src/mod.py", goal="fix", acceptance="pytest -q", test_file="tests/test_mod.py"
    )
    receipt = engine.make_receipt(task, work, {"cmd": "pytest -q", "exit": 0}, scope_ok=True)
    assert receipt["issued_by"].startswith("harness")
    assert receipt["artifact_sha256"] == engine.sha256_file(work / "src" / "mod.py")
    assert receipt["verify"]["exit"] == 0
    assert json.dumps(receipt)  # must be serialisable into the parent's context
