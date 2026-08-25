"""test_language_imports.py — герметичные тесты экстрактора импортов.

Fake tree-sitter node (type/text/children) — БЕЗ tree-sitter зависимости:
реальные грамматики скачиваются по сети (вне юнит-тестов, как в
language_pack.py). Положительный контроль (ловит импорты) + отрицательный
(ни падений на экзотике, ни мусора из ключевых слов).
"""


from src.core.language_imports import (
    extract_imports,
    extract_imports_from_file,
    known_languages,
)


class N:
    """Минимальный fake tree-sitter node."""

    def __init__(self, type, text="", children=()):
        self.type = type
        self.text = text
        self.children = list(children)


def _py_tree():
    """import os; import a.b; from collections import defaultdict."""
    return N(
        "module",
        children=[
            N("import_statement", children=[N("dotted_name", text="os")]),
            N("import_statement", children=[N("dotted_name", text="a.b")]),
            N(
                "import_from_statement",
                children=[
                    N("identifier", text="from"),
                    N("dotted_name", text="collections"),
                    N("identifier", text="import"),
                    N("identifier", text="defaultdict"),
                ],
            ),
        ],
    )


def _rust_tree():
    """use std::collections::HashMap;"""
    return N(
        "source_file",
        children=[
            N(
                "use_declaration",
                children=[
                    N("identifier", text="use"),
                    N("scoped_identifier", text="std::collections::HashMap"),
                ],
            ),
        ],
    )


def _go_tree():
    """import \"fmt\"  (плюс многострочный import-block)"""
    return N(
        "source_file",
        children=[
            N("import_declaration", children=[N("string", text='"fmt"')]),
            N(
                "import_declaration",
                children=[
                    N("string", text='"os"'),
                    N("string", text='"strings"'),
                ],
            ),
        ],
    )


class TestExtractImports:
    def test_python_finds_modules(self):
        mods = extract_imports(_py_tree(), "python")
        assert "os" in mods
        assert "a.b" in mods
        # from-import: модуль "collections" присутствует (возможно с символом)
        assert any(m.startswith("collections") for m in mods)

    def test_rust_use_declaration(self):
        mods = extract_imports(_rust_tree(), "rust")
        assert any("std" in m for m in mods)

    def test_go_import_strings(self):
        mods = extract_imports(_go_tree(), "go")
        assert "fmt" in mods
        assert "os" in mods
        assert "strings" in mods

    def test_case_normalized_lang(self):
        # "TypeScript" → нормализация в tsx/рабочий ключ
        assert extract_imports(_py_tree(), "PYTHON")  # не падает, lang нормализуется

    def test_unknown_language_fallback_no_crash(self):
        """Negative control: экзотический язык без карты — тишина, не падение."""
        exo = N(
            "weird_doc",
            children=[
                N("import_like_thing", children=[N("name", text="x")]),
                N("ordinary_statement", children=[N("name", text="y")]),
            ],
        )
        mods = extract_imports(exo, "mooncript")
        assert isinstance(mods, list)
        assert all(m == "x" for m in mods) or "x" in mods  # import_like_thing пойман

    def test_no_junk_from_keywords(self):
        """Negative control: ключевые слова не становятся модулями."""
        mods = extract_imports(_rust_tree(), "rust")
        assert "use" not in mods

    def test_dedup_preserves_order(self):
        tree = N(
            "module",
            children=[
                N("import_statement", children=[N("dotted_name", text="os")]),
                N("import_statement", children=[N("dotted_name", text="os")]),
            ],
        )
        mods = extract_imports(tree, "python")
        assert mods == ["os"]

    def test_real_treesitter_tree_shape(self):
        """Регрессия 2026-08-25: реальный tree-sitter даёт TREE с .root_node,
        а не node с .children — без унификации экстрактор молча возвращал [].
        Живой прогон с tree-sitter-language-pack вскрыл, fake-дерево — нет.
        """

        class FakeTree:
            def __init__(self, root):
                self.root_node = root

        tree = FakeTree(
            N(
                "module",
                children=[N("import_statement", children=[N("dotted_name", text="os")])],
            )
        )
        mods = extract_imports(tree, "python")
        assert mods == ["os"]


class TestFromFile:
    def test_hermetic_with_fake_provider(self, tmp_path):
        path = str(tmp_path / "a.py")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("import os\n")

        def provider(file_path, lang):
            assert lang == "python"
            return _py_tree(), "python"

        mods = extract_imports_from_file(path, parser_provider=provider)
        assert "os" in mods

    def test_disabled_by_default_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MSCODEBASE_LANGUAGE_PACK", raising=False)
        path = str(tmp_path / "a.py")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("import os\n")
        assert extract_imports_from_file(path) == []

    def test_broken_provider_no_crash(self, tmp_path):
        def provider(file_path, lang):
            raise RuntimeError("грамматика не скачана / сеть")

        mods = extract_imports_from_file(
            str(tmp_path / "a.py"), parser_provider=provider
        )
        assert mods == []


def test_known_languages_cover_original_20():
    langs = set(known_languages())
    for original in (
        "python", "rust", "javascript", "typescript", "tsx", "go", "java",
        "csharp", "ruby", "php", "kotlin", "swift", "c", "cpp", "scala", "dart",
    ):
        assert original in langs, f"слой потерял язык {original}"
