#!/usr/bin/env python
"""
Architecture Linter — автоматическая проверка архитектурных инвариантов.

Проверяет:
  1. Core слой (src/core/) не импортирует src.mcp
  2. Tools не импортируют Registry/Bridge/Passport напрямую
  3. Нет циклических зависимостей между core-модулями
  4. Нет ссылок на старые имена (get_project_context без intel_, .codebase_index без es)

Использование:
    python scripts/architecture_linter.py

Exit code:
    0 — все инварианты соблюдены
    1 — найдены нарушения
"""

import ast
import sys
from pathlib import Path

# ENCODING SAFETY (Windows, §5.9): вывод нарушений содержит юникод (❌) —
# cp1251-консоль падала с UnicodeEncodeError до вывода первого нарушения,
# линтер молча работал «вхолостую» на Windows (ARCLUX audit 2026-08-17).
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

REPO = Path(__file__).resolve().parent.parent  # D:\Project\MSCodeBase

# ══════════════════════════════════════════════════════════════
# Инвариант 1: Core не импортирует MCP
# ══════════════════════════════════════════════════════════════

_FORBIDDEN_MCP_IMPORTS = {
    "src.mcp",
    "src.mcp.server",
    "src.mcp.tools",
    "mcp.server",
    "mcp.tools",
}

# Core не импортирует MCP вообще (ARCH-03 закрыт 2026-08-05/2026-08-17):
# resolve_project_root — src/core/project_resolution.py; progress_state —
# src/core/progress_state.py; _grep_fallback — src/core/utils/grep_fallback.py
# (перенесён из mcp.tools.search_tools 2026-08-17, ARCLUX audit).
# Stale-ключи удалены: intelligence_layer (модуль не существует),
# intelligence.layer (больше не импортирует mcp).
_ALLOWED_CORE_MCP_IMPORTS: dict[str, list[str]] = {}


def _check_core_no_mcp_imports() -> list[str]:
    """Проверяет, что core-файлы не импортируют MCP."""
    errors = []
    core_dir = REPO / "src" / "core"
    for py_file in core_dir.rglob("*.py"):
        if py_file.name.startswith("__"):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError as e:
            errors.append(f"[SYNTAX] {py_file.relative_to(REPO)}: {e}")
            continue

        for node in ast.walk(tree):
            mod_key = str(py_file.relative_to(REPO).with_suffix('')).replace(chr(92), '/').replace('/', '.')
            allowed = _ALLOWED_CORE_MCP_IMPORTS.get(mod_key, [])
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for forbidden in _FORBIDDEN_MCP_IMPORTS:
                        if alias.name.startswith(forbidden):
                            if any(alias.name.startswith(a) for a in allowed):
                                continue
                            rel = py_file.relative_to(REPO)
                            errors.append(
                                f"[CORE_MCP] {rel}:{node.lineno} импортирует {alias.name!r} (запрещено)"
                            )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    for forbidden in _FORBIDDEN_MCP_IMPORTS:
                        if node.module.startswith(forbidden):
                            if any(node.module.startswith(a) for a in allowed):
                                continue
                            rel = py_file.relative_to(REPO)
                            names = [a.name for a in node.names]
                            errors.append(
                                f"[CORE_MCP] {rel}:{node.lineno} "
                                f"from {node.module} import {', '.join(names)} (запрещено)"
                            )
    return errors


# ══════════════════════════════════════════════════════════════
# Инвариант 2: Tools не импортируют Registry/Bridge/Passport напрямую
# (кроме base.py, который их определяет)
# ══════════════════════════════════════════════════════════════

_FORBIDDEN_TOOL_IMPORTS = {
    "src.core.project_indexer_registry",
    "src.core.lsp_project_bridge",
    "src.mcp.server",
}


def _check_tools_no_direct_registry() -> list[str]:
    """Проверяет, что tools не импортируют Registry/Bridge напрямую."""
    errors = []
    tools_dir = REPO / "src" / "mcp" / "tools"
    for py_file in tools_dir.rglob("*.py"):
        if py_file.name in ("__init__.py", "base.py"):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for forbidden in _FORBIDDEN_TOOL_IMPORTS:
                        if alias.name.startswith(forbidden):
                            rel = py_file.relative_to(REPO)
                            errors.append(
                                f"[TOOL_REGISTRY] {rel}:{node.lineno} "
                                f"импортирует {alias.name!r} (через Coordinator!)"
                            )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    for forbidden in _FORBIDDEN_TOOL_IMPORTS:
                        if node.module.startswith(forbidden):
                            rel = py_file.relative_to(REPO)
                            names = [a.name for a in node.names]
                            errors.append(
                                f"[TOOL_REGISTRY] {rel}:{node.lineno} "
                                f"from {node.module} import {', '.join(names)} (через Coordinator!)"
                            )
    return errors


