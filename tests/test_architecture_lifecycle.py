"""Архитектурный тест: полный жизненный цикл проекта.

Проверяет:
  1. resolve_project_root() — проект резолвится
  2. SystemArtifacts — правильные пути не считаются системными
  3. Registry — Indexer создаётся
  4. StateMachine — проект переходит в READY
  5. RuntimeCoordinator — verdict.ok = True
  6. ProjectContext — snapshot содержит все поля
  7. notify_change — индекс обновляется

Это НЕ unit-тест на отдельную функцию. Это тест на то, что
архитектура работает как цепочка слоёв.
"""

import ast
import os
import sys
import tempfile
from pathlib import Path

# ── Настройка окружения ─────────────────────────────────────
# Используем install-dir расширения как PYTHONPATH
_HERE = Path(__file__).resolve().parent.parent  # D:\Project\MSCodeBase
_INSTALL = Path(r"C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence")
_PYTHONPATH = str(_INSTALL if _INSTALL.exists() else _HERE)

if _PYTHONPATH not in sys.path:
    sys.path.insert(0, _PYTHONPATH)

os.environ.setdefault("PROJECT_PATH", str(_HERE))
os.environ.setdefault("ZED_WORKTREE_ROOT", str(_HERE))
os.environ.setdefault("PYTHONPATH", _PYTHONPATH)

import pytest


# ══════════════════════════════════════════════════════════════
# Layer 1: SystemArtifacts
# ══════════════════════════════════════════════════════════════

class TestSystemArtifactsLayer:
    """SystemArtifacts: правильно отличает системные пути от пользовательских."""

    def test_user_project_is_not_system(self):
        from src.core.system_artifacts import SystemArtifacts
        assert SystemArtifacts.is_system_path(_HERE) is False, \
            "Корень проекта не должен быть системным"

    def test_system_directories_are_system(self):
        from src.core.system_artifacts import SystemArtifacts
        assert SystemArtifacts.is_system_dir(".mscodebase")
        assert SystemArtifacts.is_system_dir(".codebase_indices")
        assert SystemArtifacts.is_system_dir(".git")

    def test_feedback_files_are_detected(self):
        from src.core.system_artifacts import SystemArtifacts
        # Файл внутри .codebase_indices — системный
        fake = _HERE / ".codebase_indices" / "summaries_cache" / "chunk_summaries.json"
        assert SystemArtifacts.is_system_path(fake), \
            "Файлы в .codebase_indices должны быть системными"


# ══════════════════════════════════════════════════════════════
# Layer 2-3: Bridge + Registry
# ══════════════════════════════════════════════════════════════

class TestProjectResolutionLayer:
    """resolve_project_root + Registry: проект определяется и индекс создаётся."""

    def test_project_root_resolves(self):
        """Layer 2-3: project_root резолвится."""
        from src.mcp.server import resolve_project_root, reset_project_root_cache
        reset_project_root_cache()
        pr = resolve_project_root()
        assert pr is not None
        assert pr.exists(), f"Проект не существует: {pr}"

    def test_registry_creates_indexer(self):
        """Layer 3: Registry создаёт Indexer для проекта."""
        from src.core.di_container import create_service_collection, IndexerFactoryKey
        services = create_service_collection(_HERE)
        factory = services.resolve(IndexerFactoryKey)
        indexer = factory(_HERE)
        assert indexer is not None
        status = indexer.get_status()
        assert "total_chunks" in status
        assert "unique_files" in status


# ══════════════════════════════════════════════════════════════
# Layer 4-5: StateMachine + Coordinator
# ══════════════════════════════════════════════════════════════

