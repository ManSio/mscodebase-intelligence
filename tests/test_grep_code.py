"""grep_code: AST-aware scope, path safety, negative control.

The tool adapts coderlm's `grep?scope=code` (MIT) and fixes its per-line
shortcut: every match is judged by its own offset, so a line that contains
both code and a comment keeps the code match.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.core.di_container import ServiceCollection
from src.core.indexing.parser import CodeParser
from src.mcp.tools.grep_tool import GrepCodeTool

SOURCE = '''TOKEN = "needle"      # string literal
# needle in a comment
needle = 2            # real code
other = "needle"      # string + code needle? no, only in string
'''


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    (tmp_path / "a.py").write_text(SOURCE, encoding="utf-8")
    (tmp_path / "notes.md").write_text("needle in docs\n", encoding="utf-8")
    return tmp_path


def _run(project: Path, **kwargs) -> str:
    tool = GrepCodeTool(ServiceCollection())
    tool.resolve_parser = lambda: CodeParser()  # noqa: SLF001 — test seam
    return asyncio.run(tool.execute(project_root=str(project), **kwargs))


def test_code_scope_skips_comments_and_strings(project: Path):
    out = _run(project, pattern="needle", scope="code")
    assert "a.py:3" in out
    assert "a.py:1" not in out          # string literal
    assert "a.py:2" not in out          # comment
    assert "needle = 2" in out


def test_all_scope_sees_everything(project: Path):
    out = _run(project, pattern="needle", scope="all")
    assert "a.py:1" in out
    assert "a.py:2" in out
    assert "a.py:3" in out


def test_negative_control(project: Path):
    out = _run(project, pattern="definitely_absent_xyz", scope="all")
    assert "0 matches" in out


def test_file_filter_and_traversal(project: Path):
    out = _run(project, pattern="needle", scope="all", file_path="notes.md")
    assert "notes.md:1" in out
    assert "a.py" not in out

    denied = _run(project, pattern="needle", scope="all", file_path="../../etc/passwd")
    assert "вне проекта" in denied


def test_invalid_regex_is_reported(project: Path):
    out = _run(project, pattern="([", scope="all")
    assert "невалидный regex" in out


def test_empty_pattern_is_rejected(project: Path):
    out = _run(project, pattern="   ", scope="all")
    assert "пустой pattern" in out
