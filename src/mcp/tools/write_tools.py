"""Write tools: rename_symbol, ack_impact, move_symbol, safe_delete.

IMPLEMENTED:
- rename_symbol — rename symbol across all files (preview/apply)
- ack_impact — acknowledge impact for modification guard

PLANNED (Phase 2-3):
- move_symbol — move symbol to another file
- safe_delete — safe deletion with reference check
- replace_symbol — replace symbol body
- insert_before/after_symbol — anchor-based insertion
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.di_container import ServiceCollection
from src.core.error_handler import error_boundary
from src.core.symbol_index import SymbolIndex
from src.mcp.tools.base import MCPTool

logger = logging.getLogger("mscodebase_server.write_tools")


class RenameSymbolTool(MCPTool):
    """rename_symbol — rename a symbol across all files (preview/apply)."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="rename_symbol")

    @error_boundary("rename_symbol", timeout_ms=30000)
    async def execute(
        self,
        old_name: str,
        new_name: str,
        file_path: str = "",
        apply: bool = False,
        allow_collision: bool = False,
    ) -> Dict[str, Any]:
        """Rename a symbol across all files that reference it.

        Args:
            old_name: Current symbol name
            new_name: New symbol name
            file_path: Restrict to specific file (optional)
            apply: If False — preview only; if True — apply changes
            allow_collision: If False — error if new_name already exists

        Returns:
            Preview or apply result.
        """
        await self.require_ready_project()
        si = self.resolve_symbol_index()

        # 1. Find all references
        all_refs = si.find_all_references(old_name)

        if not all_refs:
            # Fallback: full-text search for the symbol name
            all_refs = self._find_references_fallback(old_name)

        if not all_refs:
            return {
                "status": "warning",
                "message": f"Symbol '{old_name}' not found in index.",
                "changes": [],
            }

        # Filter by file_path if specified
        if file_path:
            target = Path(file_path).resolve().as_posix()
            all_refs = [
                r
                for r in all_refs
                if Path(r.file_path).resolve().as_posix() == target
            ]

        if not all_refs:
            return {
                "status": "warning",
                "message": f"Symbol '{old_name}' not found in file '{file_path}'.",
                "changes": [],
            }

        # 2. Collision check
        if not allow_collision:
            collision = self._check_collision(new_name, all_refs, si)
            if collision:
                return {
                    "status": "error",
                    "message": (
                        f"Symbol '{new_name}' already exists in target scope. "
                        f"Use allow_collision=True to override."
                    ),
                    "collision": collision,
                }

        # 3. Build preview
        changes = self._build_changes(old_name, new_name, all_refs)

        if not apply:
            return {
                "status": "preview",
                "message": f"Preview: rename '{old_name}' \u2192 '{new_name}' ({len(changes)} occurrences)",
                "changes": changes,
                "files_affected": len(set(c["file"] for c in changes)),
                "total_occurrences": len(changes),
            }

        # 4. Apply changes
        result = await self._apply_changes(changes)

        # 5. Update in-memory index
        si.rename_symbol(old_name, new_name)

        # 6. Notify indexer
        try:
            indexer = self.resolve_indexer()
            if hasattr(indexer, "notify_file_changed"):
                for file in result.get("files", []):
                    indexer.notify_file_changed(file)
        except Exception:
            pass

        return result

    def _find_references_fallback(self, symbol: str) -> list:
        """Fallback: search for symbol in file contents via symbol_index text search."""
        si = self.resolve_symbol_index()
        results = []
        try:
            # search_symbols возвращает список SymbolRef
            found = si.search_symbols(symbol)
            if found:
                results = found
        except Exception:
            pass
        return results

    def _check_collision(
        self, new_name: str, refs: list, si: SymbolIndex
    ) -> Optional[Dict]:
        """Check if new_name already exists in target files."""
        target_files = set(r.file_path for r in refs)
        collisions = []

        for file in target_files:
            symbols_in_file = si.get_symbols_in_file(file)
            if new_name in symbols_in_file:
                collisions.append({"file": file, "symbol": new_name})

        if collisions:
            return {"existing_symbol": new_name, "in_files": collisions}
        return None

    def _build_changes(
        self, old_name: str, new_name: str, refs: list
    ) -> List[Dict]:
        """Build list of changes (preview format)."""
        seen = set()
        changes = []

        for r in refs:
            key = (r.file_path, r.line)
            if key not in seen:
                seen.add(key)
                changes.append(
                    {
                        "file": r.file_path,
                        "line": r.line,
                        "kind": r.kind,
                        "is_definition": r.is_definition,
                        "old": old_name,
                        "new": new_name,
                    }
                )

        # Sort by file, then line
        changes.sort(key=lambda c: (c["file"], c["line"]))
        return changes

    async def _apply_changes(self, changes: List[Dict]) -> Dict[str, Any]:
        """Apply rename changes to disk files.

        Uses direct file I/O — no LSP dependency.
        """
        # Group changes by file
        by_file: Dict[str, List[Dict]] = {}
        for c in changes:
            by_file.setdefault(c["file"], []).append(c)

        applied = 0
        errors = []
        files_modified = []

        for file_path, file_changes in by_file.items():
            try:
                # Read file content
                abs_path = Path(file_path).resolve()
                if not abs_path.exists():
                    errors.append(f"File not found: {file_path}")
                    continue

                content = abs_path.read_text(encoding="utf-8", errors="replace")
                lines = content.splitlines(True)  # keep line endings

                # Apply changes in reverse line order (to preserve line numbers)
                file_changes.sort(key=lambda c: c["line"], reverse=True)

                for change in file_changes:
                    line_idx = change["line"] - 1  # 0-based
                    if line_idx < 0 or line_idx >= len(lines):
                        errors.append(
                            f"Line {change['line']} out of range in {file_path}"
                        )
                        continue

                    old_line = lines[line_idx]
                    new_line = old_line.replace(change["old"], change["new"], 1)
                    if new_line != old_line:
                        lines[line_idx] = new_line
                        applied += 1

                # Write back
                abs_path.write_text("".join(lines), encoding="utf-8")
                files_modified.append(file_path)

            except Exception as e:
                errors.append(f"Error processing {file_path}: {e}")

        result: Dict[str, Any] = {
            "status": "applied" if not errors else "partial",
            "message": f"Renamed {applied} occurrences across {len(files_modified)} files.",
            "changes_applied": applied,
            "files": files_modified,
        }

        if errors:
            result["errors"] = errors
            result["status"] = "partial"

        return result


class AckImpactTool(MCPTool):
    """ack_impact — acknowledge impact for modification guard.

    After calling impact_analysis, call ack_impact to allow
    write operations on guarded files for TTL seconds.
    """

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="ack_impact")

    @error_boundary("ack_impact", timeout_ms=5000)
    async def execute(
        self,
        file_path: str = "",
        symbol: str = "",
    ) -> Dict[str, Any]:
        """Acknowledge impact of changes.

        Args:
            file_path: Path to the file being modified
            symbol: Symbol name being modified (alternative to file_path)

        Returns:
            Ack status with TTL.
        """
        from src.core.modification_guard import ack_impact as _ack

        target = file_path or symbol
        if not target:
            return {
                "status": "error",
                "message": "Provide either file_path or symbol.",
            }

        result = _ack(target)
        return result


__all__ = [
    "RenameSymbolTool",
    "AckImpactTool",
]
