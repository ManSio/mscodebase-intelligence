"""Operator catalogue: deterministic one-action mechanisms.

Every operator:
  * takes JSON-able args,
  * is bounded (max hits / lines / bytes of output),
  * never calls a model,
  * returns a dict that the executor puts into the journal.

Nothing here decides *what* to do — that is the brain's job. These are the
primitive tasks of the tree.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

MAX_GREP_HITS = 40
MAX_READ_LINES = 80
MAX_OUTPUT_CHARS = 2000
MAX_LS_ENTRIES = 60

SHELL_ALLOW = (
    "python -m pytest",
    "python -m ruff",
    "git status",
    "git diff",
    "git log",
    "git rev-parse",
)


class OpError(RuntimeError):
    pass


@dataclass(frozen=True)
class Op:
    name: str
    params: tuple[str, ...]
    doc: str
    fn: Callable[[Path, dict], dict]


def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _inside(repo: Path, rel: str) -> Path:
    p = (repo / rel).resolve()
    if not p.is_relative_to(repo.resolve()):
        raise OpError(f"path escapes the repository: {rel}")
    return p


def _slice_text(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n... [{len(text) - limit} chars cut]"


# --------------------------------------------------------------------- operators

def op_ls(repo: Path, args: dict) -> dict:
    rel = str(args.get("path") or ".")
    base = _inside(repo, rel)
    if not base.exists():
        raise OpError(f"no such path: {rel}")
    if base.is_file():
        return {"path": rel, "kind": "file", "size": base.stat().st_size}
    entries = sorted(p.name + ("/" if p.is_dir() else "") for p in base.iterdir())[:MAX_LS_ENTRIES]
    return {"path": rel, "kind": "dir", "entries": entries}


def op_grep(repo: Path, args: dict) -> dict:
    pattern = str(args.get("pattern") or "")
    if not pattern:
        raise OpError("grep needs a pattern")
    glob = str(args.get("glob") or "*.py")
    rx = re.compile(pattern)
    hits: list[dict] = []
    for path in sorted(repo.rglob(glob)):
        if any(part in {".git", "node_modules", "venv", "__pycache__", ".venv", "build", "dist",
                        ".factory", ".pytest_cache", "site-packages", ".ruff_cache"} for part in path.parts):
            continue
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                hits.append({"file": path.relative_to(repo).as_posix(), "line": i, "text": line.strip()[:200]})
                if len(hits) >= MAX_GREP_HITS:
                    return {"pattern": pattern, "hits": hits, "truncated": True}
    return {"pattern": pattern, "hits": hits, "truncated": False}


def op_read(repo: Path, args: dict) -> dict:
    rel = str(args.get("path") or "")
    if not rel:
        raise OpError("read needs a path")
    path = _inside(repo, rel)
    if not path.is_file():
        raise OpError(f"not a file: {rel}")
    start = max(1, int(args.get("start") or 1))
    end = start + min(MAX_READ_LINES, int(args.get("lines") or 40)) - 1
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    chunk = lines[start - 1:end]
    return {
        "path": rel,
        "start": start,
        "end": min(end, len(lines)),
        "total_lines": len(lines),
        "text": _slice_text("\n".join(f"{n:>5}: {t}" for n, t in zip(range(start, start + len(chunk)), chunk))),
    }


def op_outline(repo: Path, args: dict) -> dict:
    rel = str(args.get("path") or "")
    path = _inside(repo, rel)
    if path.suffix != ".py":
        raise OpError("outline supports only .py")
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    items = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            items.append({"kind": type(node).__name__, "name": node.name, "line": node.lineno})
    return {"path": rel, "symbols": items[:40]}


def op_run(repo: Path, args: dict) -> dict:
    cmd = str(args.get("cmd") or "")
    if not any(cmd.startswith(prefix) for prefix in SHELL_ALLOW):
        raise OpError(f"command is not in the allowlist: {cmd}")
    timeout = min(600, int(args.get("timeout") or 300))
    proc = subprocess.run(cmd, cwd=str(repo), shell=True, capture_output=True, text=True,
                          timeout=timeout, encoding="utf-8", errors="replace")
    out = (proc.stdout or "") + (proc.stderr or "")
    return {"cmd": cmd, "exit": proc.returncode, "tail": _slice_text(out.strip()[-MAX_OUTPUT_CHARS:])}


def op_write(repo: Path, args: dict) -> dict:
    rel = str(args.get("path") or "")
    content = str(args.get("content") or "")
    path = _inside(repo, rel)
    if not path.parent.exists():
        raise OpError(f"parent directory does not exist: {path.parent}")
    before = path.read_text(encoding="utf-8", errors="replace") if path.exists() else None
    path.write_text(content, encoding="utf-8", newline="\n")
    return {"path": rel, "bytes": len(content.encode("utf-8")),
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "created": before is None, "changed": before != content}


def op_git(repo: Path, args: dict) -> dict:
    sub = str(args.get("sub") or "status")
    if sub not in {"status", "diff", "log"}:
        raise OpError(f"git subcommand not allowed: {sub}")
    cmd = f"git {sub}" + (" --stat" if sub == "log" else "")
    return op_run(repo, {"cmd": cmd, "timeout": 60})


def op_deploy(repo: Path, args: dict) -> dict:
    """Dry-run only: shows what would run and refuses to execute."""
    script = str(args.get("script") or "")
    path = _inside(repo, script) if script else None
    exists = bool(path and path.exists())
    return {"script": script, "exists": exists, "executed": False,
            "reason": "deploy is dry-run by design; enable explicitly in a future operator"}


CATALOGUE: tuple[Op, ...] = (
    Op("ls", ("path",), "list a directory (<=60 entries)", op_ls),
    Op("grep", ("pattern", "glob"), "regex search, <=40 hits", op_grep),
    Op("read", ("path", "start", "lines"), "read <=80 numbered lines", op_read),
    Op("outline", ("path",), "top-level symbols of a .py file", op_outline),
    Op("run", ("cmd",), "run an allowlisted command, keep the tail", op_run),
    Op("write", ("path", "content"), "write a file inside the repo", op_write),
    Op("git", ("sub",), "git status|diff|log", op_git),
    Op("deploy", ("script",), "dry-run a deploy script", op_deploy),
)

BY_NAME = {op.name: op for op in CATALOGUE}


def catalogue_prompt() -> str:
    return "\n".join(f"- {op.name}({', '.join(op.params)}): {op.doc}" for op in CATALOGUE)


def describe() -> dict:
    return {"operators": [{"name": op.name, "params": list(op.params), "doc": op.doc} for op in CATALOGUE],
            "shell_allowlist": list(SHELL_ALLOW),
            "limits": {"grep_hits": MAX_GREP_HITS, "read_lines": MAX_READ_LINES,
                       "output_chars": MAX_OUTPUT_CHARS, "ls_entries": MAX_LS_ENTRIES},
            "catalogue_sha256": _sha([op.name for op in CATALOGUE])}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps(describe(), indent=2, ensure_ascii=False))
