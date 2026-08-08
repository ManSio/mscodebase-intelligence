"""WS7: Tool registration guard — тулы регистрируются только статически.

Tool Poisoning (arXiv 2603.22489): злоумышленник внедряет вредоносные
инструменты/описания через динамическую регистрацию. Guard: имена тулов в
server_tools.py / tools_reg.py обязаны быть строковыми литералами в
декораторах @mcp.tool(...) / @mcp_app.tool(...) — никаких runtime-имён,
eval/exec, импорта регистрации из контента репозитория.
"""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
REGISTRATION_FILES = [
    SRC / "mcp" / "server_tools.py",
    SRC / "core" / "intelligence" / "tools_reg.py",
]


def _find_tool_decorators(tree: ast.AST):
    """Ищет (func, arg) для @<module>.tool("<имя>") декораторов."""
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            # @mcp.tool("name") / @mcp_app.tool("name")
            if (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and dec.func.attr == "tool"
                and dec.args
            ):
                yield node, dec.args[0]


@pytest.mark.parametrize("path", [str(p) for p in REGISTRATION_FILES])
def test_tool_names_are_string_literals(path):
    """Имя каждого тула — строковый литерал, не переменная/вызов/expr."""
    source = Path(path).read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(source)
    found = list(_find_tool_decorators(tree))
    assert found, f"не найдено ни одной регистрации @*.tool(...) в {path}"
    for _func, name_arg in found:
        assert isinstance(name_arg, ast.Constant) and isinstance(
            name_arg.value, str
        ), f"tool name не литерал в {path}: {ast.dump(name_arg)}"


@pytest.mark.parametrize("path", [str(p) for p in REGISTRATION_FILES])
def test_no_dynamic_code_in_registration_files(path):
    """Запрещены eval/exec/compile и чтение путей репозитория при регистрации."""
    source = Path(path).read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(source)
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in ("eval", "exec", "compile", "globals"):
                bad.append(f"{node.func.id}@{getattr(node, 'lineno', '?')}")
    assert not bad, f"динамическое исполнение в регистрации: {bad}"


def test_registration_files_do_not_read_indexed_project():
    """Регистрация не читает файлы индексируемого проекта (динамические тулы)."""
    path = SRC / "mcp" / "server_tools.py"
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    reg = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "register_all_tools"),
        None,
    )
    assert reg is not None, "register_all_tools не найден"
    banned = {"resolve_project_root", "read_text", "read_bytes", "glob", "iterdir"}
    hits = []
    for node in ast.walk(reg):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
            if name in banned:
                hits.append(f"{name}@{node.lineno}")
    assert not hits, f"регистрация читает проект: {hits}"
