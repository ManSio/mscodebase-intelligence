"""grep_code — regex search with AST-aware scope.

Adapted (MIT, attribution below) from JaredStewart/coderlm's `grep?scope=code`
(`server/src/ops/content.rs`), with one deliberate improvement: that
implementation decides per *line* and only inspects the first match on it, so a
line with both code and a comment is dropped entirely. Here every match is
checked by its own byte offset.

Why the tool exists: the MCP had no regex grep at all, so agents fell back to
`shell grep` — noisy (matches inside comments/strings) and outside the index.

Attribution: CodeRLM — https://github.com/JaredStewart/coderlm (MIT).
"""

from __future__ import annotations

import asyncio
import bisect
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.core.di_container import ServiceCollection
from src.core.error_handler import error_boundary
from src.mcp.tools.base import MCPTool

_MAX_FILE_BYTES = 1_000_000
_MAX_FILES = 4000
_MAX_PATTERN = 512
_MAX_DEPTH = 30
_NON_CODE_HINTS = ("comment", "string")


def _non_code_ranges(parser, source: bytes) -> List[Tuple[int, int]]:
    """Byte ranges of comment/string nodes (generic across grammars)."""
    try:
        tree = parser.parse(source)
    except Exception:  # noqa: BLE001 — битый файл не должен ронять поиск
        return []
    if tree is None:
        return []
    ranges: List[Tuple[int, int]] = []
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        node_type = (node.type or "").lower()
        if any(hint in node_type for hint in _NON_CODE_HINTS):
            ranges.append((node.start_byte, node.end_byte))
            continue
        stack.extend(node.children)
    return ranges


def _inside(offset: int, starts: List[int], ranges: List[Tuple[int, int]]) -> bool:
    """True when offset falls inside any excluded range (binary search)."""
    idx = bisect.bisect_right(starts, offset) - 1
    if idx < 0:
        return False
    start, end = ranges[idx]
    return start <= offset < end


def _line_starts(source: bytes) -> List[int]:
    starts = [0]
    for i, byte in enumerate(source):
        if byte == 10:
            starts.append(i + 1)
    return starts


