"""
ProjectContext — единая точка входа для получения всей информации о проекте.

Агрегирует данные из:
  • ProjectIndexerRegistry (состояние, индекс)
  • LSP Bridge (путь, синхронизация)
  • Runtime Passport (PID, uptime, env)
  • HealthReport (предупреждения, ошибки)
  • IntelligenceStore (инциденты, ADR, проектная память)
  • JobTracker (фоновые задачи)

Вместо того чтобы дёргать 5 разных компонентов, инструмент делает один вызов:
    ctx = ProjectContext(project_path, services)
    ctx.state          # ProjectState.READY
    ctx.index_chunks   # 1362
    ctx.bridge_synced  # True
    ctx.health_ok      # True

Ничего не ломает — добавляется как новый слой поверх существующей архитектуры.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

__all__ = [
    "ProjectContextSnapshot",
    "ProjectContext",
]
logger = logging.getLogger("mscodebase_server.project_context")


@dataclass
class ProjectContextSnapshot:
    """Снэпшот состояния проекта на момент запроса.

    Все поля опциональны — если компонент недоступен, поле будет None.
    """

    # Идентификация
    project_path: str = ""
    project_name: str = ""

    # Состояние (из Registry)
    state: Optional[str] = None  # READY / INDEXING / FAILED / ...
    state_changed_at: Optional[str] = None

    # Индекс (из Indexer)
    index_chunks: Optional[int] = None
    index_files: Optional[int] = None
    index_symbols: Optional[int] = None
    index_embedder: Optional[str] = None  # LM Studio / local / none

    # Bridge (из LSP)
    bridge_path: Optional[str] = None  # путь из LSP bridge
    bridge_synced: Optional[bool] = None  # True если bridge синхронизирован

    # Runtime (из Passport)
    runtime_pid: Optional[int] = None
    runtime_uptime: Optional[float] = None
    runtime_ext_root: Optional[str] = None
    runtime_env: Dict[str, Optional[str]] = field(default_factory=dict)

    # Health
    health_ok: Optional[bool] = None
    health_warnings: List[str] = field(default_factory=list)
    health_errors: List[str] = field(default_factory=list)

    # Memory (из IntelligenceStore)
    memory_incidents: int = 0
    memory_adrs: int = 0
    memory_known_issues: int = 0

    # Jobs
    jobs_running: int = 0
    jobs_completed: int = 0

    # Мета
    captured_at: str = ""
    capture_duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Сериализация в dict для JSON-вывода."""
        return {
            "project": {
                "path": self.project_path,
                "name": self.project_name,
            },
            "state": {
                "current": self.state,
                "changed_at": self.state_changed_at,
            },
            "index": {
                "chunks": self.index_chunks,
                "files": self.index_files,
                "symbols": self.index_symbols,
                "embedder": self.index_embedder,
            },
            "bridge": {
                "path": self.bridge_path,
                "synced": self.bridge_synced,
            },
            "runtime": {
                "pid": self.runtime_pid,
                "uptime_sec": self.runtime_uptime,
                "ext_root": self.runtime_ext_root,
                "env": self.runtime_env,
            },
            "health": {
                "ok": self.health_ok,
                "warnings": self.health_warnings,
                "errors": self.health_errors,
            },
            "memory": {
                "incidents": self.memory_incidents,
                "adrs": self.memory_adrs,
                "known_issues": self.memory_known_issues,
            },
            "jobs": {
                "running": self.jobs_running,
                "completed": self.jobs_completed,
            },
            "captured_at": self.captured_at,
            "capture_duration_ms": round(self.capture_duration_ms, 1),
        }


