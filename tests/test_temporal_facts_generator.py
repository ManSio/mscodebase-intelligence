"""Unit-тесты temporal_facts_generator (Exp 2-E, Rung 4): структура, ground truth, детерминизм.

Генератор использует git (репозиторий проекта) — тесты валидируют инварианты
ground truth: removed-факт обязан быть правдой на valid_at_commit (git show),
absent-имена обязаны быть grep-0.
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "temporal_facts_generator", ROOT / "experiments" / "2E_evidence_ladder" / "temporal_facts_generator.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # noqa: E402


def test_generate_structure_and_kinds():
    facts = _mod.generate(seed=7)
    assert len(facts) >= 30
    kinds = {f["kind"] for f in facts}
    assert {"removed", "real", "absent"} <= kinds
    for f in facts:
        assert isinstance(f["truth"], bool)
        assert f["claim"]
        assert f["evidence_git"]["branch"]
        assert f["id"].startswith("T")


def test_removed_ground_truth_validated_via_git():
    """removed-факт: символ реально был на C~1 (родителе коммита удаления), false@HEAD."""
    removed = [f for f in _mod.generate(seed=7) if f["kind"] == "removed"]
    assert removed
    r = removed[0]
    path = r["support_patterns"][0][5:]
    parent = _mod._git("rev-parse", f"{r['valid_at_commit']}~1").strip()
    text = _mod._git("show", f"{parent}:{path}")
    assert text, f"файл {path} не существует на {parent} (родителе {r['valid_at_commit']})"
    assert r["value"] in _mod._ast_names(text)
    # на самом коммите удаления файла уже нет
    assert not _mod._git("show", f"{r['valid_at_commit']}:{path}")
    assert r["was_true"] is True and r["truth"] is False


def test_absent_names_are_grep_zero():
    for f in _mod.generate(seed=7):
        if f["kind"] == "absent":
            assert _mod._grep_zero(f["value"]), f"{f['value']} встречается в src/"


def test_deterministic_generation():
    assert _mod.generate(seed=7) == _mod.generate(seed=7)
