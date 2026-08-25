"""test_impact.py — герметичные тесты статического предиктора blast radius.

Отрицательный контроль обязателен (протокол Тома): предиктор, который
"умеет" предсказывать ВСЁ, бесполезен — здесь проверяем и попадания,
и НЕ-попадания (test OTHER не должен быть затронут чужим изменением).
"""


from src.core.test_impact import (
    affected_gates,
    predict_affected_tests,
    referenced_modules,
    risk_level,
)


def _make_tree(tmp_path):
    """src/core/widget.py + 3 теста: два импортируют widget, один — нет."""
    root = tmp_path / "proj"
    src = root / "src" / "core"
    tests = root / "tests"
    (src / "__init__.py").parent.mkdir(parents=True)
    (src).mkdir(parents=True, exist_ok=True)
    tests.mkdir(parents=True, exist_ok=True)
    (src / "__init__.py").write_text("", encoding="utf-8")
    (src / "widget.py").write_text("def render() -> int:\n    return 1\n", encoding="utf-8")
    (tests / "test_widget.py").write_text(
        "from src.core.widget import render\n\ndef test_render():\n    assert render() == 1\n",
        encoding="utf-8",
    )
    (tests / "test_widget_remote.py").write_text(
        "from src.core import widget\n\ndef test_remote():\n    assert widget.render() == 1\n",
        encoding="utf-8",
    )
    (tests / "test_other.py").write_text(
        "def test_other():\n    assert 1 + 1 == 2\n",
        encoding="utf-8",
    )
    return root


class TestPredictAffectedTests:
    def test_direct_module_import_found(self, tmp_path):
        root = _make_tree(tmp_path)
        res = predict_affected_tests(["src/core/widget.py"], str(root))
        affected = res["affected_tests"]
        assert "tests/test_widget.py" in affected
        assert "tests/test_widget_remote.py" in affected  # под-импорт src.core.widget
        assert affected == sorted(affected)

    def test_unrelated_test_not_hit(self, tmp_path):
        """Отрицательный контроль: изменение widget НЕ трогает test_other."""
        root = _make_tree(tmp_path)
        res = predict_affected_tests(["src/core/widget.py"], str(root))
        assert "tests/test_other.py" not in res["affected_tests"]

    def test_no_false_hit_for_other_module(self, tmp_path):
        """Изменение чужого модуля не задевает widget-тесты."""
        root = _make_tree(tmp_path)
        (root / "src" / "core" / "gears.py").write_text("GEARS = 1\n", encoding="utf-8")
        res = predict_affected_tests(["src/core/gears.py"], str(root))
        assert res["affected_tests"] == []

    def test_symbol_hit_in_test_body(self, tmp_path):
        root = _make_tree(tmp_path)
        res = predict_affected_tests(["src/core/widget.py"], str(root), symbols=["render"])
        assert "tests/test_widget.py" in res["affected_tests"]

    def test_relative_import_resolution(self, tmp_path):
        """Изменение src/core/a: тест, импортирующий from . import a — ловится."""
        root = _make_tree(tmp_path)
        (root / "src" / "core" / "a.py").write_text("A = 1\n", encoding="utf-8")
        (root / "tests" / "test_a_rel.py").write_text(
            "from src.core import a\n\ndef test_a():\n    assert a.A == 1\n",
            encoding="utf-8",
        )
        res = predict_affected_tests(["src/core/a.py"], str(root))
        assert "tests/test_a_rel.py" in res["affected_tests"]


class TestGates:
    def test_core_change_affects_arch_gates(self, tmp_path):
        root = _make_tree(tmp_path)
        gates = affected_gates(["src/core/widget.py"], str(root))
        assert "architecture_linter" in gates
        assert "check_layer_boundaries" in gates
        assert "ruff" in gates

    def test_tests_only_change_no_linter(self, tmp_path):
        root = _make_tree(tmp_path)
        gates = affected_gates(["tests/test_other.py"], str(root))
        assert "architecture_linter" not in gates
        assert "ruff" in gates


class TestRisk:
    def test_risk_levels(self):
        assert risk_level(0) == "low"
        assert risk_level(3) == "medium"
        assert risk_level(9) == "high"

    def test_referenced_modules_absolute(self, tmp_path):
        root = _make_tree(tmp_path)
        tf = root / "tests" / "test_widget.py"
        refs = referenced_modules(tf, root)
        assert "src.core.widget" in refs
