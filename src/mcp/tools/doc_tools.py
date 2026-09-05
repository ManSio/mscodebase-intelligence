"""Doc tools: stale_detector — detects documentation version drift."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.di_container import ServiceCollection
from src.core.error_handler import error_boundary
from src.mcp.tools.base import MCPTool
from tools.stale_detector.stale_check import StaleConfig
from tools.stale_detector.stale_check import run as stale_run

logger = logging.getLogger(__name__)


class StaleDetectorTool(MCPTool):
    """stale_detector — detects documentation version drift.

    Compares version strings in markdown docs against pyproject.toml
    (single source of truth). Configurable via stale_config.json.
    """

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="stale_detector")

    @error_boundary("stale_detector", timeout_ms=60000)
    async def execute(
        self,
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> str:
        # INC-MULTI-WINDOW: корень из резолвера (CWD-first, per-window), а не
        # из __file__: в installed-режиме __file__ = каталог расширения, и
        # stale_detector сканировал чужую документацию расширения (аудит Bot_snow #6).
        from src.core.project_resolution import resolve_project_root

        project_root = resolve_project_root()
        config_path = project_root / "tools" / "stale_detector" / "stale_config.json"

        config = self._load_config(config_path)
        actual_version = self._get_actual_version(project_root)
        if actual_version == "unknown":
            return "Cannot determine project version from pyproject.toml"

        # Блокирующее сканирование docs выносим в поток: напрямую stale_run
        # (10-30s, синхронный subprocess/filesystem) блокирует async event loop,
        # и asyncio.wait_for из error_boundary не может прервать его на таймауте
        # (см. инцидент 2026-09-05 — stale_detector стабильно падал по -32001).
        results = await asyncio.to_thread(
            self._scan_docs, project_root, actual_version, config
        )
        total_hits = sum(r["total_hits"] for r in results)
        errors = sum(
            1 for r in results for h in r["hits"] if h["severity"] == "error"
        )

        lines = [
            "Stale Detector — Doc Drift Report",
            f"Actual version: {actual_version}",
            f"Docs with drift: {len(results)}",
            f"Total drift instances: {total_hits} ({errors} errors)",
            "",
        ]

        for r in sorted(results, key=lambda x: -x["total_hits"])[:15]:
            lines.append(f"{r['path']} ({r['total_hits']} drifts)")
            for h in r["hits"][:3]:
                lines.append(
                    f"  L{h['line']}: docs say '{h['expected']}' "
                    f"-> actual '{h['actual']}'"
                )
            if len(r["hits"]) > 3:
                lines.append(f"  ... +{len(r['hits']) - 3} more")
            lines.append("")

        if errors:
            lines.append("VERDICT: Docs have VERSION DRIFT — outdated info!")
        else:
            lines.append("VERDICT: Docs appear up to date.")

        return "\n".join(lines)

    def _load_config(self, config_path: Path) -> dict:
        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _get_actual_version(self, project_root: Path) -> str:
        pyproject = project_root / "pyproject.toml"
        if pyproject.exists():
            for line in pyproject.read_text(encoding="utf-8").split("\n"):
                m = re.match(r'version\s*=\s*["\'](.+?)["\']', line)
                if m:
                    return m.group(1)
        return "unknown"

    def _scan_docs(
        self, project_root: Path, actual_version: str, config: dict
    ) -> list:
        """Делегирование каноническому чекеру tools/stale_detector/stale_check.py.

        Single source of truth (§6.2): дублированная реализация здесь ранее НЕ
        поддерживала <!-- stale-ignore -->, severity_overrides и ARCHIVED-скип —
        давала ложные дрейфы (инцидент 2026-08-14: 11 ложных на AGENTS/TELEMETRY
        при 0 у канонического чекера).
        """
        cfg = StaleConfig(
            exclude_files=config.get("exclude_files") or [],
            exclude_dirs=config.get("exclude_dirs"),  # None → канонические defaults
            version_exclude_patterns=config.get("version_exclude_patterns") or [],
            version_ignore_files=config.get("version_ignore_files") or [],
            severity_overrides=config.get("severity_overrides") or {},
        )
        return [
            {
                "path": rep.path,
                "mtime": rep.mtime,
                "hits": rep.hits,
                "total_hits": rep.total_hits,
            }
            for rep in stale_run(project_root, cfg)
        ]
