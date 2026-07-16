"""
write_tools.py — Write operations как единый meta-tool.

Заменяет 7 отдельных инструментов на один `write(action)`.
Оригинальные классы сохранены для обратной совместимости импортов.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.di_container import ServiceCollection
from src.core.error_handler import error_boundary
from src.core.indexing.symbol_index import SymbolIndex
from src.mcp.tools.base import MCPTool

logger = logging.getLogger("mscodebase_server.write_tools")

class _R(str):
    """str с dict-доступом (для совместимости тестов)."""
    def __new__(cls, data):
        s = data.get('status', '')
        m = data.get('message', '')
        icon = {'preview': '🔍', 'applied': '✅', 'warning': '⚠️', 'error': '🚫', 'denied': '🚫'}.get(s, 'ℹ️')
        text = f"{icon} **{s.title()}:** {m}\n"
        instance = str.__new__(cls, text)
        instance._data = data
        return instance
    def __getitem__(self, key):
        return self._data[key]
    def __contains__(self, item):
        return item in self._data or str(item).lower() in str(self).lower()
    def get(self, key, default=None):
        return self._data.get(key, default)
    def keys(self):
        return self._data.keys()


class WriteTool(MCPTool):
    """write — единый инструмент для всех write-операций.

    Доступные action:
    - "rename"     — rename a symbol across all files (preview/apply)
    - "ack"        — acknowledge impact for modification guard
    - "move"       — move a symbol to another file (preview/apply)
    - "safe_delete" — delete a symbol with reference check (preview/apply)
    - "replace"    — replace a symbol's body (preview/apply)
    - "insert_before" — insert code before a symbol
    - "insert_after"  — insert code after a symbol
    """

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="write")
        self._lsp_client = None

    @error_boundary("write", timeout_ms=30000)
    async def execute(
        self,
        action: str,
        # rename parameters
        old_name: str = "",
        new_name: str = "",
        # move parameters
        symbol: str = "",
        to_file: str = "",
        # general
        file_path: str = "",
        anchor_symbol: str = "",
        new_code: str = "",
        allow_collision: bool = False,
        force: bool = False,
        apply: bool = False,
    ) -> str:
        """Execute a write operation.

        Args:
            action: One of: rename, ack, move, safe_delete, replace, insert_before, insert_after
            old_name: Current symbol name (rename)
            new_name: New symbol name (rename)
            symbol: Symbol to move or delete (move, safe_delete)
            to_file: Target file path (move)
            file_path: File to operate on (optional, uses first definition)
            anchor_symbol: Symbol to insert before/after (insert_before, insert_after)
            new_code: New code to replace or insert (replace, insert_before, insert_after)
            allow_collision: Allow name collision (rename)
            force: Force delete with references (safe_delete)
            apply: Apply changes (False = preview only)
        """

        action_map = {
            "rename": self._action_rename,
            "ack": self._action_ack,
            "move": self._action_move,
            "safe_delete": self._action_safe_delete,
            "replace": self._action_replace,
            "insert_before": self._action_insert_before,
            "insert_after": self._action_insert_after,
        }

        handler = action_map.get(action)
        if handler is None:
            return (
                f"🚫 **Unknown action:** `{action}`\n\n"
                f"Available: rename, ack, move, safe_delete, replace, insert_before, insert_after"
            )

        # Вызываем хендлер с параметрами (без служебных ключей)
        kwargs = {k: v for k, v in locals().items() 
                  if k not in ('self', 'action', 'handler', 'kwargs', 'action_map')}
        return await handler(**kwargs)

    async def _action_rename(self, **kw):
        """Rename a symbol across all files."""
        await self.require_ready_project()
        si = self.resolve_symbol_index()
        old_name = kw["old_name"]
        new_name = kw["new_name"]
        file_path = kw["file_path"]
        apply = kw["apply"]
        allow_collision = kw["allow_collision"]

        if not old_name or not new_name:
            return _R({"status": "error", "message": "Provide old_name and new_name for rename."})

        defs = si.find_definitions(old_name)
        all_refs = si.find_all_references(old_name)

        if not all_refs:
            all_refs = self._find_references_fallback(old_name, si)

        if not all_refs and not defs:
            return _R({"status": "warning", "message": f"Symbol '{old_name}' not found in index."})

        if file_path:
            target = Path(file_path).resolve().as_posix()
            all_refs = [r for r in all_refs if Path(r.file_path).resolve().as_posix() == target]
            defs = [d for d in defs if Path(d.file_path).resolve().as_posix() == target]

        if not all_refs:
            return _R({"status": "warning", "message": f"Symbol '{old_name}' not found in file '{file_path}'."})

        if not allow_collision:
            collision = self._check_collision(new_name, all_refs, si)
            if collision:
                return _R({"status": "error", "message": f"Symbol '{new_name}' already exists. Use allow_collision=True.", "collision": collision})

        return await self._rename_with_lsp_fallback(old_name, new_name, defs, all_refs, apply, allow_collision, si)

    async def _action_ack(self, **kw) -> str:
        from src.core.modification_guard import ack_impact as _ack
        target = kw["file_path"] or kw["symbol"]
        if not target:
            return "🚫 **Error:** Provide either file_path or symbol."
        result = _ack(target)
        ttl = result.get("ttl_seconds", 600)
        return f"✅ **Impact acknowledged** for `{target}` (TTL={ttl}s)"

    async def _action_move(self, **kw):
        await self.require_ready_project()
        si = self.resolve_symbol_index()
        symbol = kw["symbol"]
        to_file = kw["to_file"]
        file_path = kw["file_path"]
        apply = kw["apply"]

        if not symbol or not to_file:
            return _R({"status": "error", "message": "Provide symbol and to_file for move."})

        defs = si.find_definitions(symbol)
        if not defs:
            return _R({"status": "warning", "message": f"Symbol '{symbol}' not found in index."})

        if file_path:
            target = Path(file_path).resolve().as_posix()
            defs = [d for d in defs if Path(d.file_path).resolve().as_posix() == target]

        if not defs:
            return {"status": "warning", "message": f"Symbol '{symbol}' not found in specified file."}

        source_def = defs[0]
        source_file = source_def.file_path
        all_refs = si.find_all_references(symbol)
        target_path = Path(to_file)
        if not target_path.is_absolute():
            target_path = Path(self.resolve_indexer().project_path) / to_file
        target_file = target_path.resolve().as_posix()
        source_package = self._infer_package(source_file)
        target_package = self._infer_package(target_file)

        changes = [{"op": "move_definition", "symbol": symbol, "from": source_file, "to": target_file, "line": source_def.line, "kind": source_def.kind}]
        updated_imports = set()
        for ref in all_refs:
            if ref.file_path != source_file and ref.file_path not in updated_imports:
                updated_imports.add(ref.file_path)
                changes.append({"op": "update_import", "file": ref.file_path, "old_import": f"from {source_package} import {symbol}", "new_import": f"from {target_package} import {symbol}"})

        if not apply:
            return {"status": "preview", "message": f"Preview: move '{symbol}' -> {to_file} ({len(changes)} changes)", "changes": changes, "source_file": source_file, "target_file": target_file, "symbol_kind": source_def.kind}

        return await self._apply_move(symbol, source_file, target_file, all_refs, source_package, target_package)

    async def _action_safe_delete(self, **kw):
        await self.require_ready_project()
        si = self.resolve_symbol_index()
        symbol = kw["symbol"]
        file_path = kw["file_path"]
        force = kw["force"]
        apply = kw["apply"]

        if not symbol:
            return {"status": "error", "message": "Provide symbol for safe_delete."}

        defs = si.find_definitions(symbol)
        if not defs:
            return {"status": "warning", "message": f"Symbol '{symbol}' not found."}

        if file_path:
            target = Path(file_path).resolve().as_posix()
            defs = [d for d in defs if Path(d.file_path).resolve().as_posix() == target]

        all_refs = si.find_references(symbol)
        usages = [r for r in all_refs if not r.is_definition and r.symbol == symbol]
        if usages and not force:
            usage_files = list(set(r.file_path for r in usages))
            return {"status": "denied", "message": f"Symbol '{symbol}' has {len(usages)} usages across {len(usage_files)} files. Use force=True to delete anyway.", "usages": [{"file": r.file_path, "line": r.line, "kind": r.kind} for r in usages[:20]], "usage_count": len(usages), "usage_files": usage_files}

        changes = [{"op": "delete_definition", "file": d.file_path, "line": d.line, "kind": d.kind} for d in defs]
        if force and usages:
            for u in usages[:20]:
                changes.append({"op": "delete_reference", "file": u.file_path, "line": u.line})

        if not apply:
            return {"status": "preview", "message": f"Preview: delete '{symbol}' ({len(defs)} definition{'s' if len(defs)>1 else ''})", "changes": changes, "has_usages": len(usages) > 0, "usage_count": len(usages)}

        return await self._apply_delete(symbol, defs, usages if force else [])

    async def _action_replace(self, **kw) -> str:
        await self.require_ready_project()
        si = self.resolve_symbol_index()
        symbol = kw["symbol"]
        new_code = kw["new_code"]
        file_path = kw["file_path"]
        apply = kw["apply"]

        if not symbol or not new_code:
            return "🚫 **Error:** Provide symbol and new_code for replace."

        defs = si.find_definitions(symbol)
        if not defs:
            return f"🚫 **Error:** Symbol '{symbol}' not found."

        if file_path:
            target = Path(file_path).resolve().as_posix()
            defs = [d for d in defs if Path(d.file_path).resolve().as_posix() == target]

        source_def = defs[0]
        source_file = source_def.file_path
        abs_path = Path(source_file).resolve()
        if not abs_path.exists():
            return f"🚫 **Error:** File not found: `{source_file}`"

        content = abs_path.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines(True)
        start_idx = source_def.line - 1
        end_idx = self._find_body_end(lines, start_idx)
        original_lines = lines[start_idx:end_idx]

        if not apply:
            return f"🔍 **Preview:** replace `{symbol}` in `{source_file}` (line {source_def.line})\n\nOld: {len(original_lines)} lines → New: {len(new_code.splitlines())} lines"

        new_lines_list = new_code.splitlines(True)
        base_indent = len(lines[start_idx]) - len(lines[start_idx].lstrip())
        if new_lines_list and base_indent > 0:
            indented = []
            for i, nl in enumerate(new_lines_list):
                indented.append(nl if i == 0 or not nl.strip() else " " * base_indent + nl)
            new_lines_list = indented

        lines[start_idx:end_idx] = new_lines_list
        abs_path.write_text("".join(lines), encoding="utf-8")
        try:
            si.remove_file(source_file)
        except Exception:
            pass

        return f"✅ **Replaced** `{symbol}` in `{source_file}` ({len(original_lines)} → {len(new_lines_list)} lines)"

    async def _action_insert_before(self, **kw) -> str:
        return await self._action_insert("before", **kw)

    async def _action_insert_after(self, **kw) -> str:
        return await self._action_insert("after", **kw)

    async def _action_insert(self, position: str, **kw) -> str:
        await self.require_ready_project()
        si = self.resolve_symbol_index()
        anchor_symbol = kw["anchor_symbol"]
        new_code = kw["new_code"]
        file_path = kw["file_path"]
        apply = kw["apply"]

        if not anchor_symbol or not new_code:
            return f"🚫 **Error:** Provide anchor_symbol and new_code for insert_{position}."

        defs = si.find_definitions(anchor_symbol)
        if not defs:
            return f"🚫 **Error:** Symbol '{anchor_symbol}' not found."

        if file_path:
            target = Path(file_path).resolve().as_posix()
            defs = [d for d in defs if Path(d.file_path).resolve().as_posix() == target]

        source_def = defs[0]
        source_file = source_def.file_path
        abs_path = Path(source_file).resolve()
        if not abs_path.exists():
            return f"🚫 **Error:** File not found: `{source_file}`"

        content = abs_path.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines(True)
        anchor_idx = source_def.line - 1

        if position == "after":
            body_end = self._find_body_end(lines, anchor_idx)
            insert_at = body_end
        else:
            if anchor_idx > 0 and lines[anchor_idx - 1].strip() == '':
                insert_at = anchor_idx - 1
            else:
                insert_at = anchor_idx

        if not apply:
            return f"🔍 **Preview:** insert {position} `{anchor_symbol}` in `{source_file}`"

        new_lines = new_code.splitlines(True)
        if new_lines and new_lines[-1].strip() != '':
            new_lines.append('\n')
        if position == "after" and insert_at < len(lines) and lines[insert_at - 1].strip() != '':
            new_lines.insert(0, '\n')

        lines[insert_at:insert_at] = new_lines
        abs_path.write_text("".join(lines), encoding="utf-8")
        return f"✅ **Inserted {position}** `{anchor_symbol}` in `{source_file}` (+{len(new_lines)} lines)"

    # ─── Вспомогательные методы ─────────────────────────

    def _find_references_fallback(self, symbol: str, si: SymbolIndex) -> list:
        found = si.search_symbols(symbol)
        return found if found else []

    def _check_collision(self, new_name: str, refs: list, si: SymbolIndex) -> Optional[Dict]:
        target_files = set(r.file_path for r in refs)
        for file in target_files:
            if new_name in si.get_symbols_in_file(file):
                return {"existing_symbol": new_name, "in_files": [file]}
        return None

    def _build_changes(self, old_name: str, new_name: str, refs: list) -> List[Dict]:
        seen = set()
        changes = []
        for r in refs:
            key = (r.file_path, r.line)
            if key not in seen:
                seen.add(key)
                changes.append({"file": r.file_path, "line": r.line, "kind": r.kind, "old": old_name, "new": new_name})
        changes.sort(key=lambda c: (c["file"], c["line"]))
        return changes

    def _infer_package(self, file_path: str) -> str:
        p = Path(file_path).resolve()
        parts = p.as_posix().rstrip(".py").split("/")
        return ".".join(pt for pt in parts if pt)

    def _find_body_end(self, lines: list, def_line: int) -> int:
        if def_line >= len(lines):
            return def_line
        base_indent = len(lines[def_line]) - len(lines[def_line].lstrip())
        def_text = lines[def_line].rstrip()
        if def_text.rstrip().endswith(':'):
            after_colon = def_text.split(':', 1)[1].strip()
            if after_colon and not after_colon.startswith('#'):
                return def_line + 1
        for i in range(def_line + 1, len(lines)):
            stripped = lines[i].strip()
            if stripped and not stripped.startswith('#'):
                indent = len(lines[i]) - len(lines[i].lstrip())
                if indent <= base_indent:
                    return i
        return len(lines)

    # ─── LSP rename helpers ────────────────────────────

    def _get_lsp_client(self):
        if self._lsp_client is None:
            try:
                from src.core.lsp_client import LspClient
                from src.mcp.server import resolve_project_root
                self._lsp_client = LspClient(project_root=resolve_project_root())
            except Exception:
                self._lsp_client = False
        return self._lsp_client if self._lsp_client is not False else None

    async def _rename_with_lsp_fallback(self, old_name, new_name, defs, all_refs, apply, allow_collision, si):
        if not defs:
            return await self._apply_fallback_rename(old_name, new_name, all_refs, apply, si)

        lsp = self._get_lsp_client()
        if lsp is not None:
            warmed = 0
            seen = set()
            for ref in all_refs:
                if ref.file_path not in seen and len(seen) < 10:
                    seen.add(ref.file_path)
                    try:
                        if await lsp.open_file(ref.file_path):
                            warmed += 1
                    except Exception:
                        pass
            if warmed:
                await asyncio.sleep(0.3)

            try:
                edit = await asyncio.wait_for(
                    lsp.rename_symbol(defs[0].file_path, max(0, defs[0].line - 1), -1, new_name, old_name),
                    timeout=5.0,
                )
                if edit and (edit.get("changes") or edit.get("documentChanges")):
                    return await self._apply_workspace_edit(edit, old_name, new_name)
            except asyncio.TimeoutError:
                pass
            except Exception:
                pass

        return await self._apply_fallback_rename(old_name, new_name, all_refs, apply, si)

    async def _apply_fallback_rename(self, old_name, new_name, all_refs, apply, si):
        changes = self._build_changes(old_name, new_name, all_refs)
        if not apply:
            return {"status": "preview", "message": f"Preview: rename '{old_name}' -> '{new_name}' ({len(changes)} occurrences)", "changes": changes, "files_affected": len(set(c["file"] for c in changes)), "total_occurrences": len(changes)}

        result = await self._apply_changes(changes)
        si.rename_symbol(old_name, new_name)
        return {"status": "applied", "message": f"Renamed '{old_name}' -> '{new_name}' in {len(result.get('files', []))} files.", "changes_applied": len(changes), "files": result.get("files", []), "errors": result.get("errors")}

    async def _apply_changes(self, changes: List[Dict]) -> Dict[str, Any]:
        by_file = {}
        for c in changes:
            by_file.setdefault(c["file"], []).append(c)

        applied = 0
        errors = []
        files_modified = []

        for file_path, file_changes in by_file.items():
            try:
                abs_path = Path(file_path).resolve()
                if not abs_path.exists():
                    errors.append(f"File not found: {file_path}")
                    continue
                content = abs_path.read_text(encoding="utf-8", errors="replace")
                lines = content.splitlines(True)
                file_changes.sort(key=lambda c: c["line"], reverse=True)
                for change in file_changes:
                    idx = change["line"] - 1
                    if 0 <= idx < len(lines):
                        new_line = lines[idx].replace(change["old"], change["new"], 1)
                        if new_line != lines[idx]:
                            lines[idx] = new_line
                            applied += 1
                abs_path.write_text("".join(lines), encoding="utf-8")
                files_modified.append(file_path)
            except Exception as e:
                errors.append(f"Error processing {file_path}: {e}")

        return {"status": "applied" if not errors else "partial", "files": files_modified, "errors": errors}

    async def _apply_workspace_edit(self, edit: dict, old_name: str, new_name: str) -> dict:
        files_modified = []
        all_edits = []
        for uri, edits in edit.get("changes", {}).items():
            all_edits.append((uri, edits))
        for doc in edit.get("documentChanges", []):
            if "textDocument" in doc and "edits" in doc:
                all_edits.append((doc["textDocument"]["uri"], doc["edits"]))

        for uri, text_changes in all_edits:
            file_path = self._uri_to_path(uri)
            if not file_path:
                continue
            try:
                abs_path = Path(file_path).resolve()
                if not abs_path.exists():
                    continue
                content = abs_path.read_text(encoding="utf-8")
                lines = content.splitlines(True)
                text_changes.sort(key=lambda c: (c["range"]["start"]["line"], c["range"]["start"]["character"]), reverse=True)
                for change in text_changes:
                    start, end, new_text = change["range"]["start"], change["range"]["end"], change.get("newText", "")
                    if start["line"] == end["line"] and start["character"] == end["character"]:
                        idx = start["line"]
                        lines[idx] = lines[idx][:start["character"]] + new_text + lines[idx][start["character"]:]
                    else:
                        if start["line"] == end["line"]:
                            lines[start["line"]] = lines[start["line"]][:start["character"]] + new_text + lines[start["line"]][end["character"]:]
                        else:
                            first = lines[start["line"]]
                            lines[start["line"]] = first[:start["character"]] + new_text
                            del lines[start["line"] + 1:end["line"] + 1]
                abs_path.write_text("".join(lines), encoding="utf-8")
                files_modified.append(file_path)
            except Exception as e:
                logger.warning(f"WorkspaceEdit apply error: {e}")

        return {"status": "applied", "message": f"LSP rename applied across {len(files_modified)} files.", "files": files_modified}

    def _uri_to_path(self, uri: str) -> Optional[str]:
        if not uri.startswith("file://"):
            return None
        from urllib.parse import unquote
        path = unquote(uri[7:])
        return path[1:] if path.startswith("/") and len(path) > 2 and path[2] == ":" else path

    async def _apply_delete(self, symbol: str, defs: list, usages: list) -> dict:
        from collections import defaultdict
        by_file = defaultdict(list)
        for d in defs:
            by_file[d.file_path].append(d.line)
        for u in usages:
            by_file[u.file_path].append(u.line)

        modified = set()
        errors = []
        for file_path, lines_to_remove in by_file.items():
            try:
                abs_path = Path(file_path).resolve()
                if not abs_path.exists():
                    continue
                content = abs_path.read_text(encoding="utf-8")
                text_lines = content.splitlines(True)
                lines_to_remove.sort(reverse=True)
                removed = 0
                for line_no in lines_to_remove:
                    idx = line_no - 1 - removed
                    if 0 <= idx < len(text_lines):
                        del text_lines[idx]
                        removed += 1
                abs_path.write_text("".join(text_lines), encoding="utf-8")
                modified.add(file_path)
            except Exception as e:
                errors.append(f"Error processing {file_path}: {e}")

        return {"status": "applied" if not errors else "partial", "message": f"Deleted '{symbol}' from {len(modified)} file(s).", "files_modified": list(modified), "errors": errors if errors else None}

    async def _apply_move(self, symbol, source_file, target_file, all_refs, source_package, target_package) -> dict:
        errors = []
        modified = []
        try:
            src_path = Path(source_file).resolve()
            content = src_path.read_text(encoding="utf-8")
            lines = content.splitlines(True)
            si = self.resolve_symbol_index()
            defs = si.find_definitions(symbol)
            if defs:
                def_line = defs[0].line - 1
                base_indent = len(lines[def_line]) - len(lines[def_line].lstrip())
                extracted = []
                i = def_line
                while i < len(lines):
                    line = lines[i]
                    if i > def_line and line.strip() and not line.startswith((' ', '\t')) and len(line) - len(line.lstrip()) <= base_indent:
                        break
                    extracted.append(line)
                    i += 1
                del lines[def_line:i]
                src_path.write_text("".join(lines), encoding="utf-8")
                modified.append(source_file)
                target_path = Path(target_file)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_text("".join(extracted), encoding="utf-8")
                modified.append(target_file)

            for ref in all_refs:
                if ref.file_path == source_file:
                    continue
                ref_path = Path(ref.file_path).resolve()
                if ref_path.exists():
                    ref_content = ref_path.read_text(encoding="utf-8")
                    ref_content = ref_content.replace(f"from {source_package} import {symbol}", f"from {target_package} import {symbol}")
                    ref_path.write_text(ref_content, encoding="utf-8")
                    modified.append(ref.file_path)
        except Exception as e:
            errors.append(str(e))

        return {"status": "applied" if not errors else "partial", "message": f"Moved '{symbol}' to {target_file}. Updated {len(set(modified))} files.", "files_modified": list(set(modified)), "errors": errors if errors else None}


# ─── Оригинальные классы (для обратной совместимости импортов) ───


class RenameSymbolTool(MCPTool):
    def __init__(self, services):
        super().__init__(services, tool_name="rename_symbol_legacy")
        self._wrapped = WriteTool(services)
    @error_boundary("rename_symbol", timeout_ms=30000)
    async def execute(self, old_name="", new_name="", file_path="", apply=False, allow_collision=False, **kw):
        for a in ('require_ready_project', 'resolve_symbol_index', 'resolve_indexer', '_lsp_client', '_get_lsp_client'):
            if hasattr(self, a):
                setattr(self._wrapped, a, getattr(self, a))
        return await self._wrapped._action_rename(old_name=old_name, new_name=new_name, file_path=file_path, apply=apply, allow_collision=allow_collision)


class AckImpactTool(MCPTool):
    def __init__(self, services):
        super().__init__(services, tool_name="ack_impact_legacy")
        self._wrapped = WriteTool(services)
    @error_boundary("ack_impact", timeout_ms=5000)
    async def execute(self, file_path="", symbol="", **kw):
        for a in ('require_ready_project', 'resolve_symbol_index', 'resolve_indexer'):
            if hasattr(self, a): setattr(self._wrapped, a, getattr(self, a))
        return await self._wrapped._action_ack(**{**kw, "file_path": file_path, "symbol": symbol})


class MoveSymbolTool(MCPTool):
    def __init__(self, services):
        super().__init__(services, tool_name="move_symbol_legacy")
        self._wrapped = WriteTool(services)
    @error_boundary("move_symbol", timeout_ms=30000)
    async def execute(self, symbol="", to_file="", file_path="", apply=False, **kw):
        for a in ('require_ready_project', 'resolve_symbol_index', 'resolve_indexer'):
            if hasattr(self, a): setattr(self._wrapped, a, getattr(self, a))
        return await self._wrapped._action_move(symbol=symbol, to_file=to_file, file_path=file_path, apply=apply)


class SafeDeleteTool(MCPTool):
    def __init__(self, services):
        super().__init__(services, tool_name="safe_delete_legacy")
        self._wrapped = WriteTool(services)
    @error_boundary("safe_delete", timeout_ms=20000)
    async def execute(self, symbol="", file_path="", force=False, apply=False, **kw):
        for a in ('require_ready_project', 'resolve_symbol_index', 'resolve_indexer'):
            if hasattr(self, a): setattr(self._wrapped, a, getattr(self, a))
        return await self._wrapped._action_safe_delete(symbol=symbol, file_path=file_path, force=force, apply=apply)


class ReplaceSymbolTool(MCPTool):
    def __init__(self, services):
        super().__init__(services, tool_name="replace_symbol_legacy")
        self._wrapped = WriteTool(services)
    @error_boundary("replace_symbol", timeout_ms=30000)
    async def execute(self, symbol="", new_code="", file_path="", apply=False, **kw):
        for a in ('require_ready_project', 'resolve_symbol_index', 'resolve_indexer'):
            if hasattr(self, a): setattr(self._wrapped, a, getattr(self, a))
        return await self._wrapped._action_replace(symbol=symbol, new_code=new_code, file_path=file_path, apply=apply)


class InsertBeforeSymbolTool(MCPTool):
    def __init__(self, services):
        super().__init__(services, tool_name="insert_before_symbol_legacy")
        self._wrapped = WriteTool(services)
    @error_boundary("insert_before_symbol", timeout_ms=15000)
    async def execute(self, anchor_symbol="", new_code="", file_path="", apply=False, **kw):
        for a in ('require_ready_project', 'resolve_symbol_index', 'resolve_indexer'):
            if hasattr(self, a): setattr(self._wrapped, a, getattr(self, a))
        return await self._wrapped._action_insert_before(**{**kw, "anchor_symbol": anchor_symbol, "new_code": new_code, "file_path": file_path, "apply": apply})


class InsertAfterSymbolTool(MCPTool):
    def __init__(self, services):
        super().__init__(services, tool_name="insert_after_symbol_legacy")
        self._wrapped = WriteTool(services)
    @error_boundary("insert_after_symbol", timeout_ms=15000)
    async def execute(self, anchor_symbol="", new_code="", file_path="", apply=False, **kw):
        for a in ('require_ready_project', 'resolve_symbol_index', 'resolve_indexer'):
            if hasattr(self, a): setattr(self._wrapped, a, getattr(self, a))
        return await self._wrapped._action_insert_after(**{**kw, "anchor_symbol": anchor_symbol, "new_code": new_code, "file_path": file_path, "apply": apply})


__all__ = [
    "WriteTool",
    "RenameSymbolTool", "AckImpactTool", "MoveSymbolTool",
    "SafeDeleteTool", "ReplaceSymbolTool",
    "InsertBeforeSymbolTool", "InsertAfterSymbolTool",
]
