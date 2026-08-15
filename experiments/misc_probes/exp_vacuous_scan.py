"""EXP-2: Скан тестов на вакуумность — «40 guards, 33 unproven» для MSCodeBase.

Метрика Max Quimby: тест, который не может вернуть false, — не «проходит»,
а «не проверен». Синтаксический AST-скан tests/: тест = «доказан» (может
упасть), если содержит минимум один assert / pytest.raises / pytest.warns /
pytest.xfail / pytest.fail / raise.

Ограничение (честно, §5.15): скан не видит asserts в вызываемых хелперах —
число «вакуумных» это ВЕРХНЯЯ граница (часть помеченных может быть доказана
через хелперы). skip/skipif НЕ считаются «доказанными» (скип не провал).
"""
import ast
import sys
import traceback
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

TESTS_DIR = Path(__file__).resolve().parent.parent / "tests"
SKIP_FILES = {"conftest.py"}

# Конструкции, способные уронить тест
FAIL_ATTRS = {"raises", "warns", "xfail", "fail"}
# Mock-утверждения: mock.assert_called_once() и т.п. кидают AssertionError
MOCK_ASSERT_PREFIX = "assert_"


def has_failing_construct(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Assert):
            return True
        if isinstance(sub, ast.Raise):
            return True
        if isinstance(sub, ast.Call):
            f = sub.func
            if isinstance(f, ast.Attribute):
                if f.attr in FAIL_ATTRS or f.attr.startswith(MOCK_ASSERT_PREFIX):
                    return True
            if isinstance(f, ast.Name) and f.id in {"raises", "warns", "fail"}:
                return True
    return False


def is_skipped(node) -> bool:
    for dec in node.decorator_list:
        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) \
                and dec.func.attr in {"skip", "skipif"}:
            return True
        if isinstance(dec, ast.Attribute) and dec.attr in {"skip", "skipif"}:
            return True
    return False


def main():
    total = 0
    proven = 0
    unproven = []
    skipped = 0
    examples = []

    for py in sorted(TESTS_DIR.glob("test_*.py")):
        if py.name in SKIP_FILES:
            continue
        try:
            src = py.read_text(encoding="utf-8")
            tree = ast.parse(src, filename=str(py))
        except SyntaxError as e:
            print(f"  ⚠️  SyntaxError в {py.name}: {e}")
            continue

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            total += 1
            if is_skipped(node):
                skipped += 1
                continue
            if has_failing_construct(node):
                proven += 1
            else:
                loc = f"{py.name}:{node.lineno}"
                unproven.append(loc)
                if len(examples) < 30:
                    body = ast.get_source_segment(src, node) or ""
                    examples.append((loc, node.name, body[:170].replace("\n", " | ")))

    print("=" * 72)
    print("EXP-2: Скан тестов на вакуумность (AST, синтаксический)")
    print(f"Каталог: {TESTS_DIR}")
    print("=" * 72)
    print(f"Всего тестов (test_* функций и методов Test*): {total}")
    print(f"  proven (есть assert/raises/warns/fail/raise): {proven}")
    print(f"  вакуумных (не могут упасть):                  {len(unproven)}")
    print(f"  skip (by design):                             {skipped}")
    print(f"  доля вакуумных: {len(unproven)/max(total,1)*100:.1f}%")
    print("\nПримеры вакуумных (первые 30):")
    for loc, name, body in examples:
        print(f"  {loc}  def {name}: {body}")
    print("\nПолный список вакуумных:")
    for loc in unproven:
        print(f"  {loc}")

    print("=" * 72)
    print("ИТОГ: таблица Max Quimby для MSCodeBase: "
          f"{proven} proven / {len(unproven)} unproven / {skipped} skipped")
    print("=" * 72)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