class GrepCodeTool(MCPTool):
    """grep_code — regex search, optionally skipping comments and strings."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="grep_code")

    @error_boundary("grep_code", timeout_ms=45000)
    async def execute(
        self,
        pattern: str,
        scope: str = "code",
        file_path: str = "",
        max_matches: int = 50,
        context_lines: int = 0,
        project_root: str = "",
    ) -> str:
        pattern = (pattern or "").strip()
        if not pattern:
            return "grep_code: пустой pattern"
        if len(pattern) > _MAX_PATTERN:
            return f"grep_code: pattern длиннее {_MAX_PATTERN} символов"
        scope = (scope or "code").strip().lower()
        if scope not in ("code", "all"):
            return "grep_code: scope должен быть 'code' или 'all'"
        try:
            regex = re.compile(pattern.encode("utf-8"))
        except re.error as exc:
            return f"grep_code: невалидный regex — {exc}"

        root = Path(project_root).resolve() if project_root else Path(
            self.resolve_indexer().project_path
        ).resolve()
        if not root.exists():
            return f"grep_code: путь не существует — {root}"

        target = None
        if file_path:
            candidate = (root / file_path).resolve()
            if not candidate.is_relative_to(root):
                return "grep_code: file_path вне проекта"
            if not candidate.is_file():
                return f"grep_code: файл не найден — {file_path}"
            target = candidate

        result = await asyncio.to_thread(
            self._search,
            root,
            target,
            regex,
            scope,
            max(1, int(max_matches)),
            max(0, min(int(context_lines), 5)),
        )
        return self._format(root, pattern, scope, result)

    def _search(
        self,
        root: Path,
        target: Optional[Path],
        regex: re.Pattern,
        scope: str,
        max_matches: int,
        context_lines: int,
    ) -> Dict[str, Any]:
        from src.core.indexing.file_guard import FileGuard

        guard = FileGuard(root)
        parser = None
        if scope == "code":
            try:
                parser = self.resolve_parser()
            except Exception:  # noqa: BLE001 — без парсера остаётся scope=all
                parser = None

        files: List[Path] = []
        if target is not None:
            files = [target]
        else:
            base_depth = len(root.parts)
            for dirpath, dirnames, filenames in os.walk(root):
                depth = len(Path(dirpath).parts) - base_depth
                if depth >= _MAX_DEPTH:
                    dirnames[:] = []
                dirnames[:] = [
                    d for d in dirnames if not guard.should_skip_dir(d)
                ]
                for name in filenames:
                    files.append(Path(dirpath) / name)
                    if len(files) >= _MAX_FILES:
                        break
                if len(files) >= _MAX_FILES:
                    break

        started = time.perf_counter()
        matches: List[Dict[str, Any]] = []
        total = 0
        scanned = 0
        skipped_big = 0
        skipped_binary = 0

        for path in files:
            if guard.should_skip_file(path):
                continue
            try:
                if path.stat().st_size > _MAX_FILE_BYTES:
                    skipped_big += 1
                    continue
                source = path.read_bytes()
            except OSError:
                continue
            if b"\x00" in source[:8192]:
                skipped_binary += 1
                continue
            scanned += 1
            rel = str(path.relative_to(root)).replace(os.sep, "/")

            # Prefilter (2026-11-08): tree-sitter is used only to decide whether a
            # match sits inside a comment/string. A file whose bytes cannot match
            # the pattern has nothing to decide, and parsing it anyway made the
            # whole channel CPU-bound: on this repo (523 files) `_search` parsed
            # every file per call, took ~2.7 s alone and exceeded the 15 s channel
            # budget inside `investigate`, which runs it next to the semantic
            # channel under the same GIL. Result: `degraded: grep:timeout` on every
            # query of our own repository. The match set is unchanged — a file
            # with zero regex hits contributed zero matches either way.
            if not regex.search(source):
                continue

            ranges: List[Tuple[int, int]] = []
            starts: List[int] = []
            if scope == "code" and parser is not None:
                ts_parser = parser.parsers.get(path.suffix.lower())
                if ts_parser is not None:
                    ranges = _non_code_ranges(ts_parser, source)
                    if ranges:
                        ranges.sort()
                        starts = [r[0] for r in ranges]

            lines = source.split(b"\n")
            line_starts = _line_starts(source)

            for match in regex.finditer(source):
                if ranges and _inside(match.start(), starts, ranges):
                    continue
                total += 1
                if len(matches) >= max_matches:
                    continue
                line_no = bisect.bisect_right(line_starts, match.start())
                text = lines[line_no - 1].decode("utf-8", "replace").strip()
                entry: Dict[str, Any] = {"file": rel, "line": line_no, "text": text}
                if context_lines:
                    lo = max(0, line_no - 1 - context_lines)
                    hi = min(len(lines), line_no + context_lines)
                    entry["before"] = [
                        lines[i].decode("utf-8", "replace").rstrip()
                        for i in range(lo, line_no - 1)
                    ]
                    entry["after"] = [
                        lines[i].decode("utf-8", "replace").rstrip()
                        for i in range(line_no, hi)
                    ]
                matches.append(entry)

        return {
            "matches": matches,
            "total": total,
            "truncated": total > max_matches,
            "scanned": scanned,
            "skipped_big": skipped_big,
            "skipped_binary": skipped_binary,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }

    def _format(self, root: Path, pattern: str, scope: str, result: Dict[str, Any]) -> str:
        head = (
            f"📂 Project: {root}\n"
            f"🔍 grep_code: `{pattern}` — {result['total']} matches "
            f"(scope={scope}, {result['elapsed_ms']}ms, "
            f"files={result['scanned']}"
        )
        if result["skipped_big"] or result["skipped_binary"]:
            head += (
                f", big={result['skipped_big']}, binary={result['skipped_binary']}"
            )
        head += ")"
        lines = [head, ""]
        for m in result["matches"]:
            if m.get("before"):
                for b in m["before"]:
                    lines.append(f"      | {b}")
            lines.append(f"{m['file']}:{m['line']}: {m['text']}")
            for a in m.get("after", []):
                lines.append(f"      | {a}")
        if not result["matches"]:
            lines.append("ℹ️ nothing found")
        if result["truncated"]:
            lines.append("⚠️ truncated — увеличьте max_matches")
        return "\n".join(lines)
