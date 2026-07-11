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


class MoveSymbolTool(MCPTool):
    """move_symbol — move a symbol to another file (preview/apply)."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="move_symbol")

    @error_boundary("move_symbol", timeout_ms=30000)
    async def execute(
        self,
        symbol: str,
        to_file: str,
        file_path: str = "",
        apply: bool = False,
    ) -> Dict[str, Any]:
        """Move a symbol to another file, updating all imports.

        Args:
            symbol: Symbol name to move
            to_file: Target file path (relative to project root)
            file_path: Source file path (optional, uses first definition if empty)
            apply: If False — preview only; if True — apply changes

        Returns:
            Preview or apply result.
        """
        await self.require_ready_project()
        si = self.resolve_symbol_index()

        # 1. Find definition
        defs = si.find_definitions(symbol)
        if not defs:
            return {
                "status": "warning",
                "message": f"Symbol '{symbol}' not found in index.",
            }

        # Filter by source file if specified
        if file_path:
            target = Path(file_path).resolve().as_posix()
            defs = [d for d in defs if Path(d.file_path).resolve().as_posix() == target]

        if not defs:
            return {
                "status": "warning",
                "message": f"Symbol '{symbol}' not found in specified file.",
            }

        source_def = defs[0]
        source_file = source_def.file_path

        # 2. Find all references
        all_refs = si.find_all_references(symbol)

        # 3. Build preview
        target_path = Path(to_file)
        if not target_path.is_absolute():
            target_path = Path(self.resolve_indexer().project_path) / to_file
        target_path = target_path.resolve()
        target_file = target_path.as_posix()

        source_package = self._infer_package(source_file)
        target_package = self._infer_package(target_file)

        preview_changes = []

        # Definition move
        preview_changes.append({
            "op": "move_definition",
            "symbol": symbol,
            "from": source_file,
            "to": target_file,
            "line": source_def.line,
            "kind": source_def.kind,
        })

        # Import updates for all referencing files
        updated_imports = set()
        for ref in all_refs:
            ref_file = ref.file_path
            if ref_file == source_file:
                continue
            if ref_file not in updated_imports:
                updated_imports.add(ref_file)
                preview_changes.append({
                    "op": "update_import",
                    "file": ref_file,
                    "old_import": f"from {source_package} import {symbol}",
                    "new_import": f"from {target_package} import {symbol}",
                })

        if not apply:
            return {
                "status": "preview",
                "message": f"Preview: move '{symbol}' → {to_file} ({len(preview_changes)} changes)",
                "changes": preview_changes,
                "source_file": source_file,
                "target_file": target_file,
                "symbol_kind": source_def.kind,
            }

        # 4. Apply changes
        result = await self._apply_move(
            symbol=symbol,
            source_file=source_file,
            target_file=target_file,
            all_refs=all_refs,
            source_package=source_package,
            target_package=target_package,
        )

        return result

    def _infer_package(self, file_path: str) -> str:
        """Infer Python package from file path.

        E.g., src/core/foo.py → src.core
        """
        p = Path(file_path).resolve()
        parts = p.as_posix().rstrip(".py").split("/")
        # Remove empty parts
        parts = [pt for pt in parts if pt]
        return ".".join(parts)

    async def _apply_move(
        self,
        symbol: str,
        source_file: str,
        target_file: str,
        all_refs: list,
        source_package: str,
        target_package: str,
    ) -> Dict[str, Any]:
        """Apply move: extract definition, update references, add imports."""
        errors = []
        modified_files = []

        try:
            # Read source file
            src_path = Path(source_file).resolve()
            if not src_path.exists():
                return {
                    "status": "error",
                    "message": f"Source file not found: {source_file}",
                }

            content = src_path.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines(True)

            # Find definition start line
            def_line = None
            for d in self.resolve_symbol_index().find_definitions(symbol):
                if Path(d.file_path).resolve().as_posix() == Path(source_file).resolve().as_posix():
                    def_line = d.line - 1  # 0-based
                    break

            if def_line is None:
                errors.append(f"Could not locate definition line for '{symbol}'")
            else:
                # Extract definition (simple heuristic: until next top-level def/class or EOF)
                extracted_lines = []
                i = def_line
                indent_level = len(lines[i]) - len(lines[i].lstrip())
                while i < len(lines):
                    line = lines[i]
                    if i > def_line and line.strip() and not line.startswith((' ', '\t')) and len(line) - len(line.lstrip()) <= indent_level:
                        if any(line.lstrip().startswith(kw) for kw in ('def ', 'class ', '@', 'async ')):
                            break
                    extracted_lines.append(line)
                    i += 1

                # Remove from source
                del lines[def_line:i]

                # Write back source
                src_path.write_text("".join(lines), encoding="utf-8")
                modified_files.append(source_file)

                # Write to target
                target_path = Path(target_file)
                target_path.parent.mkdir(parents=True, exist_ok=True)

                if target_path.exists():
                    target_content = target_path.read_text(encoding="utf-8")
                    target_lines = target_content.splitlines(True)
                    # Append at end with proper spacing
                    if target_lines and not target_lines[-1].endswith('\n'):
                        target_lines.append('\n')
                    target_lines.append('\n')
                    target_lines.extend(extracted_lines)
                else:
                    target_lines = extracted_lines

                target_path.write_text("".join(target_lines), encoding="utf-8")
                modified_files.append(target_file)

            # Update imports in all referencing files
            for ref in all_refs:
                ref_path = Path(ref.file_path).resolve()
                if not ref_path.exists():
                    continue
                if ref.file_path == source_file:
                    continue

                try:
                    ref_content = ref_path.read_text(encoding="utf-8")
                    old_import = f"from {source_package} import {symbol}"
                    new_import = f"from {target_package} import {symbol}"

                    if old_import in ref_content:
                        ref_content = ref_content.replace(old_import, new_import)
                        ref_path.write_text(ref_content, encoding="utf-8")
                        if ref.file_path not in modified_files:
                            modified_files.append(ref.file_path)
                except Exception as e:
                    errors.append(f"Error updating imports in {ref.file_path}: {e}")

        except Exception as e:
            errors.append(f"Move failed: {e}")

        # Update in-memory index — rename symbol's definition path
        try:
            self.resolve_symbol_index().rename_symbol(symbol, symbol)
        except Exception:
            pass

        status = "applied" if not errors else "partial"
        return {
            "status": status,
            "message": f"Moved '{symbol}' to {target_file}. Updated {len(modified_files)} files.",
            "files_modified": modified_files,
            "errors": errors if errors else None,
        }


class SafeDeleteTool(MCPTool):
    """safe_delete — safely delete a symbol with reference check (preview/apply)."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="safe_delete")

    @error_boundary("safe_delete", timeout_ms=20000)
    async def execute(
        self,
        symbol: str,
        file_path: str = "",
        force: bool = False,
        apply: bool = False,
    ) -> Dict[str, Any]:
        """Delete a symbol safely with reference check.

        Args:
            symbol: Symbol name to delete
            file_path: File to delete from (optional, uses first definition)
            force: If False, refuses if references exist
            apply: If False — preview only; if True — apply changes

        Returns:
            Preview or apply result.
        """
        await self.require_ready_project()
        si = self.resolve_symbol_index()

        # 1. Find all references
        defs = si.find_definitions(symbol)
        refs = si.find_references(symbol)

        if not defs:
            return {
                "status": "warning",
                "message": f"Symbol '{symbol}' not found in index.",
            }

        # Filter by file_path
        if file_path:
            target = Path(file_path).resolve().as_posix()
            defs = [d for d in defs if Path(d.file_path).resolve().as_posix() == target]

        if not defs:
            return {
                "status": "warning",
                "message": f"Symbol '{symbol}' not found in specified file.",
            }

        # Separate usages (non-definition references) from definition refs
        usages = [r for r in refs if not r.is_definition and r.symbol == symbol]

        # 2. Check for existing references
        if usages and not force:
            usage_files = set(r.file_path for r in usages)
            return {
                "status": "denied",
                "message": (
                    f"Symbol '{symbol}' has {len(usages)} usages across {len(usage_files)} files. "
                    f"Use force=True to delete anyway."
                ),
                "usages": [
                    {"file": r.file_path, "line": r.line, "kind": r.kind}
                    for r in usages[:20]
                ],
                "usage_count": len(usages),
                "usage_files": list(usage_files),
            }

        # 3. Build preview
        changes = []
        for d in defs:
            changes.append({
                "op": "delete_definition",
                "file": d.file_path,
                "line": d.line,
                "kind": d.kind,
            })

        if force and usages:
            for u in usages[:20]:
                changes.append({
                    "op": "delete_reference",
                    "file": u.file_path,
                    "line": u.line,
                })

        if not apply:
            return {
                "status": "preview",
                "message": f"Preview: delete '{symbol}' ({len(defs)} definition{'s' if len(defs)>1 else ''})",
                "changes": changes,
                "has_usages": len(usages) > 0,
                "usage_count": len(usages),
            }

        # 4. Apply changes
        result = await self._apply_delete(symbol, defs, usages if force else [])

        return result

    async def _apply_delete(
        self,
        symbol: str,
        defs: list,
        usages: list,
    ) -> Dict[str, Any]:
        """Apply deletion: remove definition lines and optionally reference lines."""
        errors = []
        modified_files = set()

        # Group by file
        from collections import defaultdict
        by_file = defaultdict(list)
        for d in defs:
            by_file[d.file_path].append((d.line, "definition"))
        for u in usages:
            by_file[u.file_path].append((u.line, "usage"))

        for file_path, lines_to_remove in by_file.items():
            try:
                abs_path = Path(file_path).resolve()
                if not abs_path.exists():
                    continue

                content = abs_path.read_text(encoding="utf-8")
                text_lines = content.splitlines(True)

                # Sort in reverse order
                lines_to_remove.sort(key=lambda x: x[0], reverse=True)

                removed = 0
                for line_no, _ in lines_to_remove:
                    idx = line_no - 1 - removed
                    if 0 <= idx < len(text_lines):
                        del text_lines[idx]
                        removed += 1

                abs_path.write_text("".join(text_lines), encoding="utf-8")
                modified_files.add(file_path)

            except Exception as e:
                errors.append(f"Error processing {file_path}: {e}")

        # Update in-memory index
        si = self.resolve_symbol_index()
        if hasattr(si, "remove_file"):
            for f in set(d.file_path for d in defs):
                try:
                    si.remove_file(f)
                except Exception:
                    pass

        status = "applied" if not errors else "partial"
        return {
            "status": status,
            "message": f"Deleted '{symbol}' from {len(modified_files)} file(s).",
            "files_modified": list(modified_files),
            "errors": errors if errors else None,
        }


__all__ = [
    "RenameSymbolTool",
    "AckImpactTool",
    "MoveSymbolTool",
    "SafeDeleteTool",
]
