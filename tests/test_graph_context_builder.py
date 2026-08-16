"""Unit-тесты graph_context_builder (Exp 2-E, Rung 3): детерминизм, декой, leak-guard.

Builder детерминирован и не требует PropertyGraph (enable_graph=False) —
тесты не зависят от живой БД графа (CI-safe).
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "graph_context_builder", ROOT / "experiments" / "2E_evidence_ladder" / "graph_context_builder.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # noqa: E402


def _builder():
    return _mod.GraphContextBuilder(ROOT, enable_graph=False)


def test_decoy_for_unresolvable_token():
    """Несуществующий токен (mutation_absent/silent) → декой, evidence=decoy."""
    ctx = _mod.build_contexts([{"id": "T1", "support_patterns": ["typesense_absent_xyz"]}], _builder())
    assert ctx["T1"]["evidence"] == "decoy"
    assert "typesense_absent_xyz" not in ctx["T1"]["block"]


def test_no_truth_leak():
    """Truth-лейбл не попадает ни в блок, ни в метаданные (assert в build_contexts)."""
    facts = [{"id": "T1", "support_patterns": ["pathlib"], "truth": False}]
    ctx = _mod.build_contexts(facts, _builder())
    assert "truth" not in ctx["T1"]["block"]


def test_occurrences_block_for_stdlib_token():
    """mutation_present (pathlib): OCCURS-блок со списком файлов, evidence=real."""
    ctx = _mod.build_contexts([{"id": "T1", "support_patterns": ["pathlib"]}], _builder())
    assert ctx["T1"]["evidence"] == "real"
    assert ctx["T1"]["block"].startswith("TOKEN: pathlib")
    assert "occurs in" in ctx["T1"]["block"]
    assert "src/" in ctx["T1"]["block"]


def test_file_block():
    """file:-якорь → FILE-блок с импортами и определениями."""
    ctx = _mod.build_contexts(
        [{"id": "T1", "support_patterns": ["file:src/core/consistency.py"]}], _builder())
    assert ctx["T1"]["evidence"] == "real"
    assert ctx["T1"]["block"].startswith("FILE: src/core/consistency.py")
    assert "imports" in ctx["T1"]["block"]


def test_missing_file_anchor_falls_to_decoy():
    """file:-якорь на несуществующий файл → не резолвится → декой."""
    ctx = _mod.build_contexts(
        [{"id": "T1", "support_patterns": ["file:src/core/no_such_file_xyz.py"]}], _builder())
    assert ctx["T1"]["evidence"] == "decoy"


def test_deterministic_output():
    """Один и тот же вход → идентичный выход (детерминизм evidence)."""
    b = _builder()
    facts = [{"id": "T1", "support_patterns": ["pathlib"]},
             {"id": "T2", "support_patterns": ["file:src/core/instruction_scan.py"]},
             {"id": "T3", "support_patterns": ["nope_absent_xyz"]}]
    assert _mod.build_contexts(facts, b) == _mod.build_contexts(facts, _builder())


def test_control_block_not_empty():
    """Декой-блок (контрольный символ) всегда непустой — даже без графа."""
    b = _builder()
    block = _mod._control_block(b)
    assert block.strip()
    assert "instruction_scan" in block.lower()


# ─── Temporal-контексты (Rung 4) ────────────────────────────────────────────
def test_temporal_contexts_removed_and_real():
    """removed: NOT FOUND + existed at commit; real: блок + last commit touching."""
    facts = [
        {"id": "T1", "support_patterns": ["file:src/core/definitely_removed_xyz.py"],
         "value": "GhostSymbol", "valid_at_commit": "abc1234deadbeef",
         "evidence_git": {"hash": "abc1234deadbeef", "date": "2026-08-01",
                          "subject": "removed ghost", "branch": "main"}},
        {"id": "T2", "support_patterns": ["file:src/core/consistency.py"],
         "valid_at_commit": "def5678cafe",
         "evidence_git": {"hash": "def5678cafe", "date": "2026-08-02",
                          "subject": "touched", "branch": "main"}},
    ]
    ctx = _mod.build_temporal_contexts(facts, _builder())
    assert ctx["T1"]["evidence"] == "removed"
    assert "NOT FOUND AT HEAD" in ctx["T1"]["block"]
    assert "existed until commit abc1234" in ctx["T1"]["block"]
    assert "truth" not in ctx["T1"]["block"]
    assert ctx["T2"]["evidence"] == "real"
    assert "GIT: last commit touching" in ctx["T2"]["block"]


def test_temporal_contexts_absent_no_trail():
    """absent: NOT FOUND + no history (без fake-трейла)."""
    facts = [{"id": "T1", "support_patterns": ["file:src/core/ghost_absent_xyz.py"],
              "value": "GhostAbsent", "valid_at_commit": None,
              "evidence_git": {"hash": "", "date": "", "subject": "", "branch": "main"}}]
    ctx = _mod.build_temporal_contexts(facts, _builder())
    assert ctx["T1"]["evidence"] == "absent"
    assert "no history" in ctx["T1"]["block"]
    assert "NOT FOUND AT HEAD" in ctx["T1"]["block"]
