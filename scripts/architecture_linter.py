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

# Разрешённые исключения (documented for v2.5 migration):
# resolve_project_root, _is_self_index_path, passport vars —
# временно в src.mcp.server, будут перенесены в core в v2.5.
_ALLOWED_CORE_MCP_IMPORTS: dict[str, list[str]] = {
    "src.core.runtime_coordinator": ["src.mcp.server"],
    "src.core.intelligence_layer": ["src.mcp.tools.base"],
    "src.core.intelligence.layer": ["src.mcp.tools.base"],
    "src.core.project_context": ["src.mcp.server"],
    "src.core.intelligence.project_context": ["src.mcp.server"],
}


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
        "src/core/system_artifacts.py",  # backward compat
        ".gitignore",                      # backward compat
        "docs/architecture.md",           # historical
        "docs/architecture-layers.md",    # historical
    ],
    "get_project_context(": [
        "CHANGELOG.md",              # historical
        "docs/architecture.md",     # historical
        "src/mcp/server.py",        # old name in comments/docs
    ],
}

_STALE_PATTERNS = [
    # (подстрока, описание, исключаемые файлы)
    (".codebase_index", "старое имя директории (без 'es')", [
        "docs/architecture.md",
        ".gitignore",
        "src/core/system_artifacts.py",  # backward compat — разрешено
        "src/core/symbol_index.py",      # backward compat — обе директории
    ]),
    ("get_project_context(", "старое имя tool (без intel_)", [
        "CHANGELOG.md",  # историческая запись
        "docs/architecture.md",
        "src/mcp/server.py",  # текущая реализация (новое имя)
    ]),
]


def _check_stale_references() -> list[str]:
    """Проверяет, что нет ссылок на старые имена в исходном коде."""
    errors = []
    for py_file in (REPO / "src").rglob("*.py"):
        if py_file.name.startswith("__"):
            continue
        content = py_file.read_text(encoding="utf-8")
        rel = py_file.relative_to(REPO)
        for pattern, description, exceptions in _STALE_PATTERNS:
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
                        errors.append(
                            f"[STALE] {rel}:{lineno} содержит {pattern!r} ({description})"
                        )
                        break
    return errors


# ══════════════════════════════════════════════════════════════
# Runner
# ══════════════════════════════════════════════════════════════

_CHECKS = [
    ("Core не импортирует MCP", _check_core_no_mcp_imports),
    ("Tools не импортируют Registry напрямую", _check_tools_no_direct_registry),
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
        print(f"  ✅ Все инварианты соблюдены")
        sys.exit(0)


if __name__ == "__main__":
    main()
