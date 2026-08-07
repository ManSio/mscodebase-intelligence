"""
Тесты AutoDocUpdater — точечные замены README без коррупции.

Регрессия (2026-08-05): _update_readme коррумпировал README.md:
- `\\d+\\s*passed` ловил '20passed' внутри URL-бейджа `tests-747%20passed`
  → 'tests-747%1016 passed' (test_count двойно считал async-тесты);
- `_replace_between("tools", ...)` попадал на якорь навигации, а не на заголовок;
- `_replace_between("language", ...)` перескакивал через таблицу языков и
  заменял «13 high-level intel_* tools» на «0 ...» (lang_count всегда 0);
- `_count_tools` использовал text.count() на regex-строке как на литерале
  → всегда 0 (README «MCP Tools (0 total)»).
"""

import os
from pathlib import Path

from src.core.auto_doc_updater import AutoDocUpdater

FIXTURE_README = """\
# MSCodebase Intelligence

[![Tests](https://img.shields.io/badge/tests-747%20passed-brightgreen)](tests/)

[Features](#-features) • [Quick Start](#-quick-start) • [Tools](#mcp-tools-48-total) • [Documentation](#-documentation-map)

### Languages
| Language | Parsing | Call Graph |
|---|---|---|
| **Python** | ✅ | ✅ |
| **Rust** | ✅ | ✅ |

| 🧠 **Intelligence Layer** | 13 high-level `intel_*` tools: self-diagnostics, topology |

## 🔧 MCP Tools (48 total)
"""


def _make_tree(tmp_path: Path) -> Path:
    """Фейковый проект: README с маркерами + минимальные src/mcp и tests."""
    (tmp_path / "README.md").write_text(FIXTURE_README, encoding="utf-8")

    # src/mcp: 2 inline-декоратора + список tool_classes с 2 core-классами
    (tmp_path / "src" / "mcp" / "tools").mkdir(parents=True)
    (tmp_path / "src" / "mcp" / "server_tools.py").write_text(
        '@mcp.tool("a")\ndef a(): ...\n\n'
        '@mcp.tool("b")\ndef b(): ...\n\n'
        "tool_classes = [\n"
        "    SearchCodeTool,\n"
        "    ImpactAnalysisTool,\n"
        "]\n",
        encoding="utf-8",
    )

    # tests: 1 sync + 1 async (проверка отсутствия двойного счёта)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(
        "def test_sync():\n    pass\n\nasync def test_async():\n    pass\n",
        encoding="utf-8",
    )
    return tmp_path


def test_count_tools_sums_decorators_and_classes(tmp_path):
    """_count_tools: декораторы + core-классы из списка tool_classes."""
    root = _make_tree(tmp_path)
    assert AutoDocUpdater()._count_tools(root) == 4  # 2 декоратора + 2 класса


def test_count_tools_counts_execute_script_when_enabled(tmp_path, monkeypatch):
    """ExecuteScriptTool учитывается только при MSCODEBASE_EXECUTE_SCRIPT_ENABLED=true."""
    root = _make_tree(tmp_path)
    (tmp_path / "src" / "mcp" / "tools" / "codebase_tool.py").write_text(
        "class CodebaseTool:\n    pass\n\nclass ExecuteScriptTool:\n    pass\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("MSCODEBASE_EXECUTE_SCRIPT_ENABLED", raising=False)
    assert AutoDocUpdater()._count_tools(root) == 4  # ExecuteScriptTool скрыт

    monkeypatch.setenv("MSCODEBASE_EXECUTE_SCRIPT_ENABLED", "true")
    assert AutoDocUpdater()._count_tools(root) == 5  # ExecuteScriptTool виден


def test_count_tests_no_double_count(tmp_path):
    """async def test_ считается один раз (не как 'def test_' + 'async def test_')."""
    root = _make_tree(tmp_path)
    assert AutoDocUpdater()._count_tests(root) == 2


def test_update_readme_no_corruption(tmp_path):
    """Ключевая регрессия: README обновляется без коррупции маркеров."""
    root = _make_tree(tmp_path)
    updater = AutoDocUpdater()

    assert updater._update_readme(root) is True

    text = (tmp_path / "README.md").read_text(encoding="utf-8")
    # 1. Бейдж: целостность URL-encoded пробела, число обновлено (2 теста)
    assert "tests-2%20passed" in text
    assert "%20passed" in text  # %20 не превратился в обычный пробел
    # 2. Заголовок и якорь навигации синхронны (4 = 2 декоратора + 2 класса)
    assert "## 🔧 MCP Tools (4 total)" in text
    assert "#mcp-tools-4-total" in text
    # 3. Чужие числа не тронуты: «13 high-level» остаётся, языки не переписаны
    assert "13 high-level" in text
    assert "0 high-level" not in text
    # 4. Таблица языков не пострадала
    assert "| **Python** | ✅ | ✅ |" in text


def test_update_readme_idempotent(tmp_path):
    """Повторный прогон — без изменений (стабильность)."""
    root = _make_tree(tmp_path)
    updater = AutoDocUpdater()

    assert updater._update_readme(root) is True
    assert updater._update_readme(root) is False

    text = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "tests-2%20passed" in text
    assert "## 🔧 MCP Tools (4 total)" in text


def test_count_tools_real_project_guard():
    """Реальный проект: счётчик не равен 0 (баг text.count → вернул 48)."""
    root = Path(__file__).resolve().parent.parent
    tools = AutoDocUpdater()._count_tools(root)
    assert tools >= 44, f"_count_tools вернул {tools} — снова баг подсчёта?"
    if os.environ.get("MSCODEBASE_EXECUTE_SCRIPT_ENABLED", "false").lower() != "true":
        assert tools == 57, f"ожидалось 57 (README-контракт), получено {tools}"
