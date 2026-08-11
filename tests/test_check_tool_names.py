"""
check_tool_names.py — negative control: гейт обязан падать на мёртвом имени
и проходить на чистом наборе (правило Тома, KNOWN_ISSUES#2026-08-12:
«guard структурно неспособен упасть» закрыт отрицательным контролем).
"""

import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_tool_names.py"


def _make_project(tmp_path: Path, doc_content: str) -> Path:
    """Собирает минимальный проект: 2 reg-intel + 1 inline-intel + AGENTS + doc."""
    root = tmp_path / "proj"
    tools_reg = root / "src" / "core" / "intelligence"
    tools_reg.mkdir(parents=True)
    (root / "src" / "mcp").mkdir(parents=True)

    (tools_reg / "tools_reg.py").write_text(
        '"""doc"""\n'
        '@mcp_app.tool("intel_one")\n'
        'async def one(): ...\n'
        '@mcp_app.tool("intel_two")\n'
        'async def two(): ...\n',
        encoding="utf-8",
    )
    (root / "src" / "mcp" / "server_tools.py").write_text(
        '"""doc"""\n'
        '@mcp.tool("intel_inline")\n'
        'async def il(): ...\n',
        encoding="utf-8",
    )
    (root / "AGENTS.md").write_text(
        "### A. Intel Intelligence Layer (2 tools)\n"
        "`intel_one`, `intel_two`.\n"
        "Inline/Diagnostic (12): `intel_inline`.\n",
        encoding="utf-8",
    )
    (root / "docs" / "en").mkdir(parents=True)
    (root / "docs" / "en" / "ARCHITECTURE.md").write_text(doc_content, encoding="utf-8")
    return root


def _run(root: Path) -> int:
    env = dict(os.environ)
    env["MSCODEBASE_PROJECT_ROOT"] = str(root)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    return proc.returncode


def test_clean_docs_pass(tmp_path: Path):
    """Контрольная группа: корректные доки → exit 0."""
    root = _make_project(tmp_path, "Use `intel_one` for status.\n")
    assert _run(root) == 0


def test_dead_name_fails(tmp_path: Path):
    """Мёртвое имя (никогда не было тулом) → exit 1."""
    root = _make_project(tmp_path, "Use `get_variable_flow` for data flow.\n")
    assert _run(root) == 1


def test_unknown_intel_fails(tmp_path: Path):
    """Несуществующий intel_* → exit 1."""
    root = _make_project(tmp_path, "Use `intel_ghost` for magic.\n")
    assert _run(root) == 1


def test_header_mismatch_fails(tmp_path: Path):
    """Заголовок (N tools) ≠ реальному → exit 1."""
    root = _make_project(tmp_path, "ok\n")
    agents = root / "AGENTS.md"
    agents.write_text(
        agents.read_text(encoding="utf-8").replace("(2 tools)", "(3 tools)"),
        encoding="utf-8",
    )
    assert _run(root) == 1


def test_missing_real_tool_fails(tmp_path: Path):
    """Реальный tools_reg-тул не упомянут в AGENTS.md → exit 1."""
    root = _make_project(tmp_path, "ok\n")
    agents = root / "AGENTS.md"
    agents.write_text(
        agents.read_text(encoding="utf-8").replace("`intel_one`, `intel_two`", "`intel_one`"),
        encoding="utf-8",
    )
    assert _run(root) == 1


def test_ledger_excluded(tmp_path: Path):
    """Леджер (исторический) с мёртвым именем — вне scope → exit 0."""
    root = _make_project(tmp_path, "ok\n")
    (root / "KNOWN_ISSUES.md").write_text(
        "## old entry\nget_variable_flow was renamed\n", encoding="utf-8"
    )
    assert _run(root) == 0
