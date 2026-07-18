"""Doc tools: stale_detector — detects documentation version drift."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.di_container import ServiceCollection
from src.core.error_handler import error_boundary
from src.mcp.tools.base import MCPTool


class StaleDetectorTool(MCPTool):
    """stale_detector — detects documentation version drift.

    Compares version strings in markdown docs against pyproject.toml
    (single source of truth). Configurable via stale_config.json.
    """

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="stale_detector")

    @error_boundary("stale_detector", timeout_ms=10000)
    async def execute(
        self,
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> str:
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        config_path = project_root / "tools" / "stale_detector" / "stale_config.json"

        config = self._load_config(config_path)
        actual_version = self._get_actual_version(project_root)
        if actual_version == "unknown":
            return "Cannot determine project version from pyproject.toml"

        results = self._scan_docs(project_root, actual_version, config)
        total_hits = sum(r["total_hits"] for r in results)
        errors = sum(
            1 for r in results for h in r["hits"] if h["severity"] == "error"
        )

        lines = [
            f"Stale Detector — Doc Drift Report",
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
        exclude_files = set(config.get("exclude_files", []))
        exclude_dirs = set(config.get("exclude_dirs", []))
        version_exclude = config.get("version_exclude_patterns", [])
        version_ignore = config.get("version_ignore_files", [])

        results = []
        for md_file in sorted(project_root.rglob("*.md")):
            rel = str(md_file.relative_to(project_root))
            parts = Path(rel).parts

            name = md_file.name
            if name in exclude_files:
                continue
            if any(d in parts for d in exclude_dirs):
                continue
            if any(rel.endswith(f) for f in version_ignore):
                continue

            try:
                text = md_file.read_text(encoding="utf-8")
            except Exception as _read_err:
                logger.debug(f"Skip unreadable {md_file.name}: {_read_err}")
                continue

            mtime = datetime.fromtimestamp(md_file.stat().st_mtime)
            hits = []
            in_code_block = False

            for i, line in enumerate(text.split("\n"), 1):
                if line.strip().startswith("```"):
                    in_code_block = not in_code_block
                    continue
                if in_code_block:
                    continue

                for m in re.finditer(r'(?:v?)(\d+\.\d+\.\d+)', line):
                    ver = m.group(1)
                    if any(re.search(p, ver) for p in version_exclude):
                        continue
                    if ver != actual_version:
                        hits.append({
                            "line": i,
                            "expected": ver,
                            "actual": actual_version,
                            "severity": "error",
                        })

            if hits:
                results.append({
                    "path": rel,
                    "mtime": mtime.strftime("%Y-%m-%d %H:%M"),
                    "hits": hits,
                    "total_hits": len(hits),
                })

        return results
