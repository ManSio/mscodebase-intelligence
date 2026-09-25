# -*- coding: utf-8 -*-
"""E17 extraction: AST-based retrieval of function and test source.

Why this module exists
----------------------
The E17 pilot originally matched source with a naive substring search
(``f"def {name}"``). The PropertyGraph stores *qualified* names:
methods as ``Class.method`` and tests as ``Class::test_name``. Neither
ever matched ``def Class.method`` / ``def Class::test``, so every class
method got ``# FUNC NOT FOUND`` and every class-based test got
``# Test not found`` — the pilot measured hallucination, not the signal.

This module resolves names via :mod:`ast`, so both free functions and
class methods/tests are extracted correctly.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[2]

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _segment(source: str, node: ast.AST, name: str) -> str:
    """Return source text of ``node``; fall back to a line slice.

    ``errors="ignore"`` can shift byte offsets relative to the parsed text,
    so a segment that does not contain the expected name is rejected in
    favour of an explicit ``lineno``/``end_lineno`` slice.
    """
    seg = ast.get_source_segment(source, node)
    if seg is not None and name in seg:
        return seg
    lines = source.splitlines()
    start = max(getattr(node, "lineno", 1) - 1, 0)
    end = getattr(node, "end_lineno", start + 1)
    return "\n".join(lines[start:end])


def _find_in_tree(tree: ast.AST, qualified_name: str) -> Optional[ast.AST]:
    parts = qualified_name.split(".")
    method = parts[-1]
    if len(parts) == 1:
        for node in ast.walk(tree):
            if isinstance(node, _FUNC_NODES) and node.name == method:
                return node
        return None
    cls = parts[-2]
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for item in node.body:
                if isinstance(item, _FUNC_NODES) and item.name == method:
                    return item
    return None


def read_function_code(file_path: str, function_name: str) -> Optional[str]:
    """Return source of ``function_name`` from ``file_path`` or None.

    ``file_path`` may be an absolute graph path (``D:/Project/MSCodeBase/...``)
    or a path relative to the repository root. ``function_name`` may be a bare
    name (``safe_mkdir``) or qualified (``CypherLexer.tokenize``).
    """
    local = file_path.replace("D:/Project/MSCodeBase/", "").replace("\\", "/")
    path = ROOT / local
    if not path.exists():
        return None
    try:
        source = _read(path)
        tree = ast.parse(source)
    except (SyntaxError, ValueError, OSError):
        return None
    node = _find_in_tree(tree, function_name)
    if node is None:
        return None
    return _segment(source, node, function_name.split(".")[-1])


def _find_test(tree: ast.AST, test_name: str) -> Optional[ast.AST]:
    if "::" in test_name:
        cls, method = test_name.split("::", 1)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == cls:
                for item in node.body:
                    if isinstance(item, _FUNC_NODES) and item.name == method:
                        return item
        return None
    return _find_in_tree(tree, test_name)


def read_test_code(test_name: str, tests_dir: Optional[Path] = None) -> Optional[str]:
    """Return source of a test function/class-method or None.

    ``test_name`` may be ``test_foo`` or ``TestClass::test_foo``. Searches
    ``tests/`` recursively in a deterministic order.
    """
    base = tests_dir or ROOT / "tests"
    if not base.exists():
        return None
    for test_file in sorted(base.rglob("*.py")):
        try:
            source = _read(test_file)
            tree = ast.parse(source)
        except (SyntaxError, ValueError, OSError):
            continue
        node = _find_test(tree, test_name)
        if node is not None:
            return _segment(source, node, test_name.split("::")[-1])
    return None


def read_tests(tests: List[str], tests_dir: Optional[Path] = None) -> List[str]:
    """Return source bodies for the tests that could be resolved (skips misses)."""
    bodies: List[str] = []
    for name in tests:
        body = read_test_code(name, tests_dir)
        if body is not None:
            bodies.append(body)
    return bodies