class ProjectContext:
    """Единая точка входа для получения информации о проекте.

    Usage:
        ctx = ProjectContext(project_path, services)
        snapshot = await ctx.capture()
        print(snapshot.state)             # READY
        print(snapshot.index_chunks)      # 1362
        print(snapshot.runtime_pid)       # 31420
        print(snapshot.health_ok)         # True
    """

    def __init__(self, project_path: Path, services: Any):
        self._path = project_path.resolve()
        self._services = services
        self._name = self._path.name

    @property
    def path(self) -> Path:
        return self._path

    @property
    def name(self) -> str:
        return self._name

    async def capture(self) -> ProjectContextSnapshot:
        """Собирает полный снэпшот состояния проекта из всех компонентов.

        Каждый блок обёрнут в try/except — если компонент недоступен,
        соответствующее поле будет None, а не упадёт весь запрос.
        """
        t0 = time.time()
        snap = ProjectContextSnapshot(
            project_path=str(self._path),
            project_name=self._name,
            captured_at=datetime.now().isoformat(),
        )

        # ─── State + Index (Registry) ───────────────────────
        snap = self._capture_registry(snap)

        # ─── Bridge (LSP) ────────────────────────────────────
        snap = self._capture_bridge(snap)

        # ─── Runtime (Passport) ──────────────────────────────
        snap = self._capture_runtime(snap)

        # ─── Health ──────────────────────────────────────────
        snap = await self._capture_health(snap)

        # ─── Memory (IntelligenceStore) ─────────────────────
        snap = self._capture_memory(snap)

        # ─── Jobs ────────────────────────────────────────────
        snap = self._capture_jobs(snap)

        snap.capture_duration_ms = (time.time() - t0) * 1000
        return snap

    # ─── Registry ──────────────────────────────────────────────

    def _capture_registry(self, snap: ProjectContextSnapshot) -> ProjectContextSnapshot:
        try:
            from src.core.di_container import ProjectIndexerRegistry as PIRKey

            registry = self._services.resolve(PIRKey)
            snap.state = registry.get_state(self._path).name
            try:
                indexer = registry.get_indexer(self._path)
                status = indexer.get_status()
                snap.index_chunks = status.get("total_chunks", 0)
                snap.index_files = status.get("unique_files", 0)
                # Bugfix: get_status() не возвращает symbols_count и embedder_mode
                # Берём symbols напрямую из SymbolIndex
                try:
                    if hasattr(indexer, "_symbol_index"):
                        snap.index_symbols = indexer._symbol_index.get_symbol_count()
                except Exception as _e:
                    logger.warning(f"symbol_index count failed: {_e}")
                # Берём embedder из embedder объекта
                try:
                    if hasattr(indexer, "embedder"):
                        snap.index_embedder = getattr(
                            indexer.embedder, "mode", "unknown"
                        )
                except Exception as _e:
                    logger.warning(f"embedder mode failed: {_e}")
            except Exception as _e:
                logger.warning(f"registry snapshot iteration failed: {_e}")
        except Exception as e:
            logger.debug(f"ProjectContext: registry error: {e}")
        return snap

    # ─── Bridge ────────────────────────────────────────────────

    def _capture_bridge(self, snap: ProjectContextSnapshot) -> ProjectContextSnapshot:
        try:
            from src.core.lsp_project_bridge import read_project_from_bridge

            bp = read_project_from_bridge(max_wait=0.2)
            if bp is not None:
                snap.bridge_path = str(bp)
                snap.bridge_synced = bp.resolve() == self._path
            else:
                snap.bridge_path = None
                snap.bridge_synced = False
        except Exception as e:
            logger.debug(f"ProjectContext: bridge error: {e}")
        return snap

    # ─── Runtime ───────────────────────────────────────────────

    def _capture_runtime(self, snap: ProjectContextSnapshot) -> ProjectContextSnapshot:
        try:
            from src.core.passport import RUN_PID, RUN_STARTED_AT
            from src.mcp.server import _ext_root

            snap.runtime_pid = RUN_PID
            snap.runtime_uptime = round(time.time() - RUN_STARTED_AT, 1)
            snap.runtime_ext_root = str(_ext_root)
            snap.runtime_env = {
                "PROJECT_PATH": os.environ.get("PROJECT_PATH"),
                "ZED_WORKTREE_ROOT": os.environ.get("ZED_WORKTREE_ROOT"),
                "MSCODEBASE_ALLOW_SELF_INDEX": os.environ.get(
                    "MSCODEBASE_ALLOW_SELF_INDEX"
                ),
                "PYTHONPATH_0": (os.environ.get("PYTHONPATH") or "").split(os.pathsep)[
                    0
                ]
                or None,
            }
        except Exception as e:
            logger.debug(f"ProjectContext: runtime error: {e}")
        return snap

    # ─── Health ────────────────────────────────────────────────

    async def _capture_health(
        self, snap: ProjectContextSnapshot
    ) -> ProjectContextSnapshot:
        try:
            from src.core.intelligence.health import HealthReport

            hr = HealthReport(self._path, self._services)
            report = await hr.generate()
            if isinstance(report, dict):
                snap.health_ok = report.get("status") == "ok"
                snap.health_warnings = report.get("warnings", [])
                snap.health_errors = report.get("errors", [])
        except Exception as e:
            logger.debug(f"ProjectContext: health error: {e}")
        return snap

    # ─── Memory ────────────────────────────────────────────────

    def _capture_memory(self, snap: ProjectContextSnapshot) -> ProjectContextSnapshot:
        try:
            from src.core.intelligence.layer import IntelligenceStore

            store = IntelligenceStore(self._path)
            memory = store.load_memory()
            if isinstance(memory, dict):
                snap.memory_incidents = len(store.load_incidents())
                snap.memory_adrs = len(memory.get("adrs", []))
                snap.memory_known_issues = len(memory.get("known_issues", []))
        except Exception as e:
            logger.debug(f"ProjectContext: memory error: {e}")
        return snap

    # ─── Jobs ──────────────────────────────────────────────────

    def _capture_jobs(self, snap: ProjectContextSnapshot) -> ProjectContextSnapshot:
        try:
            from src.mcp.server import _last_progress

            running = 0
            completed = 0
            with __import__("threading").Lock():
                for pname, info in list(_last_progress.items()):
                    if info.get("phase") == "complete":
                        completed += 1
                    else:
                        running += 1
            snap.jobs_running = running
            snap.jobs_completed = completed
        except Exception as e:
            logger.debug(f"ProjectContext: jobs error: {e}")
        return snap
