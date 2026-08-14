"""Регрессия 2026-08-14: MCP stale_detector игнорировал <!-- stale-ignore -->.

Дублированная реализация в doc_tools.py давала 11 ложных дрейфов (AGENTS.md
v3.2.0-маркеры, TELEMETRY 3.2.1) при 0 у канонического чекера. Фикс:
делегирование tools/stale_detector/stale_check.py (single source of truth).

Известный остаток (не чиним здесь): severity_overrides матчатся forward-slash
паттерном, а rel на Windows содержит backslash → docs/ru|zh НЕ получают warn
на Windows (на POSIX работают). Зафиксировано в KNOWN_ISSUES.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _tool():
    from src.mcp.tools.doc_tools import StaleDetectorTool

    return StaleDetectorTool.__new__(StaleDetectorTool)


def test_stale_tool_respects_stale_ignore(tmp_path):
    """<!-- stale-ignore --> обязан исключать строку из дрейфа (регрессия)."""
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "3.4.0"\n', encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "historical.md").write_text(
        "<!-- stale-ignore -->\nТекущая: v3.2.0 (исторический маркер)\n<!-- stale-ignore -->\n",
        encoding="utf-8",
    )
    (docs / "real.md").write_text("Реальная версия: v3.2.0\n", encoding="utf-8")

    results = _tool()._scan_docs(tmp_path, "3.4.0", {})
    paths = [Path(r["path"]) for r in results]
    assert not any(p == Path("docs/historical.md") for p in paths), "stale-ignore не сработал"
    assert any(p == Path("docs/real.md") for p in paths), "реальный дрейф не найден"


def test_stale_tool_uses_canonical_defaults(tmp_path):
    """Пустой config → канонические defaults (exclude_dirs: .git, node_modules...)."""
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "3.4.0"\n', encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "doc.md").write_text("Версия: v3.2.0\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "real.md").write_text("Версия: v3.2.0\n", encoding="utf-8")

    results = _tool()._scan_docs(tmp_path, "3.4.0", {})
    paths = [Path(r["path"]) for r in results]
    assert not any(".git" in p.parts for p in paths), ".git не исключён (defaults сломаны)"
    assert any(p == Path("docs/real.md") for p in paths)
