"""Тесты SCM-определений (tags.scm) — Workstream A: wiring в parse_file.

Проверяют:
1. Формат-паритет с TARGET_NODES walk (qualified name, 0-based line, kind=node.type).
2. SCM ⊇ walk для языков с tags.scm (recall 100% + доп. символы: классы/async).
3. Fallback на walk-символы для языков БЕЗ tags.scm (yaml/toml/...).
4. Исключены variable/import/декораторные captures.
5. Compile-guard: все вендоренные tags.scm компилируются с установленными грамматиками
   (регрессия при будущем бампе tree-sitter-* — §5.19).
"""
import pathlib

import pytest

from src.core.indexing.parser import QUERIES_DIR, CodeParser

PY_SAMPLE = """import os

class MyClass:
    def method_a(self):
        return 1

    @property
    def prop(self):
        return 2

async def fetch_data():
    return [1, 2]

def plain():
    pass
"""

RS_SAMPLE = """struct Point { x: i32 }

impl Point {
    fn new(x: i32) -> Point { Point { x } }
}

fn main() {}
"""

TS_SAMPLE = """interface Shape { area(): number }
class Circle implements Shape {
    radius: number;
    area(): number { return 3.14 * this.radius; }
}
function helper(): void {}
type Alias = string;
"""


@pytest.fixture()
def parser():
    return CodeParser()


def _write(tmp_path: pathlib.Path, ext: str, code: str) -> pathlib.Path:
    f = tmp_path / f"sample{ext}"
    f.write_text(code, encoding="utf-8")
    return f


class TestFormatParity:
    """Формат SCM-символов = формат walk (потребители графа не меняются)."""

    def test_python_symbols_format(self, parser, tmp_path):
        f = _write(tmp_path, ".py", PY_SAMPLE)
        _, symbols = parser.parse_file(f)
        by_name = {s["name"]: s for s in symbols}

        assert by_name["MyClass"]["line"] == 2  # 0-based (1-based строка 3)
        assert by_name["MyClass"]["kind"] == "class_definition"
        assert by_name["MyClass.method_a"]["kind"] == "function_definition"
        # имя квалифицировано контекстом класса
        assert by_name["MyClass.method_a"]["name"] == "MyClass.method_a"

    def test_rust_impl_methods_qualified(self, parser, tmp_path):
        f = _write(tmp_path, ".rs", RS_SAMPLE)
        _, symbols = parser.parse_file(f)
        names = {s["name"] for s in symbols}
        assert "Point" in names            # struct_item — новый символ (walk его не даёт)
        assert "Point.new" in names        # метод внутри impl → qualified через impl_item
        assert "main" in names

    def test_typescript_class_methods_qualified(self, parser, tmp_path):
        f = _write(tmp_path, ".ts", TS_SAMPLE)
        _, symbols = parser.parse_file(f)
        names = {s["name"] for s in symbols}
        assert "Circle" in names
        assert "Circle.area" in names
        assert "Shape" in names            # interface_declaration
        assert "Alias" in names            # type_alias_declaration

    def test_decorated_and_async_python(self, parser, tmp_path):
        """Декорированные и async-определения, которые walk пропускает/даёт."""
        f = _write(tmp_path, ".py", PY_SAMPLE)
        _, symbols = parser.parse_file(f)
        names = {s["name"] for s in symbols}
        assert "fetch_data" in names       # async — function_definition в 0.25
        assert "MyClass.prop" in names     # @property — внутри decorated_definition


class TestWalkSuperset:
    """SCM-символы ⊇ walk-символы (по name+line+kind)."""

    @pytest.mark.parametrize(
        "ext,code",
        [
            (".py", PY_SAMPLE),
            (".rs", RS_SAMPLE),
            (".ts", TS_SAMPLE),
        ],
    )
    def test_scm_covers_all_walk_symbols(self, parser, tmp_path, ext, code):
        f = _write(tmp_path, ext, code)
        _, scm_symbols = parser.parse_file(f)
        _, walk_symbols = parser._parse_with_tree_sitter(f, ext)

        scm_set = {(s["name"], s["line"], s["kind"]) for s in scm_symbols}
        for s in walk_symbols:
            key = (s["name"], s["line"], s["kind"])
            assert key in scm_set, f"walk-символ {key} потерян SCM-путём"


class TestFallback:
    """Языки без tags.scm — walk-символы, без краха."""

    @pytest.mark.parametrize("ext", [".yaml", ".toml"])
    def test_no_query_falls_back_to_walk(self, parser, tmp_path, ext):
        f = _write(tmp_path, ext, "key: value\n" if ext == ".yaml" else "x = 1\n")
        assert parser._load_tags_query(ext) == ""
        chunks, symbols = parser.parse_file(f)
        assert isinstance(chunks, list)
        assert isinstance(symbols, list)

    def test_variable_import_not_symbols(self, parser, tmp_path):
        """definition.variable/import из tags.scm НЕ попадают в символы."""
        f = _write(tmp_path, ".py", "import os\nx = 1\n\ndef f():\n    return x\n")
        _, symbols = parser.parse_file(f)
        names = {s["name"] for s in symbols}
        assert "os" not in names
        assert "x" not in names
        assert "f" in names


class TestQueryCompileGuard:
    """Все вендоренные tags.scm обязаны компилироваться с установленными
    грамматиками. Падение = бамп tree-sitter-* без обновления query."""

    def test_all_vendored_queries_compile(self, parser):
        from tree_sitter import Query

        compiled = 0
        for lang_dir in QUERIES_DIR.iterdir():
            if not lang_dir.is_dir():
                continue
            scm = lang_dir / "tags.scm"
            if not scm.exists():
                continue
            # маппинг query-папки → расширения (зеркалит _load_tags_query)
            ext = _query_dir_to_ext(lang_dir.name)
            if ext not in parser.parsers:
                pytest.skip(f"парсер {ext} не установлен")
            Query(parser.parsers[ext].language, scm.read_text(encoding="utf-8"))
            compiled += 1
        # минимум 17 языков с queries вендорено
        assert compiled >= 17


def _query_dir_to_ext(lang: str) -> str:
    return {
        "python": ".py",
        "rust": ".rs",
        "typescript": ".ts",
        "javascript": ".js",
        "go": ".go",
        "java": ".java",
        "c": ".c",
        "cpp": ".cpp",
        "csharp": ".cs",
        "kotlin": ".kt",
        "swift": ".swift",
        "ruby": ".rb",
        "php": ".php",
        "scala": ".scala",
        "dart": ".dart",
        "bash": ".sh",
        "sql": ".sql",
    }.get(lang, "")