class TestReadinessLayer:
    """StateMachine + RuntimeCoordinator: проект готов к выполнению."""

    @pytest.mark.asyncio
    async def test_coordinator_accepts_project(self):
        """Layer 5: RuntimeCoordinator разрешает выполнение для готового проекта."""
        from src.core.di_container import create_service_collection
        from src.core.runtime_coordinator import RuntimeCoordinator

        services = create_service_collection(_HERE)
        coord = RuntimeCoordinator(services)
        verdict = await coord.can_execute(_HERE)

        # Должен быть ok (READY или INDEXING)
        assert verdict.ok, f"Coordinator отклонил проект: {verdict.reason} — {verdict.detail}"
        assert verdict.reason == "ready"
        assert verdict.state in ("READY", "INDEXING")

    @pytest.mark.asyncio
    async def test_system_paths_blocked(self):
        """Layer 5: Coordinator блокирует системные пути."""
        from src.core.di_container import create_service_collection
        from src.core.runtime_coordinator import RuntimeCoordinator

        services = create_service_collection(_HERE)
        coord = RuntimeCoordinator(services)

        verdict = await coord.can_execute(
            _HERE / ".codebase_indices"
        )
        assert not verdict.ok, "Coordinator должен блокировать .codebase_indices"
        assert verdict.reason == "system_path"

    @pytest.mark.asyncio
    async def test_verdict_has_all_fields(self):
        """ExecutionVerdict содержит все поля диагностики."""
        from src.core.di_container import create_service_collection
        from src.core.runtime_coordinator import RuntimeCoordinator

        services = create_service_collection(_HERE)
        coord = RuntimeCoordinator(services)
        verdict = await coord.can_execute(_HERE)

        d = verdict.to_dict()
        for key in ("ok", "reason", "state", "detail", "retry_after",
                     "requires_reindex", "requires_bridge_sync", "warnings"):
            assert key in d, f"Verdict не содержит поле {key}"


# ══════════════════════════════════════════════════════════════
# Layer 6: ProjectContext
# ══════════════════════════════════════════════════════════════

class TestProjectContextLayer:
    """ProjectContext: snapshot содержит всю информацию о проекте."""

    @pytest.mark.asyncio
    async def test_context_capture_has_all_fields(self):
        """Layer 6: ProjectContext.capture() возвращает полный снэпшот."""
        from src.core.di_container import create_service_collection
        from src.core.project_context import ProjectContext

        services = create_service_collection(_HERE)
        ctx = ProjectContext(_HERE, services)
        snap = await ctx.capture()
        d = snap.to_dict()

        # Проверяем структуру
        for section in ("project", "state", "index", "bridge", "runtime",
                        "health", "memory", "jobs", "captured_at"):
            assert section in d, f"Snapshot не содержит секцию {section}"
        assert d["project"]["path"] == str(_HERE)
        assert d["project"]["name"] == _HERE.name

    @pytest.mark.asyncio
    async def test_context_reads_bridge(self):
        """ProjectContext: bridge path доступен (может быть None)."""
        from src.core.di_container import create_service_collection
        from src.core.project_context import ProjectContext

        services = create_service_collection(_HERE)
        ctx = ProjectContext(_HERE, services)
        snap = await ctx.capture()
        # bridge может быть None — не падает
        assert hasattr(snap, "bridge_path")
        assert hasattr(snap, "bridge_synced")

    @pytest.mark.asyncio
    async def test_context_does_not_mutate(self):
        """ProjectContext immutable: повторный вызов даёт новый snapshot."""
        from src.core.di_container import create_service_collection
        from src.core.project_context import ProjectContext

        services = create_service_collection(_HERE)
        ctx = ProjectContext(_HERE, services)
        snap1 = await ctx.capture()
        snap2 = await ctx.capture()
        # Каждый capture — новый объект
        assert snap1 is not snap2
        assert snap1.captured_at != snap2.captured_at


# ══════════════════════════════════════════════════════════════
# Layer 7: Passport
# ══════════════════════════════════════════════════════════════

class TestPassportLayer:
    """Passport: RUN_ID, BUILD_ID, PID доступны."""

    def test_passport_vars_exist(self):
        from src.mcp import server as srv
        assert hasattr(srv, "_RUN_ID")
        assert hasattr(srv, "_BUILD_ID")
        assert hasattr(srv, "_RUN_PID")
        assert srv._RUN_ID is not None
        assert len(srv._RUN_ID) > 0
        assert srv._RUN_PID > 0

    def test_build_id_has_git_commit(self):
        from src.mcp import server as srv
        # В dev-репо BUILD_ID должен содержать git hash
        if srv._BUILD_ID:
            assert len(srv._BUILD_ID) >= 7, \
                f"BUILD_ID слишком короткий: {srv._BUILD_ID}"
            # Должен быть hex
            int(srv._BUILD_ID, 16)


# ══════════════════════════════════════════════════════════════
# Architecture Invariants (Dependency Graph)
# ══════════════════════════════════════════════════════════════