# ══════════════════════════════════════════════════════════════
# Инвариант 3: Нет ссылок на старые имена в коде
# ══════════════════════════════════════════════════════════════

# Backward-compat файлы, где .codebase_index (без es) и get_project_context разрешены
_ALLOWED_STALE = {
    ".codebase_index": [
        "src/core/system_artifacts.py",      # backward compat
        ".gitignore",                        # backward compat
        "docs/architecture.md",              # historical
        "docs/architecture-layers.md",       # historical
        "src/core/indexing/symbol_index.py", # backward compat — обе директории
        "src/core/search/graph_adapter.py",  # skip-dir — обе директории
    ],
    "get_project_context(": [
        "CHANGELOG.md",              # historical
        "docs/architecture.md",     # historical
        "src/mcp/server.py",        # old name in comments/docs
    ],
}

# Каждый кортеж: (подстрока, описание, исключаемые файлы, ignore_substr).
# ignore_substr: если он есть в той же строке, что и подстрока — НЕ нарушение.
# get_project_context(: новое имя intel_get_project_context содержит старое как
# подстроку → без ignore_substr каждое упоминание нового имени давало ложное
# срабатывание (server_tools.py, project_context.py, 2026-08-24).
_STALE_PATTERNS = [
    (".codebase_index", "старое имя директории (без 'es')", [
        "docs/architecture.md",
        ".gitignore",
        "src/core/system_artifacts.py",      # backward compat — разрешено
        "src/core/indexing/symbol_index.py", # backward compat — обе директории
        "src/core/search/graph_adapter.py",  # skip-dir — обе директории
    ], None),
    ("get_project_context(", "старое имя tool (без intel_)", [
        "CHANGELOG.md",  # историческая запись
        "docs/architecture.md",
        "src/mcp/server.py",  # old name in comments/docs
    ], "intel_get_project_context"),
]


def _check_stale_references() -> list[str]:
    """Проверяет, что нет ссылок на старые имена в исходном коде."""
    errors = []
    for py_file in (REPO / "src").rglob("*.py"):
        if py_file.name.startswith("__"):
            continue
        content = py_file.read_text(encoding="utf-8")
        rel = py_file.relative_to(REPO)
        for pattern, description, exceptions, ignore_substr in _STALE_PATTERNS:
            # Нормализуем оба пути для сравнения (Windows \\ vs Unix /)
            rel_str = str(rel).replace(chr(92), "/")
            if any(exc.replace(chr(92), "/") == rel_str for exc in exceptions):
                continue
            # Проверяем _ALLOWED_STALE (backward compat)
            allowed_for_pattern = _ALLOWED_STALE.get(pattern, [])
            if any(allowed.replace(chr(92), "/") == rel_str for allowed in allowed_for_pattern):
                continue
            if pattern in content:
                for lineno, line in enumerate(content.splitlines(), 1):
                    if pattern in line:
                        # intel_get_project_context содержит get_project_context(
                        # как подстроку — новое имя нарушением не является
                        if ignore_substr and ignore_substr in line:
                            continue
                        errors.append(
                            f"[STALE] {rel}:{lineno} содержит {pattern!r} ({description})"
                        )
                        break
    return errors


# ══════════════════════════════════════════════════════════════
# Инвариант 3: Нет циклических зависимостей между core-модулями
# ══════════════════════════════════════════════════════════════

# Осознанный техдолг: error_handler ⇄ task_queue. Обе стороны импортируют друг
# друга ТОЛЬКО lazy-импортами внутри функций под try/except
# (error_handler.py:290 `from src.core.task_queue import idle_tick`;
# task_queue.py:414 `from src.core.error_handler import _LAST_CALL_AT`) —
# цикл разрывается в рантайме, при загрузке модулей не выполняется.
# Удалить из исключений после рефакторинга (см. KNOWN_ISSUES 2026-08-24).
_ALLOWED_CORE_CYCLES: set[frozenset[str]] = {
    frozenset({"src.core.error_handler", "src.core.task_queue"}),
}


