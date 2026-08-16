"""Unit-тесты trap_facts_generator (Exp 2-E E5, P-00X): валидация лейблов ПО СУБЪЕКТУ.

Демонстрация фикса генератора v4_rep: false-trap обязан иметь value, отсутствующий
в файле СУБЪЕКТА (grep субъекта = 0), даже если value есть в проекте.
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "trap_facts_generator", ROOT / "experiments" / "2E_evidence_ladder" / "trap_facts_generator.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # noqa: E402


def test_structure_and_kinds():
    facts = _mod.generate()
    assert len(facts) >= 24
    kinds = {f["kind"] for f in facts}
    assert kinds == {"trap_false", "trap_true"}
    assert sum(1 for f in facts if f["kind"] == "trap_false") >= 2 * sum(
        1 for f in facts if f["kind"] == "trap_true")


def test_false_traps_are_subject_absent():
    """P-00X: у каждого false-trap value ОТСУТСТВУЕТ в файле субъекта (главный фикс)."""
    for f in _mod.generate():
        if f["kind"] != "trap_false":
            continue
        path = ROOT / _subj_path_for(f["claim"])
        text = path.read_text(encoding="utf-8", errors="replace")
        assert not _mod._in_file(text, f["value"]), \
            f"{f['id']}: value '{f['value']}' найден в файле субъекта — лейбл false неверен (P-00X)"
        assert "subject_file=0" in f["label_validated"], f"{f['id']}: нет метки валидации"


def _subj_path_for(claim: str) -> str:
    """Путь субъекта из claim: «<Label> использует <value>» — по соответствию label->path."""
    # проще: вернуть путь из пары label-claim через SUBJECTS
    for label, rel in _mod.SUBJECTS:
        if claim.startswith(label):
            return rel
    raise AssertionError(f"label не найден для claim: {claim}")


def test_true_traps_are_subject_present():
    """true-trap: value есть в файле субъекта (валидация по субъекту)."""
    for f in _mod.generate():
        if f["kind"] != "trap_true":
            continue
        path = ROOT / _subj_path_for(f["claim"])
        text = path.read_text(encoding="utf-8", errors="replace")
        assert _mod._in_file(text, f["value"]), \
            f"{f['id']}: value '{f['value']}' НЕ найден в файле субъекта — лейбл true неверен"


def test_false_trap_values_exist_in_project():
    """false-trap: value реально встречается в проекте (не выдумка)."""
    stats = _mod._project_import_stats()
    for f in _mod.generate():
        if f["kind"] != "trap_false":
            continue
        assert stats.get(f["value"], 0) >= _mod.MIN_PROJECT_FILES, \
            f"{f['id']}: '{f['value']}' нет в проекте (это absent, не trap)"


def test_deterministic():
    assert _mod.generate() == _mod.generate()