class TestArchitectureInvariants:
    """Автоматическая проверка архитектурных инвариантов через AST.

    Эти тесты защищают архитектуру от регрессий: если кто-то случайно
    добавит импорт src.mcp в core-слой или напрямую вызовет Registry
    из tool — тест упадёт.
    """

    _REPO = Path(__file__).resolve().parent.parent  # D:\Project\MSCodeBase

    # Invariant 1: Core не импортирует MCP
    _FORBIDDEN_CORE_IMPORTS = {
        "src.mcp", "src.mcp.server", "src.mcp.tools",
        "mcp.server", "mcp.tools",
    }

    # Invariant 2: Tools не импортируют Registry/Bridge (кроме base.py)
    _FORBIDDEN_TOOL_IMPORTS = {
        "src.core.project_indexer_registry",
        "src.core.lsp_project_bridge",
    }

    def _get_imports(self, file_path: Path) -> list[tuple[int, str]]:
        """Возвращает [(lineno, module_name), ...] из AST."""
        result = []
        try:
            tree = ast.parse(file_path.read_text(encoding="utf-8"))
        except SyntaxError:
            return result
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    result.append((node.lineno, alias.name))
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    result.append((node.lineno, node.module))
        return result

    # ─── Invariant 1: Core не импортирует MCP ────────────

    def test_core_does_not_import_mcp(self):
        """Invariant 1: src/core/ не импортирует src.mcp.*"""
        core_dir = self._REPO / "src" / "core"
        errors = []
        for py_file in sorted(core_dir.rglob("*.py")):
            if py_file.name.startswith("__"):
                continue
            for lineno, modname in self._get_imports(py_file):
                for forbidden in self._FORBIDDEN_CORE_IMPORTS:
                    if modname.startswith(forbidden):
                        rel = py_file.relative_to(self._REPO)
                        errors.append(f"{rel}:{lineno} imports {modname!r}")
        assert not errors, (
            f"Core слой не должен импортировать MCP:\n" + chr(10).join(errors)
        )

    # ─── Invariant 2: Tools не импортируют Registry напрямую ────

    def test_tools_do_not_import_registry_directly(self):
        """Invariant 2: tools (кроме base.py) не импортируют Registry/Bridge."""
        tools_dir = self._REPO / "src" / "mcp" / "tools"
        errors = []
        for py_file in sorted(tools_dir.rglob("*.py")):
            if py_file.name in ("__init__.py", "base.py"):
                continue
            for lineno, modname in self._get_imports(py_file):
                for forbidden in self._FORBIDDEN_TOOL_IMPORTS:
                    if modname.startswith(forbidden):
                        rel = py_file.relative_to(self._REPO)
                        errors.append(f"{rel}:{lineno} imports {modname!r}")
        assert not errors, (
            f"Tools должны импортировать Registry только через Coordinator.\n"
            + chr(10).join(errors)
        )

    # ─── Invariant 3: Нет циклических core-зависимостей ────

    def test_no_core_self_import(self):
        """Invariant 3: core файлы не импортируют сами себя."""
        core_dir = self._REPO / "src" / "core"
        for py_file in core_dir.rglob("*.py"):
            if py_file.name.startswith("__"):
                continue
            mod_name = f"src.core.{py_file.stem}"
            for lineno, imp in self._get_imports(py_file):
                if imp == mod_name:
                    rel = py_file.relative_to(self._REPO)
                    pytest.fail(f"{rel}:{lineno} сам себя импортирует")


# ══════════════════════════════════════════════════════════════
# ExecutionVerdict Enriched Fields
# ══════════════════════════════════════════════════════════════

class TestExecutionVerdictEnriched:
    """ExecutionVerdict содержит все поля диагностики."""

    def test_verdict_has_recommended_action(self):
        from src.core.runtime_coordinator import ExecutionVerdict
        v = ExecutionVerdict(ok=False, reason="project_not_ready", state="UNINITIALIZED")
        assert v.recommended_action is not None
        assert "intel_trigger_reindex" in v.recommended_action

    def test_verdict_ready_has_no_action(self):
        from src.core.runtime_coordinator import ExecutionVerdict
        v = ExecutionVerdict(ok=True, reason="ready", state="READY")
        assert v.recommended_action is None

    def test_verdict_has_confidence(self):
        from src.core.runtime_coordinator import ExecutionVerdict
        v = ExecutionVerdict(ok=True, reason="ready", state="READY")
        assert v.confidence == 1.0
        v2 = ExecutionVerdict(ok=False, reason="project_resolution_failed")
        assert v2.confidence == 0.7
        v3 = ExecutionVerdict(ok=False, reason="registry_error")
        assert v3.confidence == 0.5

    def test_to_dict_includes_new_fields(self):
        from src.core.runtime_coordinator import ExecutionVerdict
        v = ExecutionVerdict(ok=True, reason="ready", state="READY",
                             warnings=["bridge not synced"])
        d = v.to_dict()
        assert d["recommended_action"] is None
        assert d["confidence"] == 1.0
        assert "bridge not synced" in d["warnings"]
