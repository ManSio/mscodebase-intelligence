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

    def test_unknown_language_fallback_gated_by_flag(self, monkeypatch):
        """Fallback-режим 2 МОЛЧИТ при выключенном MSCODEBASE_LANGUAGE_PACK.

        Негативный тест требования «fallback только за флагом»: без флага
        экзотический язык без карты даёт пустой результат, не падение.
        """
        monkeypatch.delenv("MSCODEBASE_LANGUAGE_PACK", raising=False)
        exo = N(
            "weird_doc",
            children=[
                N("import_like_thing", children=[N("name", text="x")]),
                N("ordinary_statement", children=[N("name", text="y")]),
            ],
        )
        assert extract_imports(exo, "mooncript") == []

    def test_unknown_language_fallback_active_with_flag(self, monkeypatch):
        """Позитивный контроль: тот же язык с флагом — best-effort находит x."""
        monkeypatch.setenv("MSCODEBASE_LANGUAGE_PACK", "true")
        exo = N(
            "weird_doc",
            children=[
                N("import_like_thing", children=[N("name", text="x")]),
                N("ordinary_statement", children=[N("name", text="y")]),
            ],
        )
        mods = extract_imports(exo, "mooncript")
        assert isinstance(mods, list)
        assert "x" in mods  # import_like_thing пойман fallback-ом

    def test_mapped_lang_never_falls_back_even_with_flag(self, monkeypatch):
        """Негативный тест: язык из карты использует ТОЧНЫЙ режим даже с флагом.

        'useless_thing' содержит 'use' — по fallback-подстроке подошёл бы,
        но rust есть в карте: посторонние типы не матчатся.
        """
        monkeypatch.setenv("MSCODEBASE_LANGUAGE_PACK", "true")
        tree = N(
            "source_file",
            children=[
                N(
                    "use_declaration",
                    children=[N("scoped_identifier", text="std::io")],
                ),
                N("useless_thing", children=[N("name", text="junk")]),
            ],
        )
        mods = extract_imports(tree, "rust")
        assert mods == ["std::io"]
        assert "junk" not in mods

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


class TestMapConsistency:
    """Единый источник истины (B4): LANGUAGE_IMPORT_NODES — производная
    CodeParser.IMPORT_NODE_MAP. Падает при любом расхождении двух карт:
    ручная правка производной, новый ext без маппинга, смена деривации.
    """

    def test_derived_from_parser_map(self):
        from src.core.indexing.parser import CodeParser
        from src.core.language_imports import _EXT_TO_LANG, LANGUAGE_IMPORT_NODES

        merged: dict = {}
        for ext, types in CodeParser.IMPORT_NODE_MAP.items():
            assert ext in _EXT_TO_LANG, (
                f"ext {ext} из IMPORT_NODE_MAP без маппинга _EXT_TO_LANG"
            )
            merged.setdefault(_EXT_TO_LANG[ext], set()).update(types)
        assert {k: set(v) for k, v in LANGUAGE_IMPORT_NODES.items()} == merged

    def test_no_literal_legacy_entries(self):
        """Исторические неверные имена старой карты не должны вернуться
        (докстринг language_imports: карта однажды была фактически неверной)."""
        from src.core.language_imports import LANGUAGE_IMPORT_NODES

        assert LANGUAGE_IMPORT_NODES["kotlin"] == ("import",)
        assert "import_header" not in LANGUAGE_IMPORT_NODES["kotlin"]
        assert "library_import" in LANGUAGE_IMPORT_NODES["dart"]
        assert "import_directive" not in LANGUAGE_IMPORT_NODES["dart"]
        assert "require_expression" in LANGUAGE_IMPORT_NODES["php"]
        assert "export_statement" not in LANGUAGE_IMPORT_NODES["typescript"]

    def test_known_languages_matches_map(self):
        from src.core.language_imports import LANGUAGE_IMPORT_NODES

        assert known_languages() == sorted(LANGUAGE_IMPORT_NODES)
