"""Positive and negative controls for `_extract_code_functions`.

Regression: a backticked error message `query dim(768)` was read as a call to a
project function `dim`, so verify_diary printed «функция dim не найдена» and the
pre-commit hook blocked every commit. Only the FIRST token of a backtick segment
may be a function name.
"""

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "verify_diary.py"
_spec = importlib.util.spec_from_file_location("verify_diary_under_test", _SCRIPT)
verify = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify)


def test_simple_call_is_extracted():
    assert verify._extract_code_functions("`set_reindexing()`") == ["set_reindexing"]


def test_call_inside_prose_backticks_is_extracted():
    assert verify._extract_code_functions("text `hybrid_search(q)` more") == ["hybrid_search"]


def test_await_and_def_prefixes_are_transparent():
    assert verify._extract_code_functions("`await fetch()`") == ["fetch"]
    assert verify._extract_code_functions("`def build()`") == ["build"]


def test_error_message_is_not_a_function_call():
    line = "**Дефект:** `lance error: query dim(768) doesn't match the column vector dim(384)`."
    assert verify._extract_code_functions(line) == []


def test_methods_are_not_extracted_as_functions():
    assert verify._extract_code_functions("`os.environ.copy()`") == []
    assert verify._extract_code_functions("`future.result()`") == []


def test_prose_with_parenthesis_outside_backticks_is_ignored():
    assert verify._extract_code_functions("sustained (prose) without backticks") == []
