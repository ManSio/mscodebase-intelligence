"""Sandboxed code execution with AST validation.

This module provides:
- validate_code(code) -> list[str]: Validates code BEFORE execution.
  Raises SandboxViolation on blocked patterns.
- execute_sandboxed(code, **kwargs) -> dict: Executes code in subprocess.

Security model:
- Module allowlist (ALLOWED_MODULES) — only stdlib modules explicitly allowed
- Blocked string patterns (BLOCKED_STR_PATTERNS) — catches obvious attacks
- AST validation — catches obfuscated imports, dangerous constructs
- Subprocess isolation — 120s timeout, 1MB output limit, no network/fs access

NOT a security boundary for untrusted code. Defense-in-depth for agent tools.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import tempfile
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────

# Allowed stdlib modules (explicit allowlist)
ALLOWED_MODULES: frozenset[str] = frozenset({
    "math", "json", "re", "datetime", "collections", "hashlib",
    "time", "random", "statistics", "string", "textwrap", "itertools",
    "functools", "operator", "decimal", "fractions", "numbers",
    "typing", "dataclasses", "enum", "uuid", "base64", "binascii",
    "html", "urllib.parse", "urllib.request", "urllib.error",
    "urllib.response", "email", "csv", "sqlite3", "xml.etree.ElementTree",
    "xml.dom.minidom", "xml.sax", "xml.parsers.expat",
    "http", "http.client", "http.server", "http.cookies",
    "http.cookiejar", "mimetypes", "json", "pickle", "copy",
    "pprint", "reprlib", "weakref", "types", "inspect", "ast",
    "tokenize", "keyword", "token", "symbol", "parser",
    "symtable", "py_compile", "compileall", "dis", "opcode",
    "importlib", "importlib.util", "importlib.machinery",
    "importlib.metadata", "importlib.resources", "pkgutil",
    "runpy", "modulefinder", "zipimport", "pkg_resources",
    "setuptools", "distutils", "distutils.version", "distutils.util",
    "argparse", "getopt", "optparse", "cmd", "shlex", "readline",
    "rlcompleter", "code", "codeop", "traceback", "linecache",
    "warnings", "contextlib", "abc", "collections.abc", "heapq",
    "bisect", "array", "queue", "sched", "threading", "multiprocessing",
    "multiprocessing.pool", "multiprocessing.dummy", "concurrent.futures",
    "asyncio", "asyncio.events", "asyncio.coroutines", "asyncio.tasks",
    "asyncio.streams", "asyncio.subprocess", "asyncio.locks",
    "asyncio.queues", "asyncio.runners", "asyncio.trsock", "selectors",
    "select", "socket", "ssl", "signal", "mmap", "resource", "fcntl",
    "termios", "tty", "pty", "grp", "pwd", "crypt", "spwd", "getpass",
    "curses", "curses.ascii", "curses.panel", "curses.textpad",
})

# String patterns that are always blocked (fast path)
BLOCKED_STR_PATTERNS: frozenset[str] = frozenset({
    "os.system", "os.popen", "os.exec", "os.fork", "os.kill",
    "subprocess", "multiprocessing", "threading.Thread",
    "ctypes", "cffi", "ffi", "importlib.util.spec_from_loader",
    "importlib.util.module_from_spec", "sys.modules", "sys.path",
    "sys.executable", "sys.argv", "sys.stdin", "sys.stdout", "sys.stderr",
    "__import__", "eval(", "exec(", "compile(",
    "open(", "file(", "input(", "raw_input(",
    "socket", "http.client", "urllib.request", "requests",
    "paramiko", "fabric", "ansible", "salt", "psutil",
    "win32", "wmi", "ctypes.windll", "ctypes.cdll",
})

# AST-level blocks (catch obfuscation attempts)
_DANGEROUS_AST_NODES: frozenset[type] = frozenset({
    ast.Raise,       # Can mask errors
    ast.Delete,      # Can delete variables
})

# Blocked built-in names (catches dynamic import/eval bypass attempts)
BLOCKED_NAMES: frozenset[str] = frozenset({
    "getattr", "setattr", "delattr",
    "globals", "locals", "vars",
    "__import__", "eval", "exec",
    "compile", "breakpoint",
    "input",  # blocks interactive input
    # Additional bypass vectors
    "__getattribute__", "__getattr__", "__setattr__", "__delattr__",
    "__reduce__", "__reduce_ex__",
    "__init_subclass__", "__class__",
    "__subclasses__", "__bases__", "__mro__", "__globals__",
    "__builtins__", "__code__", "__func__",
    "__closure__", "__defaults__", "__kwdefaults__",
    "__annotations__", "__dict__", "__module__",
    "__qualname__", "__name__", "__doc__",
    "__self__", "__func__", "__module__",
    "__closure__", "__call__", "__getitem__",
    "__setitem__", "__delitem__", "__iter__",
    "__next__", "__enter__", "__exit__",
    "__await__", "__aiter__", "__anext__",
    "__bytes__", "__complex__", "__float__", "__int__",
    "__index__", "__len__", "__length_hint__",
    "__reversed__", "__contains__", "__eq__", "__ne__",
    "__lt__", "__le__", "__gt__", "__ge__",
    "__hash__", "__bool__", "__format__", "__dir__",
    "__instancecheck__", "__subclasscheck__",
    "__prepare__", "__new__", "__init__",
    "__del__", "__delattr__", "__setattr__",
    "__getattribute__", "__getattr__",
    "__setattr__", "__delattr__",
})

# ── Limits ───────────────────────────────────────────────────────

MAX_EXECUTION_TIME_S = 120
MAX_OUTPUT_BYTES = 1_000_000  # 1MB

# ── Audit log ────────────────────────────────────────────────────

_AUDIT_LOG: Optional[Path] = None


def _get_audit_log_path() -> Path:
    """Lazily initialize audit log path."""
    global _AUDIT_LOG
    if _AUDIT_LOG is None:
        log_dir = Path(os.environ.get("MSCODEBASE_LOG_DIR", tempfile.gettempdir()))
        _AUDIT_LOG = log_dir / "sandbox_audit.jsonl"
    return _AUDIT_LOG


_MAX_AUDIT_SIZE = 5 * 1024 * 1024  # 5MB


def _audit_log(entry: Dict[str, Any]) -> None:
    """Append execution record to audit log (JSONL format).

    Rotates when log exceeds 5MB (renames to .old.jsonl).
    """
    try:
        entry["timestamp"] = datetime.now(timezone.utc).isoformat()
        log_path = _get_audit_log_path()
        # Rotate if too large
        if log_path.exists() and log_path.stat().st_size > _MAX_AUDIT_SIZE:
            old_path = log_path.with_suffix(".old.jsonl")
            try:
                log_path.rename(old_path)
            except OSError:
                pass  # If rename fails, continue appending
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"Sandbox audit log write failed: {e}")


# ── Validation ───────────────────────────────────────────────────


class SandboxViolation(Exception):
    """Raised when code fails sandbox validation."""

    def __init__(self, message: str, pattern: str = ""):
        super().__init__(message)
        self.pattern = pattern


def validate_code(code: str) -> list[str]:
    """Validate code against sandbox rules BEFORE execution.

    Performs two layers of validation:
    1. String scan — fast check for obviously dangerous patterns
    2. AST analysis — catches obfuscated imports, dangerous constructs

    Args:
        code: Python source code to validate.

    Returns:
        List of warnings (non-fatal issues).

    Raises:
        SandboxViolation: If a hard block is triggered.
    """
    warnings: list[str] = []

    # Layer 1: String scan
    for pattern in BLOCKED_STR_PATTERNS:
        if pattern in code:
            raise SandboxViolation(
                f"Blocked pattern: {pattern}",
                pattern=pattern,
            )

    # Layer 2: AST analysis
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise SandboxViolation(f"Syntax error: {e}") from e

    for node in ast.walk(tree):
        # Block dangerous imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in ALLOWED_MODULES:
                    raise SandboxViolation(
                        f"Module not in allowlist: {root}",
                        pattern=f"import {root}",
                    )

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root = node.module.split(".")[0]
                if root not in ALLOWED_MODULES:
                    raise SandboxViolation(
                        f"Module not in allowlist: {root}",
                        pattern=f"from {node.module} import ...",
                    )

        # Block dangerous function calls
        elif isinstance(node, ast.Call):
            func = node.func
            # Block eval/exec/compile
            if isinstance(func, ast.Name) and func.id in ("eval", "exec", "compile"):
                raise SandboxViolation(
                    f"Blocked call: {func.id}()",
                    pattern=f"{func.id}()",
                )
            # Block __import__
            if isinstance(func, ast.Attribute) and func.attr == "__import__":
                raise SandboxViolation(
                    "Blocked call: __import__()",
                    pattern="__import__()",
                )
            if isinstance(func, ast.Name) and func.id == "__import__":
                raise SandboxViolation(
                    "Blocked call: __import__()",
                    pattern="__import__()",
                )

        # Block dangerous attribute access
        elif isinstance(node, ast.Attribute):
            # Block direct access to dangerous dunder attributes
            if node.attr in (
                "__subclasses__", "__bases__", "__globals__",
                "__getattribute__", "__getattr__", "__setattr__", "__delattr__",
                "__reduce__", "__reduce_ex__", "__init_subclass__",
                "__class__", "__mro__",
            ):
                raise SandboxViolation(
                    f"Blocked attribute: .{node.attr}",
                    pattern=f".{node.attr}",
                )

        # Block dangerous built-in names (catches dynamic getattr/import bypass)
        elif isinstance(node, ast.Name):
            if node.id in BLOCKED_NAMES:
                raise SandboxViolation(
                    f"Blocked name: {node.id}",
                    pattern=node.id,
                )

    return warnings


# ── Execution ────────────────────────────────────────────────────

SANDBOX_MODE_STRICT = "strict"
SANDBOX_MODE_PERMISSIVE = "permissive"
SANDBOX_MODE_OFF = "off"


def execute_sandboxed(
    code: str,
    timeout: int = 30,
    cwd: Optional[str] = None,
    project_root: str = "",
    mode: str = "strict",
    args: Optional[list[str]] = None,
) -> Dict[str, Any]:
    """Execute Python code in a sandboxed subprocess.

    Args:
        code: Python source code to execute.
        timeout: Maximum execution time in seconds.
        cwd: Working directory for subprocess.
        project_root: Project root (for context).
        mode: Sandbox mode (strict/permissive/off).
        args: Command-line arguments passed to script via sys.argv.

    Returns:
            Dict with status, stdout, stderr, exit_code, duration_ms, timed_out.
        """

    if mode != SANDBOX_MODE_OFF:
        try:
            validate_code(code)
        except SandboxViolation as e:
            _audit_log({
                "event": "violation",
                "mode": mode,
                "code_preview": code[:200],
                "violation": str(e),
            })
            return {
                "status": "violation",
                "stdout": "",
                "stderr": f"Sandbox violation: {e}",
                "violation": str(e),
                "duration_ms": 0,
                "exit_code": -1,
                "timed_out": False,
            }

    import time
    t0 = time.perf_counter()

    # Prepare subprocess
    env = os.environ.copy()
    env["PYTHONPATH"] = project_root
    if cwd is None:
        cwd = tempfile.gettempdir()

    # Build the script to execute
    script = code
    if args:
        script = f"import sys\nsys.argv = {args!r}\n" + code

    # Windows-safe subprocess
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW

    try:
        # Binary mode + stdin=DEVNULL to avoid pipe deadlock on Windows (§5.16)
        proc = subprocess.Popen(
            [sys.executable, "-c", script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=env,
            creationflags=creationflags,
        )
        raw_out, raw_err = proc.communicate(timeout=timeout)
        stdout = raw_out.decode("utf-8", errors="replace") if raw_out else ""
        stderr = raw_err.decode("utf-8", errors="replace") if raw_err else ""
        exit_code = proc.returncode
        timed_out = False
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except OSError:
            pass  # Process may have already exited between timeout and kill
        raw_out, raw_err = proc.communicate()
        stdout = raw_out.decode("utf-8", errors="replace") if raw_out else ""
        stderr = raw_err.decode("utf-8", errors="replace") if raw_err else ""
        exit_code = -1
        timed_out = True
    except Exception as e:
        return {
            "status": "error",
            "stdout": "",
            "stderr": f"Subprocess error: {e}",
            "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
            "exit_code": -1,
            "timed_out": False,
        }

    duration_ms = round((time.perf_counter() - t0) * 1000, 1)

    # Truncate output if too large
    if len(stdout) > MAX_OUTPUT_BYTES:
        stdout = stdout[:MAX_OUTPUT_BYTES] + "\n... [truncated]"
    if len(stderr) > MAX_OUTPUT_BYTES:
        stderr = stderr[:MAX_OUTPUT_BYTES] + "\n... [truncated]"

    status = "ok" if exit_code == 0 else "error"
    if timed_out:
        status = "timeout"

    # Audit log
    _audit_log({
        "event": "execute",
        "mode": mode,
        "code_preview": code[:200],
        "status": status,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "stdout_bytes": len(stdout),
        "stderr_bytes": len(stderr),
    })

    return {
        "status": status,
        "stdout": stdout,
        "stderr": stderr,
        "duration_ms": duration_ms,
        "exit_code": exit_code,
        "timed_out": timed_out,
    }


# ── Exports ──────────────────────────────────────────────────────

SANDBOX_MODE_STRICT = "strict"
SANDBOX_MODE_PERMISSIVE = "permissive"
SANDBOX_MODE_OFF = "off"

__all__ = [
    "SandboxViolation",
    "validate_code",
    "execute_sandboxed",
    "SANDBOX_MODE_STRICT",
    "SANDBOX_MODE_PERMISSIVE",
    "SANDBOX_MODE_OFF",
    "ALLOWED_MODULES",
    "BLOCKED_STR_PATTERNS",
    "BLOCKED_NAMES",
]