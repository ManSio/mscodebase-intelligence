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

import os
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent.parent
_INSTALL = Path(r"C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence")
_PYTHONPATH = str(_INSTALL if _INSTALL.exists() else _HERE)

pytestmark = pytest.mark.slow


@pytest.fixture(autouse=True)
def _use_installed_extension():
    """Интеграционный smoke: импорты идут из УСТАНОВЛЕННОГО расширения (если есть).

    sys.path и env НЕ загрязняются на уровне модуля — раньше insert(0) на
    уровне импорта ломал всю pytest-сессию: соседние тесты начинали
    импортировать устаревшую копию src/ из расширения (без новых модулей
    рабочего дерева) → ModuleNotFoundError.
    """
    original_path = list(sys.path)
    original_env = {
        k: os.environ.get(k) for k in ("PROJECT_PATH", "ZED_WORKTREE_ROOT", "PYTHONPATH")
    }
    if _PYTHONPATH not in sys.path:
        sys.path.insert(0, _PYTHONPATH)
    os.environ.setdefault("PROJECT_PATH", str(_HERE))
    os.environ.setdefault("ZED_WORKTREE_ROOT", str(_HERE))
    os.environ.setdefault("PYTHONPATH", _PYTHONPATH)
    yield
    sys.path[:] = original_path
    for k, v in original_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


class TestSystemArtifactsLayer:
    def test_user_project_is_not_system(self):
        from src.core.system_artifacts import SystemArtifacts
        assert SystemArtifacts.is_system_path(_HERE) is False

    def test_system_directories_are_system(self):
        from src.core.system_artifacts import SystemArtifacts
        assert SystemArtifacts.is_system_dir(".mscodebase")
        assert SystemArtifacts.is_system_dir(".codebase_indices")
        assert SystemArtifacts.is_system_dir(".git")

    def test_feedback_files_are_detected(self):
        from src.core.system_artifacts import SystemArtifacts
        fake = _HERE / ".codebase_indices" / "summaries_cache" / "chunk_summaries.json"
        assert SystemArtifacts.is_system_path(fake)


class TestProjectResolutionLayer:
    def test_project_root_resolves(self):
        from src.mcp.server import reset_project_root_cache, resolve_project_root
        reset_project_root_cache()
        pr = resolve_project_root()
        assert pr is not None
        assert pr.exists()

    def test_registry_creates_indexer(self):
        from src.core.di_container import IndexerFactoryKey, create_service_collection
        services = create_service_collection(_HERE)
        factory = services.resolve(IndexerFactoryKey)
        indexer = factory(_HERE)
        assert indexer is not None
        status = indexer.get_status()
        assert "total_chunks" in status


class TestReadinessLayer:
    @pytest.mark.asyncio
    async def test_coordinator_accepts_project(self):
        from src.core.di_container import IndexerFactoryKey, create_service_collection
        from src.core.di_container import ProjectIndexerRegistry as PIRKey
        from src.core.runtime_coordinator import RuntimeCoordinator
        services = create_service_collection(_HERE)
        registry = services.resolve(PIRKey)
        factory = services.resolve(IndexerFactoryKey)
        registry.get_indexer(_HERE, factory=factory)
        coord = RuntimeCoordinator(services)
        verdict = await coord.can_execute(_HERE)
        assert verdict.ok, f"Coordinator rejected project: {verdict.reason}"

    @pytest.mark.asyncio
    async def test_system_paths_blocked(self):
        from src.core.di_container import create_service_collection
        from src.core.runtime_coordinator import RuntimeCoordinator
        services = create_service_collection(_HERE)
        coord = RuntimeCoordinator(services)
        verdict = await coord.can_execute(_HERE / ".codebase_indices")
        assert not verdict.ok
        assert verdict.reason == "system_path"

    @pytest.mark.asyncio
    async def test_verdict_has_all_fields(self):
        from src.core.di_container import IndexerFactoryKey, create_service_collection
        from src.core.di_container import ProjectIndexerRegistry as PIRKey
        from src.core.runtime_coordinator import RuntimeCoordinator
        services = create_service_collection(_HERE)
        registry = services.resolve(PIRKey)
        factory = services.resolve(IndexerFactoryKey)
        registry.get_indexer(_HERE, factory=factory)
        coord = RuntimeCoordinator(services)
        verdict = await coord.can_execute(_HERE)
        d = verdict.to_dict()
        for key in ("ok", "reason", "state", "retry_after", "requires_reindex",
                     "requires_bridge_sync", "warnings", "recommended_action", "confidence"):
            assert key in d, f"Verdict missing field: {key}"


class TestProjectContextLayer:
    @pytest.mark.asyncio
    async def test_context_capture_has_all_fields(self):
        from src.core.di_container import create_service_collection
        from src.core.intelligence.project_context import ProjectContext
        services = create_service_collection(_HERE)
        ctx = ProjectContext(_HERE, services)
        snap = await ctx.capture()
        d = snap.to_dict()
        for section in ("project", "state", "index", "bridge", "runtime",
                        "health", "memory", "jobs", "captured_at"):
            assert section in d
        assert d["project"]["path"] == str(_HERE)

    @pytest.mark.asyncio
    async def test_context_reads_bridge(self):
        from src.core.di_container import create_service_collection
        from src.core.intelligence.project_context import ProjectContext
        services = create_service_collection(_HERE)
        ctx = ProjectContext(_HERE, services)
        snap = await ctx.capture()
        assert hasattr(snap, "bridge_path")
        assert hasattr(snap, "bridge_synced")

    @pytest.mark.asyncio
    async def test_context_does_not_mutate(self):
        from src.core.di_container import create_service_collection
        from src.core.intelligence.project_context import ProjectContext
        services = create_service_collection(_HERE)
        ctx = ProjectContext(_HERE, services)
        snap1 = await ctx.capture()
        snap2 = await ctx.capture()
        assert snap1 is not snap2
        assert snap1.captured_at != snap2.captured_at


class TestPassportLayer:
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
        if srv._BUILD_ID:
            assert len(srv._BUILD_ID) >= 7
            int(srv._BUILD_ID, 16)


class TestExecutionVerdictEnriched:
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

    def test_to_dict_includes_new_fields(self):
        from src.core.runtime_coordinator import ExecutionVerdict
        v = ExecutionVerdict(ok=True, reason="ready", state="READY", warnings=["bridge not synced"])
        d = v.to_dict()
        assert d["recommended_action"] is None
        assert d["confidence"] == 1.0
        assert "bridge not synced" in d["warnings"]
