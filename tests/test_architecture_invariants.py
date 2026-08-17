"""Архитектурные инварианты — быстрые AST-проверки (без реальных сервисов).

Вынесены из tests/test_architecture_lifecycle.py 2026-08-17: тот файл помечен
pytestmark=slow целиком, поэтому test_core_does_not_import_mcp и
test_no_core_self_import молча исключались из дефолтного CI-прогона
(-m 'not slow and not benchmark') — нарушения импортов, найденные ARCLUX CLI
2026-08-17 (layer.py→mcp; graph.py self-import), проскальзывали мимо guard.

Этот файл — быстрый GUARD (§4): чистый AST-скан src/, без импорта src.*, < 1s.
Запускается в дефолтном pytest → регрессии импортов видны в CI сразу.
"""

import ast
from pathlib import Path
from typing import List, Optional, Tuple

import pytest

_REPO = Path(__file__).resolve().parent.parent


class TestArchitectureInvariants:
    _FORBIDDEN_CORE_IMPORTS = {
        "src.mcp", "src.mcp.server", "src.mcp.tools",
        "mcp.server", "mcp.tools",
    }

    # После ARCH-03 core не импортирует MCP вообще — исключений нет.
    # Stale-ключи удалены 2026-08-17: "src.core.intelligence_layer" (модуль
    # не существует), "src.core.runtime_coordinator" / "src.core.project_context"
    # (больше не импортируют mcp — проверено grep'ом в этой сессии).
    _ALLOWED_CORE_MCP_IMPORTS = {}

    @staticmethod
    def _module_dotted(file_path: Path) -> str:
        """'src/core/graph.py' → 'src.core.graph'."""
        rel = file_path.relative_to(_REPO)
        return str(rel.with_suffix("")).replace("/", ".").replace("\\", ".")

    @classmethod
    def _resolve_module(cls, pkg: str, node) -> Optional[str]:
        """Резолвит модуль import-узла в абсолютное имя (включая relative)."""
        if node.level:  # relative import: from .x import y / from ..x import y
            parts = pkg.split(".") if pkg else []
            up = node.level - 1
            if up > 0:
                parts = parts[:-up] if up <= len(parts) else []
            base = ".".join(parts)
            if node.module:
                return f"{base}.{node.module}" if base else node.module
            return base
        return node.module

    def _get_imports(self, file_path):
        """(lineno, абсолютное имя модуля) для ВСЕХ import-узлов, включая lazy и relative."""
        result: List[Tuple[int, str]] = []
        try:
            tree = ast.parse(file_path.read_text(encoding="utf-8"))
        except SyntaxError:
            return result
        mod = self._module_dotted(file_path)
        pkg = mod.rsplit(".", 1)[0] if "." in mod else ""
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    result.append((node.lineno, alias.name))
            elif isinstance(node, ast.ImportFrom):
                resolved = self._resolve_module(pkg, node)
                if resolved:
                    result.append((node.lineno, resolved))
        return result

    def test_core_does_not_import_mcp(self):
        core_dir = _REPO / "src" / "core"
        errors = []
        for py_file in sorted(core_dir.rglob("*.py")):
            if py_file.name.startswith("__"):
                continue
            rel = str(py_file.relative_to(_REPO))
            rel_dotted = self._module_dotted(py_file)
            allowed = self._ALLOWED_CORE_MCP_IMPORTS.get(rel_dotted, [])
            for lineno, modname in self._get_imports(py_file):
                for forbidden in self._FORBIDDEN_CORE_IMPORTS:
                    if modname.startswith(forbidden):
                        if any(modname.startswith(a) for a in allowed):
                            continue
                        errors.append(f"{rel}:{lineno} imports {modname!r}")
        assert not errors, "Core layer imports MCP:\n" + "\n".join(errors)

    def test_tools_do_not_import_registry_directly(self):
        tools_dir = _REPO / "src" / "mcp" / "tools"
        _FORBIDDEN_TOOL_IMPORTS = {
            "src.core.project_indexer_registry",
            "src.core.lsp_project_bridge",
        }
        errors = []
        for py_file in sorted(tools_dir.rglob("*.py")):
            if py_file.name in ("__init__.py", "base.py"):
                continue
            for lineno, modname in self._get_imports(py_file):
                for forbidden in _FORBIDDEN_TOOL_IMPORTS:
                    if modname.startswith(forbidden):
                        rel = py_file.relative_to(_REPO)
                        errors.append(f"{rel}:{lineno} imports {modname!r}")
        assert not errors, "Tools must use Coordinator, not Registry:\n" + "\n".join(errors)

    def test_no_core_self_import(self):
        """Файл не может импортировать сам себя — включая relative-синтаксис.

        ARCLUX 2026-08-17: src/core/graph.py:687 делал `from .graph import Edge`
        (self-import, Edge определён в том же файле). Старый тест сравнивал
        сырые имена ('.graph' != 'src.core.graph') и НЕ ловил — _get_imports
        резолвит relative-импорты в абсолютные.
        """
        core_dir = _REPO / "src" / "core"
        for py_file in core_dir.rglob("*.py"):
            if py_file.name.startswith("__"):
                continue
            own_mod = self._module_dotted(py_file)
            for lineno, imp in self._get_imports(py_file):
                if imp == own_mod:
                    rel = py_file.relative_to(_REPO)
                    pytest.fail(f"{rel}:{lineno} self-imports {imp!r}")