def _module_dotted(path: Path) -> str:
    """'src/core/graph.py' → 'src.core.graph'."""
    rel = path.relative_to(REPO)
    return str(rel.with_suffix("")).replace(chr(92), "/").replace("/", ".")


def _resolve_relative_import(pkg: str, level: int, module: str | None) -> str:
    """Резолвит relative-import (from .x / from ..y) в абсолютное имя."""
    parts = pkg.split(".") if pkg else []
    up = level - 1
    if up > 0:
        parts = parts[:-up] if up <= len(parts) else []
    base = ".".join(parts)
    if module:
        return f"{base}.{module}" if base else module
    return base


def _collect_core_imports(mod_key: str, tree) -> set[str]:
    """Core-модули (src.core.*), импортируемые mod_key (absolute + relative)."""
    deps: set[str] = set()
    pkg = mod_key.rsplit(".", 1)[0] if "." in mod_key else mod_key
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                m = alias.name
                if m.startswith("src.core"):
                    deps.add(m)
                elif m.startswith("core"):
                    deps.add("src." + m)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative: резолвим через пакет файла
                m = _resolve_relative_import(pkg, node.level, node.module)
            else:
                m = node.module or ""
            if m.startswith("src.core"):
                deps.add(m)
            elif m.startswith("core"):
                deps.add("src." + m)
    return deps


def _find_core_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """Уникальные циклы в графе импортов (DFS, три цвета)."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in graph}
    cycles: list[list[str]] = []
    canonical_seen: set[tuple] = set()

    def dfs(u: str, stack: list[str]) -> None:
        color[u] = GRAY
        stack.append(u)
        for v in sorted(graph.get(u, ())):
            if v not in graph:  # вне core или модуль-файл не найден — вне графа
                continue
            if color[v] == GRAY:
                idx = stack.index(v)
                cycle = stack[idx:] + [v]
                canonical = tuple(sorted(cycle[:-1]))
                if canonical not in canonical_seen:
                    canonical_seen.add(canonical)
                    cycles.append(cycle)
            elif color[v] == WHITE:
                dfs(v, stack)
        stack.pop()
        color[u] = BLACK

    for node in graph:
        if color[node] == WHITE:
            dfs(node, [])
    return cycles


def _check_core_no_circular_deps() -> list[str]:
    """Проверяет, что между core-модулями нет циклических зависимостей."""
    errors = []
    graph: dict[str, set[str]] = {}
    core_dir = REPO / "src" / "core"
    for py_file in sorted(core_dir.rglob("*.py")):
        if py_file.name.startswith("__"):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError as e:
            rel = py_file.relative_to(REPO)
            errors.append(f"[SYNTAX] {rel}: {e}")
            continue
        mod_key = _module_dotted(py_file)
        graph[mod_key] = _collect_core_imports(mod_key, tree)

    for cycle in _find_core_cycles(graph):
        if frozenset(cycle) in _ALLOWED_CORE_CYCLES:
            continue
        errors.append("[CIRCULAR] " + " → ".join(cycle))
    return errors


# ══════════════════════════════════════════════════════════════
# Runner
# ══════════════════════════════════════════════════════════════

_CHECKS = [
    ("Core не импортирует MCP", _check_core_no_mcp_imports),
    ("Tools не импортируют Registry напрямую", _check_tools_no_direct_registry),
    ("Нет циклических зависимостей в core", _check_core_no_circular_deps),
    ("Нет ссылок на старые имена", _check_stale_references),
]


def main():
    total_errors = 0
    for name, check_fn in _CHECKS:
        print(f"\n{'='*60}")
        print(f"  {name}")
        print(f"{'='*60}")
        errors = check_fn()
        if errors:
            total_errors += len(errors)
            for e in errors:
                print(f"  ❌ {e}")
        else:
            print("  ✅ OK")

    print(f"\n{'='*60}")
    if total_errors:
        print(f"  ❌ Найдено {total_errors} нарушений")
        sys.exit(1)
    else:
        print("  ✅ Все инварианты соблюдены")
        sys.exit(0)


if __name__ == "__main__":
    main()
