#!/usr/bin/env python3
"""
check_tool_names.py — semantic-гейт: имена MCP-тулов в доках обязаны существовать.

Закрывает класс «документация не ровна коду» (KNOWN_ISSUES#2026-08-12):
stale_detector сверяет только version-строки; имена тулов в доках не
проверялись → AGENTS.md перечислял несуществующие тулы (get_variable_flow,
get_related_files, run_health_check, predict_eta — 0 файлов в src/).

Проверки (инструкционные доки: корень + docs/{en,ru,zh,adr}, БЕЗ
archive/generated/research/blog/ISSUES/CHANGELOG и БЕЗ леджеров
AGENT_DIARY/KNOWN_ISSUES/EXPERIMENTS_LOG/WISDOM — они исторические):
1. Чёрный список «никогда-не-тулы» — любое упоминание = error.
2. Deprecated-имена (smart_search/deep_search/context_search) — упоминание
   допустимо ТОЛЬКО с маркером "deprecated" в той же строке.
3. intel_*: каждое упоминание в доках обязано существовать в реестре
   (tools_reg.py + inline server_tools.py); каждый реальный tools_reg-тул
   обязано быть упомянуто в AGENTS.md; заголовок «Intel Intelligence Layer
   (N tools)» в AGENTS.md обязан совпадать с N=tools_reg.

Exit: 0 = чисто; 1 = найдены мёртвые имена / расхождения.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# MSCODEBASE_PROJECT_ROOT — для изолированных тестов (иначе корень скрипта).
PROJECT_ROOT = Path(
    os.environ.get("MSCODEBASE_PROJECT_ROOT", Path(__file__).resolve().parent.parent)
).resolve()
TOOLS_REG = PROJECT_ROOT / "src" / "core" / "intelligence" / "tools_reg.py"
AGENTS = PROJECT_ROOT / "AGENTS.md"

# ─── Конфиг ──────────────────────────────────────────────────

# Имена, которые НИКОГДА не были MCP-тулами (grep-0 в src/mcp/, src/core/).
DEAD_NAMES = {
    "get_variable_flow",  # было: graph_query(action="flow") (2026-08-12)
    "get_related_files",  # было: graph_query(action="related")
    "run_health_check",   # никогда не существовало
    "predict_eta",        # никогда не существовало (метод-хелпер ETA, не тул)
}

# Реальные deprecated-тулы: упоминание допустимо только с маркером.
DEPRECATED_NAMES = {"smart_search", "deep_search", "context_search"}

# Леджеры исторические (описывают прошлые имена/состояния) — вне scope.
LEDGER_FILES = {"AGENT_DIARY.md", "KNOWN_ISSUES.md", "EXPERIMENTS_LOG.md", "WISDOM.md", "ISSUE.md"}

# Каталоги/файлы вне scope: исторические/сгенерированные/архивные.
EXCLUDE_DIRS = {"archive", "generated", "research", "blog", "ISSUES", "__pycache__"}
EXCLUDE_FILES = {"CHANGELOG.md"} | LEDGER_FILES

# Инструкционные доки: корень + docs/{en,ru,zh,adr}.
INSTRUCTION_GLOBS = (
    "*.md",
    "docs/en/*.md",
    "docs/ru/*.md",
    "docs/zh/*.md",
    "docs/adr/*.md",
)


def _collect_docs() -> list[Path]:
    docs: list[Path] = []
    for pattern in INSTRUCTION_GLOBS:
        for path in PROJECT_ROOT.glob(pattern):
            if any(part in EXCLUDE_DIRS for part in path.parts):
                continue
            if path.name in EXCLUDE_FILES:
                continue
            docs.append(path)
    return sorted(set(docs))


def _real_intel_names() -> tuple[set[str], set[str]]:
    """(tools_reg_intel, inline_intel) из реального кода.

    tools_reg: @mcp_app.tool("intel_...") в tools_reg.py (14).
    inline:    @mcp.tool("intel_...") в server_tools.py (4: intel_get_project_context,
               intel_explain_project_state, intel_tool_health, intel_execution_timeline).
    """
    tools_reg_text = TOOLS_REG.read_text(encoding="utf-8")
    reg = set(re.findall(r'@mcp_app\.tool\("(intel_[a-z_]+)"', tools_reg_text))
    inline_text = (PROJECT_ROOT / "src" / "mcp" / "server_tools.py").read_text(encoding="utf-8")
    inline = set(re.findall(r'@mcp\.tool\("(intel_[a-z_]+)"', inline_text))
    return reg, inline


def _mention_docs(docs: list[Path], name: str) -> list[tuple[Path, int]]:
    """Все (файл, строка) с упоминанием имени."""
    hits = []
    for doc in docs:
        for i, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(rf"\b{re.escape(name)}\b", line):
                hits.append((doc, i))
    return hits


def main() -> int:
    errors: list[str] = []
    docs = _collect_docs()
    reg_intel, inline_intel = _real_intel_names()
    all_intel = reg_intel | inline_intel

    if not all_intel:
        errors.append(f"❌ tools_reg.py/server_tools.py не найдены или пусты: {TOOLS_REG}")
        return 1

    # ─── 1. Мёртвые имена ───────────────────────────────────
    for name in sorted(DEAD_NAMES):
        for doc, line in _mention_docs(docs, name):
            errors.append(f"❌ {doc.relative_to(PROJECT_ROOT)}:{line} — мёртвое имя «{name}»")

    # ─── 2. Deprecated-имена требуют маркера ────────────────
    for name in sorted(DEPRECATED_NAMES):
        for doc, line_no in _mention_docs(docs, name):
            line = doc.read_text(encoding="utf-8").splitlines()[line_no - 1]
            if "deprecated" not in line.lower():
                errors.append(
                    f"❌ {doc.relative_to(PROJECT_ROOT)}:{line_no} — «{name}» "
                    f"без маркера deprecated"
                )

    # ─── 3a. intel_* упоминания обязаны существовать ────────
    # «intel_layer» — класс ProjectIntelligenceLayer (не тул), исключается.
    intel_mention = re.compile(r"\b(intel_(?!layer)[a-z_]+)\b")
    mentioned: set[str] = set()
    for doc in docs:
        text = doc.read_text(encoding="utf-8")
        for m in intel_mention.finditer(text):
            mentioned.add(m.group(1))
            if m.group(1) not in all_intel:
                line = text[: m.start()].count("\n") + 1
                errors.append(
                    f"❌ {doc.relative_to(PROJECT_ROOT)}:{line} — "
                    f"несуществующий тул «{m.group(1)}» (нет в tools_reg.py/inline)"
                )

    # ─── 3b. Полнота: каждый реальный tools_reg intel_* упомянут в AGENTS.md ──
    agents_text = AGENTS.read_text(encoding="utf-8")
    agents_intel = set(intel_mention.findall(agents_text))
    for name in sorted(reg_intel - agents_intel):
        errors.append(f"❌ AGENTS.md — реальный тул «{name}» не упомянут (секция A)")

    # ─── 3c. Заголовок секции A: (N tools) == len(reg_intel) ─────
    m = re.search(r"Intel Intelligence Layer \((\d+) tools\)", agents_text)
    if m and int(m.group(1)) != len(reg_intel):
        errors.append(
            f"❌ AGENTS.md — заголовок секции A: ({m.group(1)} tools), "
            f"реально tools_reg {len(reg_intel)}"
        )

    # ─── Вывод ───────────────────────────────────────────────
    if errors:
        print("🚨 CHECK TOOL NAMES — doc-vs-code drift:")
        for err in errors:
            print(f"  {err}")
        print(f"❌ Итог: {len(errors)} ошибок. Доки ссылаются на несуществующие тулы.")
        return 1

    print(
        f"✅ CHECK TOOL NAMES: {len(docs)} доков, intel_* = {len(all_intel)} "
        f"(tools_reg {len(reg_intel)} + inline {len(inline_intel)}), мёртвых имён 0"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
