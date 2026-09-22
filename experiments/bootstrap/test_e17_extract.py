# -*- coding: utf-8 -*-
"""Regression tests for E17 AST extraction.

Guards the bug where qualified names ("Class.method", "Class::test") never
matched the naive ``f"def {name}"`` search, yielding "# FUNC NOT FOUND" /
"# Test not found" for every class method.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from e17_extract import read_function_code, read_test_code, read_tests  # noqa: E402

LEXER = "D:/Project/MSCodeBase/src/core/search/cypher_lexer.py"
PATHS = "D:/Project/MSCodeBase/src/core/artifact_paths.py"


def test_method_extraction_returns_real_body():
    code = read_function_code(LEXER, "CypherLexer.tokenize")
    assert code is not None
    assert "def tokenize" in code
    assert "FUNC NOT FOUND" not in code


def test_free_function_extraction():
    code = read_function_code(PATHS, "_ensure_data_root")
    assert code is not None
    assert "def _ensure_data_root" in code


def test_missing_function_returns_none():
    assert read_function_code(LEXER, "CypherLexer.does_not_exist") is None


def test_missing_file_returns_none():
    assert read_function_code("D:/Project/MSCodeBase/src/nope.py", "x") is None


def test_class_method_test_extraction():
    body = read_test_code("TestCypherLexer::test_tokenize_simple_match")
    assert body is not None
    assert "def test_tokenize_simple_match" in body
    assert "Test not found" not in body


def test_plain_test_extraction():
    body = read_test_code("test_store_record_get_query")
    assert body is not None
    assert "def test_store_record_get_query" in body


def test_missing_test_returns_none():
    assert read_test_code("TestCypherLexer::nope_not_here") is None


def test_read_tests_skips_unresolved():
    bodies = read_tests(["TestCypherLexer::test_tokenize_simple_match", "no_such_test"])
    assert len(bodies) == 1


def test_syntax_error_file_returns_none(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("def broken(:\n", encoding="utf-8")
    assert read_function_code(str(bad), "broken") is None


def test_duplicate_method_names_resolve_by_class(tmp_path):
    mod = tmp_path / "dup.py"
    mod.write_text(
        "class A:\n"
        "    def foo(self):\n"
        "        return 'AAA'\n\n"
        "class B:\n"
        "    def foo(self):\n"
        "        return 'BBB'\n",
        encoding="utf-8",
    )
    code = read_function_code(str(mod), "B.foo")
    assert code is not None
    assert "'BBB'" in code
    assert "'AAA'" not in code


def test_async_function_extraction(tmp_path):
    mod = tmp_path / "a.py"
    mod.write_text("async def go():\n    return 1\n", encoding="utf-8")
    code = read_function_code(str(mod), "go")
    assert code is not None
    assert "async def go" in code


def test_name_only_in_comment_is_not_matched(tmp_path):
    mod = tmp_path / "c.py"
    mod.write_text(
        "# def ghost():\nSTRING = 'def ghost()'\n",
        encoding="utf-8",
    )
    assert read_function_code(str(mod), "ghost") is None


def test_nested_function_extraction(tmp_path):
    mod = tmp_path / "n.py"
    mod.write_text(
        "def outer():\n"
        "    def inner():\n"
        "        return 'INNER'\n"
        "    return inner\n",
        encoding="utf-8",
    )
    code = read_function_code(str(mod), "inner")
    assert code is not None
    assert "'INNER'" in code


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
