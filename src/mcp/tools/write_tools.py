"""
write_tools.py — Write operations как единый meta-tool.

Заменяет 7 отдельных инструментов на один `write(action)`.
Оригинальные классы сохранены для обратной совместимости импортов.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.di_container import ServiceCollection
from src.core.error_handler import error_boundary
from src.core.indexing.symbol_index import SymbolIndex
from src.core.modification_guard import modification_guard
from src.mcp.tools.base import MCPTool

logger = logging.getLogger("mscodebase_server.write_tools")


def _atomic_write(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Атомарная запись: temp-файл в той же директории + os.replace.

    На Windows `write_text` неатомарна (truncate + write) — при краше
    процесса файл остаётся повреждённым. Паттерн из _apply_changes,
    применён ко всем точкам записи (P2-9 / Claude review КРИТ-1).
    """
    import tempfile

    tmp_fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".msc.tmp")
    try:
        # newline="\n": детерминированная запись (без \r\n-трансляции Windows).
        # Иначе SHA-256 логического текста != хэша байтов на диске →
        # пост-верификация ChangeIntent (WS4) падает на Windows.
        with os.fdopen(tmp_fd, "w", encoding=encoding, newline="\n") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _sha256_text(text: str) -> str:
    """SHA-256 строкового содержимого (для expected_hash в ChangeIntent)."""
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class _R(str):
    """str с dict-доступом (для совместимости тестов)."""
    _data: Dict[str, Any]

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
    - "replace"    — replace symbol body (preview/apply)
    """

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="write")
        self._write_lock = asyncio.Lock()
        self._lsp_client: Optional[Any] = None

    def _validate_file_in_project(self, file_path: str) -> Optional[str]:
        """Validate that file_path is within the project root.

        FileGuard: fail-closed. Если корень проекта не определяется — операция
        запрещается, а не молча пропускается (старое поведение разрешало
        запись в произвольные пути при недоступном indexer'е).

        Дополнительно проверяет SafePathManager.is_safe_to_process — не-ASCII
        пути, пробелы и длина >200 символов системой не обрабатываются
        (консистентно с indexer.index_file).

        Returns error message or None if valid."""
        try:
            indexer = self.resolve_indexer()
            project_root = Path(indexer.project_path).resolve()
        except Exception:
            return (
                f"Cannot validate path '{file_path}': project root unavailable. "
                f"Open a project in Zed first and retry."
            )

        resolved = Path(file_path).resolve()

        # SafePathManager guard: не-ASCII/пробелы/длинные пути не обрабатываются.
        path_manager = getattr(indexer, "path_manager", None)
        if path_manager is not None and not path_manager.is_safe_to_process(resolved):
            return (
                f"Path '{file_path}' is not safe to process: non-ASCII "
                f"characters, spaces, or length >200. Write operations on "
                f"such paths are disabled (SafePathManager guard)."
            )

        try:
            resolved.relative_to(project_root)
        except ValueError:
            return f"Path '{file_path}' is outside project root '{project_root}'"
        return None

    def _validate_identifier(self, name: str, context: str) -> Optional[str]:
        """Validate that name is a valid Python/JS/TS identifier.
        Returns error message or None if valid."""
        if not name:
            return None
        import re
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
            return f"Invalid {context} identifier: '{name}'. Must match [A-Za-z_][A-Za-z0-9_]*"
        return None

    # ── WS4: Execution Contract 2.0 (ChangeIntent / provenance) ──────────────
    # (a) base_commit + hashes фиксируются в ledger до/после записи;
    # (b) пост-верификация: expected_hash сверяется с диском.
    # Любая ошибка ledger'а НЕ ломает запись — только warning.

    def _contract_project_root(self) -> str:
        try:
            return str(Path(self.resolve_indexer().project_path))
        except Exception:  # noqa: BLE001
            return str(Path.cwd())

    def _contract_base_commit(self) -> str:
        try:
            from src.core.execution_contract import get_base_commit

            return get_base_commit(self._contract_project_root())
        except Exception:  # noqa: BLE001
            return ""

    def _contract_record(
        self,
        operation: str,
        file_path: str,
        before_hash: Optional[str],
        after_hash: Optional[str],
        expected_hash: Optional[str] = None,
        symbol: str = "",
        base_commit: str = "",
    ) -> Dict[str, Any]:
        """Записывает ChangeIntent в ledger (+ пост-верификация при expected_hash).

        Returns: dict {"verified": bool, ...} — пустой, если ledger недоступен.
        """
        try:
            from src.core.execution_contract import (
                ChangeIntent,
                ChangeIntentLedger,
                ExecutionContract,
            )

            if not base_commit:
                base_commit = self._contract_base_commit()
            intent = ChangeIntent(
                operation=operation,
                file=file_path,
                base_commit=base_commit,
                before_hash=before_hash or "",
                after_hash=after_hash or "",
                expected_hash=expected_hash or "",
                symbol=symbol,
            )
            ledger = ChangeIntentLedger(self._contract_project_root())
            if expected_hash:
                verify = ExecutionContract.verify_file_write(
                    file_path, expected_hash=expected_hash
                )
                intent.verified = bool(verify.get("verified"))
                ledger.record(intent)
                return verify
            ledger.record(intent)
            return {"verified": True, "recorded": True}
        except Exception as e:  # noqa: BLE001
            logger.warning(f"ChangeIntent record skipped for {file_path}: {e}")
            return {}

    @error_boundary("write", timeout_ms=30000)
    @modification_guard(pagerank_min=0.05, blast_min=10, ack_ttl=600.0)
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
        impact_token: str = "",
        check_types: bool = False,
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
            impact_token: HMAC token from guard DENY response (ack action only)
            check_types: Для replace/insert — прогнать результирующий файл через
                basedpyright и вернуть ошибки типов в ответе (не блокирует запись;
                синтаксическая ошибка результирующего файла блокирует всегда).
                Работает и в preview-режиме (apply=False) — ошибки видны ДО записи.
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
        file_path = kw.get("file_path", "")
        apply = kw["apply"]
        allow_collision = kw["allow_collision"]

        # Validate new_name is a valid identifier
        id_error = self._validate_identifier(new_name, "rename target")
        if id_error:
            return _R({"status": "error", "message": id_error})

        # Validate file_path is within project if provided
        if file_path:
            path_error = self._validate_file_in_project(file_path)
            if path_error:
                return _R({"status": "error", "message": path_error})

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
            return "\u2757 **Error:** Provide either file_path or symbol."
        impact_token = kw.get("impact_token", "")
        if not impact_token:
            return (
                "\u2757 **Error:** `impact_token` is required. "
                "Get it from the guard's DENY response or impact_analysis output."
            )
        result = _ack(target, impact_token)
        if result["status"] == "denied":
            return f"\u2757 **Denied:** {result['message']}"
        ttl = result.get("ttl_seconds", 600)
        return f"\u2705 **Impact acknowledged** for `{target}` (TTL={ttl}s)"

    async def _action_move(self, **kw):
        await self.require_ready_project()
        si = self.resolve_symbol_index()
        symbol = kw["symbol"]
        to_file = kw["to_file"]
        file_path = kw.get("file_path", "")
        apply = kw["apply"]

        # Validate symbol is a valid identifier
        id_error = self._validate_identifier(symbol, "move target")
        if id_error:
            return _R({"status": "error", "message": id_error})

        # Validate to_file is within project
        path_error = self._validate_file_in_project(to_file)
        if path_error:
            return _R({"status": "error", "message": path_error})

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
        file_path = kw.get("file_path", "")
        force = kw["force"]
        apply = kw["apply"]

        # Validate symbol is a valid identifier
        id_error = self._validate_identifier(symbol, "delete target")
        if id_error:
            return _R({"status": "error", "message": id_error})

        # Validate file_path is within project if provided
        if file_path:
            path_error = self._validate_file_in_project(file_path)
            if path_error:
                return _R({"status": "error", "message": path_error})

        if not symbol:
            return {"status": "error", "message": "Provide symbol for safe_delete."}

        defs = si.find_definitions(symbol)
        if not defs:
            return {"status": "warning", "message": f"Symbol '{symbol}' not found."}

        if file_path:
            target = Path(file_path).resolve().as_posix()
            defs = [d for d in defs if Path(d.file_path).resolve().as_posix() == target]

        all_refs = si.find_all_references(symbol)
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
        file_path = kw.get("file_path", "")
        apply = kw["apply"]

        # Validate symbol is a valid identifier
        id_error = self._validate_identifier(symbol, "replace target")
        if id_error:
            return _R({"status": "error", "message": id_error})

        # Validate file_path is within project if provided
        if file_path:
            path_error = self._validate_file_in_project(file_path)
            if path_error:
                return _R({"status": "error", "message": path_error})

        if not symbol or not new_code:
            return "🚫 **Error:** Provide symbol and new_code for replace."

        defs = si.find_definitions(symbol)
        if not defs:
            return f"🚫 **Error:** Symbol '{symbol}' not found."

        if file_path:
            target = Path(file_path).resolve().as_posix()
            defs = [d for d in defs if Path(d.file_path).resolve().as_posix() == target]

        if not defs:
            return f"🚫 **Error:** Symbol '{symbol}' not found in specified file."

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
            preview_msg = (
                f"🔍 **Preview:** replace `{symbol}` in `{source_file}` (line {source_def.line})\n\n"
                f"Old: {len(original_lines)} lines → New: {len(new_code.splitlines())} lines"
            )
            if kw.get("check_types", False) and source_file.endswith(".py"):
                assembled = "".join(
                    lines[:start_idx]
                    + self._indent_new_lines(new_code, len(lines[start_idx]) - len(lines[start_idx].lstrip()))
                    + lines[end_idx:]
                )
                preflight = await self._preflight_validate(source_file, assembled, check_types=True)
                preview_msg += self._preflight_note(preflight)
            return preview_msg

        new_lines_list = self._indent_new_lines(
            new_code, len(lines[start_idx]) - len(lines[start_idx].lstrip())
        )

        # P3-8 audit: синтаксис-валидация new_code перед записью (Python-файлы),
        # чтобы пользователь не получил сломанный файл без предупреждения.
        if source_file.endswith(".py"):
            try:
                import ast as _ast

                _ast.parse(new_code)
            except SyntaxError as _se:
                return (
                    f"🚫 **Error:** new_code содержит синтаксическую ошибку: {_se}. "
                    f"Запись отменена — файл не изменён."
                )

        lines[start_idx:end_idx] = new_lines_list
        preflight = await self._preflight_validate(
            source_file, "".join(lines), check_types=kw.get("check_types", False)
        )
        if preflight is not None:
            blocking, pmsg = preflight
            if blocking:
                return _R({"status": "error", "message": pmsg})
            preflight_note = pmsg
        else:
            preflight_note = ""
        _atomic_write(abs_path, "".join(lines))
        await self._invalidate_lsp_cache(source_file)
        try:
            si.remove_file(source_file)
        except Exception as _si_err:
            # Stale symbol cache — последующие get_symbol_info вернут устаревшие данные
            logger.debug(f"remove_file из symbol index не удался: {_si_err}")

        msg = f"✅ **Replaced** `{symbol}` in `{source_file}` ({len(original_lines)} → {len(new_lines_list)} lines)"
        if preflight_note:
            msg += f"\n\n⚠️ **Preflight:** {preflight_note}"
        return msg

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

        if not defs:
            return f"🚫 **Error:** Symbol '{anchor_symbol}' not found in specified file."

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
            preview_msg = f"🔍 **Preview:** insert {position} `{anchor_symbol}` in `{source_file}`"
            if kw.get("check_types", False) and source_file.endswith(".py"):
                new_lines = self._build_insert_lines(new_code, position, insert_at, lines)
                assembled = "".join(lines[:insert_at] + new_lines + lines[insert_at:])
                preflight = await self._preflight_validate(source_file, assembled, check_types=True)
                preview_msg += self._preflight_note(preflight)
            return preview_msg

        new_lines = self._build_insert_lines(new_code, position, insert_at, lines)

        lines[insert_at:insert_at] = new_lines
        preflight = await self._preflight_validate(
            source_file, "".join(lines), check_types=kw.get("check_types", False)
        )
        if preflight is not None:
            blocking, pmsg = preflight
            if blocking:
                return _R({"status": "error", "message": pmsg})
            preflight_note = pmsg
        else:
            preflight_note = ""
        _atomic_write(abs_path, "".join(lines))
        await self._invalidate_lsp_cache(source_file)
        msg = f"✅ **Inserted {position}** `{anchor_symbol}` in `{source_file}` (+{len(new_lines)} lines)"
        if preflight_note:
            msg += f"\n\n⚠️ **Preflight:** {preflight_note}"
        return msg

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
        # Корень проекта нужен, чтобы генерировать dotted-импорт
        # относительно проекта, а не абсолютный Windows-путь
        # (иначе получаем невалидный `from D:\.Project... import X`).
        try:
            root = Path(self.resolve_indexer().project_path).resolve()
            rel = p.relative_to(root)
        except Exception:
            rel = p
        parts = list(rel.with_suffix("").parts)
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

    def _get_lsp_client(self) -> Optional[Any]:
        if self._lsp_client is None:
            try:
                from src.core.lsp_client import LspClient
                from src.core.project_resolution import resolve_project_root
                self._lsp_client = LspClient(project_root=resolve_project_root())
            except Exception:
                self._lsp_client = False
        return self._lsp_client if self._lsp_client is not False else None

    async def close(self) -> None:
        """Останавливает лениво-стартованный LSP-клиент (если создан).

        WriteTool-инстансы живут по вызову/по тесту, а rename/preflight
        поднимают реальный basedpyright-субпроцесс. Без явного закрытия
        процесс и его asyncio-транспорт висят до GC →
        PytestUnraisableExceptionWarning: unclosed transport (Windows Proactor).
        """
        lsp = self._lsp_client
        self._lsp_client = None
        if lsp is not None and not isinstance(lsp, bool):
            try:
                await lsp.stop()
            except Exception as exc:
                logger.debug("LSP close failed: %s", exc)

    def _indent_new_lines(self, new_code: str, base_indent: int) -> List[str]:
        """Разбивает new_code на строки и выравнивает отступы под base_indent.

        Используется и в apply-, и в preview-пути (preview+check_types должен
        собирать тот же результирующий файл, что и запись).
        """
        new_lines_list = new_code.splitlines(True)
        if new_lines_list and base_indent > 0:
            indented = []
            for i, nl in enumerate(new_lines_list):
                indented.append(nl if i == 0 or not nl.strip() else " " * base_indent + nl)
            new_lines_list = indented
        return new_lines_list

    @staticmethod
    def _build_insert_lines(new_code: str, position: str, insert_at: int, lines: list) -> List[str]:
        """Строит блок строк для вставки (нормализация переносов и пустых строк)."""
        new_lines = new_code.splitlines(True)
        if new_lines and new_lines[-1].strip() != '':
            new_lines.append('\n')
        if position == "after" and insert_at < len(lines) and lines[insert_at - 1].strip() != '':
            new_lines.insert(0, '\n')
        return new_lines

    @staticmethod
    def _preflight_note(preflight) -> str:
        """Форматирует результат _preflight_validate для preview-сообщения."""
        if preflight is None:
            return "\n\n✅ **Preflight:** типовые ошибки не найдены"
        blocking, msg = preflight
        icon = "🚫" if blocking else "⚠️"
        return f"\n\n{icon} **Preflight:** {msg}"

    async def _preflight_validate(self, file_path: str, new_content: str, check_types: bool) -> Optional[tuple]:
        """Pre-flight валидация результирующего файла ПЕРЕД записью.

        - compile() всего файла: жёсткий гейт — синтаксическая ошибка
          блокирует запись (ловит IndentationError/TabError, которые
          ast.parse фрагмента в _action_replace не видит).
        - check_types=True для Python: LSP-диагностика нового контента через
          preflight_content (advisory — запись НЕ блокируется: агент может
          быть в середине рефакторинга, часть типов ещё не согласована).

        Returns:
            None — чисто.
            (True, message) — блокирующая ошибка (синтаксис результирующего файла).
            (False, note) — advisory (ошибки типов / LSP недоступен / таймаут).
        """
        if file_path.endswith(".py"):
            try:
                compile(new_content, file_path, "exec")
            except SyntaxError as exc:
                return (True, f"Синтаксическая ошибка в результирующем файле: {exc}. Запись отменена — файл не изменён.")
        if not check_types or not file_path.endswith(".py"):
            return None
        lsp = self._get_lsp_client()
        if lsp is None:
            return (False, "Проверка типов пропущена: LSP (basedpyright) недоступен.")
        try:
            diags = await asyncio.wait_for(
                lsp.preflight_content(file_path, new_content),
                timeout=6.0,
            )
        except asyncio.TimeoutError:
            return (False, "Проверка типов: таймаут basedpyright, пропущено.")
        except Exception as exc:
            logger.debug("preflight type check failed for %s: %s", file_path, exc)
            return (False, "Проверка типов: ошибка LSP, пропущено.")
        errors = [d for d in diags if d.get("severity") == 1]
        if errors:
            lines = []
            for d in errors[:5]:
                ln = d.get("range", {}).get("start", {}).get("line", 0) + 1
                lines.append(f"- L{ln}: {d.get('message', '')}")
            more = f"… и ещё {len(errors) - 5}" if len(errors) > 5 else ""
            return (False, f"Найдено ошибок типов: {len(errors)}\n" + "\n".join(lines) + (more and f"\n{more}" or ""))
        return None

    async def _invalidate_lsp_cache(self, file_path: str):
        """Переоткрыть файл в LSP, чтобы language server не держал stale content.

        После прямого write_text в обход LSP pyright продолжает работать со
        старым содержимым файла. close+open заставляет его перечитать файл.
        Ничего не делает, если LSP не запущен (lazy-start не форсируется).
        """
        lsp = self._get_lsp_client()
        if lsp is None:
            return
        try:
            if await lsp.is_ready():
                await lsp.close_file(file_path)
                await lsp.open_file(file_path)
        except Exception as exc:
            logger.debug("LSP cache invalidation failed for %s: %s", file_path, exc)

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

        # DocSync: авто-обновление .md файлов после переименования
        try:
            from src.core.doc_sync_engine import DocSyncEngine
            project_root = str(Path(self.resolve_indexer().project_path))
            if project_root:
                engine = DocSyncEngine(project_root)
                report = engine.apply_rename(old_name, new_name)
                if report.auto_fixed > 0:
                    logger.info("📝 DocSync: auto-fixed %d references in docs (%s → %s)",
                                report.auto_fixed, old_name, new_name)
        except Exception as e:
            logger.warning("DocSync rename hook failed: %s", e)

        return {"status": "applied", "message": f"Renamed '{old_name}' -> '{new_name}' in {len(result.get('files', []))} files.", "changes_applied": len(changes), "files": result.get("files", []), "errors": result.get("errors")}

    async def _apply_changes(self, changes: List[Dict]) -> Dict[str, Any]:
        by_file = {}
        for c in changes:
            by_file.setdefault(c["file"], []).append(c)

        applied = 0
        errors = []
        files_modified = []

        # WS4: base_commit резолвим один раз на вызов (в потоке, чтобы не
        # блокировать event loop git-вызовом; кэш TTL=30с в execution_contract).
        base_commit = ""
        try:
            base_commit = await asyncio.to_thread(self._contract_base_commit)
        except Exception:  # noqa: BLE001
            pass

        for file_path, file_changes in by_file.items():
            try:
                abs_path = Path(file_path).resolve()
                if not abs_path.exists():
                    errors.append(f"File not found: {file_path}")
                    continue
                content = abs_path.read_text(encoding="utf-8", errors="replace")
                lines = content.splitlines(True)
                before_hash = _sha256_text(content)
                file_changes.sort(key=lambda c: c["line"], reverse=True)
                for change in file_changes:
                    idx = change["line"] - 1
                    if 0 <= idx < len(lines):
                        new_line = lines[idx].replace(change["old"], change["new"], 1)
                        if new_line != lines[idx]:
                            lines[idx] = new_line
                            applied += 1
                intended = "".join(lines)
                _atomic_write(abs_path, intended)
                # WS4: ChangeIntent — provenance + пост-верификация.
                self._contract_record(
                    "replace",
                    str(abs_path),
                    before_hash=before_hash,
                    after_hash=_sha256_text(intended),
                    expected_hash=_sha256_text(intended),
                    base_commit=base_commit,
                )
                files_modified.append(file_path)
                await self._invalidate_lsp_cache(file_path)
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
                _atomic_write(abs_path, "".join(lines))
                files_modified.append(file_path)
                await self._invalidate_lsp_cache(file_path)
            except Exception as e:
                logger.warning(f"WorkspaceEdit apply error: {e}")

        return {"status": "applied", "message": f"LSP rename applied across {len(files_modified)} files.", "files": files_modified}

    def _uri_to_path(self, uri: str) -> Optional[str]:
        if not uri.startswith("file://"):
            return None
        from urllib.parse import unquote
        path = unquote(uri[7:])
        result = path[1:] if path.startswith("/") and len(path) > 2 and path[2] == ":" else path
        # Validate result is within project root
        try:
            project_root = Path(self.resolve_indexer().project_path).resolve()
        except Exception:
            return result
        try:
            Path(result).resolve().relative_to(project_root)
        except ValueError:
            return None
        return result

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
                before_hash = _sha256_text(content)
                lines_to_remove.sort(reverse=True)
                removed = 0
                # P3-7 audit: удаляем строку только если она действительно содержит
                # символ (защита от устаревших индексов после правок файла).
                short_name = symbol.split(".")[-1]
                for line_no in lines_to_remove:
                    idx = line_no - 1 - removed
                    if 0 <= idx < len(text_lines):
                        if short_name in text_lines[idx]:
                            del text_lines[idx]
                            removed += 1
                        else:
                            errors.append(
                                f"Line {line_no} in {file_path} no longer contains "
                                f"'{short_name}' — skipped (stale index?)"
                            )
                intended = "".join(text_lines)
                _atomic_write(abs_path, intended)
                # WS4: ChangeIntent для safe_delete (provenance + пост-верификация).
                self._contract_record(
                    "safe_delete",
                    str(abs_path),
                    before_hash=before_hash,
                    after_hash=_sha256_text(intended),
                    expected_hash=_sha256_text(intended),
                    symbol=short_name,
                )
                modified.add(file_path)
                await self._invalidate_lsp_cache(file_path)
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
                _atomic_write(src_path, "".join(lines))
                modified.append(source_file)
                target_path = Path(target_file)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                _atomic_write(target_path, "".join(extracted))
                modified.append(target_file)
                await self._invalidate_lsp_cache(source_file)
                await self._invalidate_lsp_cache(target_file)

            for ref in all_refs:
                if ref.file_path == source_file:
                    continue
                ref_path = Path(ref.file_path).resolve()
                if ref_path.exists():
                    ref_content = ref_path.read_text(encoding="utf-8")
                    ref_content = ref_content.replace(f"from {source_package} import {symbol}", f"from {target_package} import {symbol}")
                    _atomic_write(ref_path, ref_content)
                    modified.append(ref.file_path)
                    await self._invalidate_lsp_cache(ref.file_path)
        except Exception as e:
            errors.append(str(e))

        return {"status": "applied" if not errors else "partial", "message": f"Moved '{symbol}' to {target_file}. Updated {len(set(modified))} files.", "files_modified": list(set(modified)), "errors": errors if errors else None}


__all__ = ["WriteTool"]
