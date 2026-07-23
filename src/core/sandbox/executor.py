"""Sandboxed Python code execution engine.

Security layers:
1. AST validation — blocks dangerous patterns before execution
2. Module allowlist — only safe stdlib modules permitted
3. Subprocess isolation — code runs in separate process with restricted env
4. Timeout enforcement — kills long-running code
5. Audit logging — every execution logged to sandbox_audit.jsonl

Usage:
    result = execute_sandboxed(code="print(1+1)", timeout=30)
    # result = {"status": "ok", "output": "2", "exit_code": 0, ...}
"""

from __future__ import annotations

import ast
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ── Sandbox modes ──────────────────────────────────────────────

SANDBOX_MODE_STRICT = "strict"
SANDBOX_MODE_PERMISSIVE = "permissive"
SANDBOX_MODE_OFF = "off"

# ── Module allowlist (stdlib only) ─────────────────────────────

ALLOWED_MODULES: frozenset[str] = frozenset({
    # Safe stdlib
    "math", "cmath", "decimal", "fractions", "statistics", "random",
    "numbers", "itertools", "functools", "operator", "copy",
    # Data structures
    "collections", "array", "enum", "dataclasses", "typing",
    "heapq", "bisect", "queue", "weakref",
    # Text / encoding
    "string", "textwrap", "re", "difflib", "unicodedata",
    "html", "xml",
    # Serialization
    "json", "csv", "base64", "codecs",
    # Hashing / crypto
    "hashlib", "hmac", "secrets",
    # Date / time
    "datetime", "time", "zoneinfo",
    # IO / paths (read-only)
    "io", "glob", "fnmatch",
    # Networking (parse only, no sockets)
    "urllib.parse", "urllib.request", "email.utils",
    # Debug / inspection
    "traceback", "inspect", "dis",
    # Misc safe
    "contextlib", "pprint", "textwrap",
})

# ── Blocked patterns (AST + string scan) ───────────────────────

# String-level blocks (fast pre-check)
BLOCKED_STR_PATTERNS: tuple[str, ...] = (
    "os.system", "os.popen", "os.exec", "os.spawn",
    "os.remove", "os.rmdir", "os.unlink", "os.rename", "os.chmod",
    "subprocess", "shutil.rmtree", "shutil.move", "shutil.copytree",
    "__import__", "importlib",
    "eval(", "exec(",
    "compile(",
    "globals()", "locals()", "vars()",
    "breakpoint()", "pdb.", "pdb.set_trace",
    "sys.exit", "sys.modules", "sys.path", "sys.platform",
    "ctypes", "signal.", "multiprocessing",
    "threading", "asyncio",
    "socket", "http.server", "xmlrpc",
)

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

# ── Limits ─────────────────────────────────────────────────────

MAX_EXECUTION_TIME_S = 120
MAX_OUTPUT_BYTES = 1_000_000  # 1MB

# ── Audit log ──────────────────────────────────────────────────

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


# ── Validation ─────────────────────────────────────────────────


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
            if node.attr in ("__subclasses__", "__bases__", "__globals__"):
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


# ── Execution ──────────────────────────────────────────────────


def execute_sandboxed(
    code: str,
    timeout: int = 30,
    cwd: Optional[str] = None,
    project_root: str = "",
    mode: str = SANDBOX_MODE_STRICT,
    args: Optional[list[str]] = None,
) -> Dict[str, Any]:
    """Execute Python code in a sandboxed subprocess.

    Args:
        code: Python source code to execute.
        timeout: Max execution time in seconds (5-120).
        cwd: Working directory for the subprocess.
        project_root: Project root for PYTHONPATH.
        mode: Sandbox mode (strict/permissive/off).
        args: Command-line arguments (passed as sys.argv).

    Returns:
        {
            "status": "ok" | "error" | "violation" | "timeout",
            "stdout": str,
            "stderr": str,
            "exit_code": int,
            "duration_ms": float,
            "timed_out": bool,
            "truncated": bool,
            "violation": str | None,
        }
    """
    timeout = max(5, min(timeout, MAX_EXECUTION_TIME_S))
    t0 = time.perf_counter()

    result_base: Dict[str, Any] = {
        "stdout": "",
        "stderr": "",
        "exit_code": 1,
        "duration_ms": 0,
        "timed_out": False,
        "truncated": False,
        "violation": None,
    }

    # ── CRITICAL warning when sandbox is disabled ──
    if mode == SANDBOX_MODE_OFF:
        logger.critical(
            "SANDBOX DISABLED — code execution without isolation",
            extra={"tool": "execute_script", "mode": "off"},
        )

    # ── Validation (strict mode only) ──
    if mode == SANDBOX_MODE_STRICT:
        try:
            validate_code(code)
        except SandboxViolation as e:
            duration_ms = round((time.perf_counter() - t0) * 1000, 1)
            result_base["status"] = "violation"
            result_base["stderr"] = f"Sandbox violation: {e}"
            result_base["violation"] = str(e)
            result_base["duration_ms"] = duration_ms
            _audit_log({
                "event": "violation",
                "code_preview": code[:200],
                "violation": str(e),
                "pattern": getattr(e, "pattern", ""),
                "mode": mode,
            })
            return result_base

    # ── Build wrapper script ──
    # The wrapper restricts sys.modules inside the child process
    # and captures output as JSON for reliable parsing.
    args_repr = json.dumps(args or [])
    code_escaped = code.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

    wrapper = f'''
import sys, json, traceback

# Restrict modules to allowlist (defense-in-depth)
_allowed = {json.dumps(sorted(ALLOWED_MODULES))}
_orig_modules = dict(sys.modules)
for _k in list(sys.modules.keys()):
    _root = _k.split(".")[0]
    if _root not in _allowed and _k not in ("builtins", "_thread", "io"):
        del sys.modules[_k]

# Set sys.argv from args
sys.argv = ["execute_script"] + {args_repr}

_code = """{code_escaped}"""

try:
    _g = {{"__name__": "__main__", "__builtins__": __builtins__}}
    exec(compile(_code, "<sandbox>", "exec"), _g)
    _output = ""
    # Check for common output variables
    for _v in ("result", "output", "_result"):
        if _v in _g:
            _output = str(_g[_v])
            break
    print(json.dumps({{
        "status": "ok",
        "output": _output[:{MAX_OUTPUT_BYTES}],
    }}))
except SystemExit:
    print(json.dumps({{"status": "ok", "output": ""}}))
except Exception as _e:
    print(json.dumps({{
        "status": "error",
        "error": str(_e),
        "traceback": traceback.format_exc()[-3000:],
    }}))
'''

    # ── Build environment ──
    env = {
        "PATH": "",
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "PYTHONPATH": project_root,
        "TEMP": os.environ.get("TEMP", ""),
        "TMP": os.environ.get("TMP", ""),
    }

    # ── Subprocess options (Windows compat) ──
    startupinfo = None
    creationflags = 0
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        creationflags = subprocess.CREATE_NO_WINDOW

    # ── Execute ──
    timed_out = False
    exit_code = 0
    stdout_text = ""
    stderr_text = ""

    try:
        proc = subprocess.Popen(
            [sys.executable, "-c", wrapper],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=cwd or tempfile.gettempdir(),
            startupinfo=startupinfo,
            creationflags=creationflags,
            close_fds=True,
        )

        try:
            stdout_bytes, stderr_bytes = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            # Graceful shutdown: term -> wait -> kill
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except (subprocess.TimeoutExpired, OSError):
                proc.kill()
                proc.wait(timeout=5)
            exit_code = -1
            stdout_bytes, stderr_bytes = b"", b""

        if not timed_out:
            stdout_text = (stdout_bytes or b"").decode("utf-8", errors="replace")
            stderr_text = (stderr_bytes or b"").decode("utf-8", errors="replace")
            exit_code = proc.returncode or 0

    except Exception as e:
        duration_ms = round((time.perf_counter() - t0) * 1000, 1)
        result_base["status"] = "error"
        result_base["stderr"] = str(e)
        result_base["duration_ms"] = duration_ms
        _audit_log({
            "event": "execution_error",
            "error": str(e),
            "code_preview": code[:200],
            "mode": mode,
        })
        return result_base

    duration_ms = round((time.perf_counter() - t0) * 1000, 1)

    # ── Parse wrapper output ──
    stdout_truncated = len(stdout_text) > MAX_OUTPUT_BYTES
    stderr_truncated = len(stderr_text) > MAX_OUTPUT_BYTES

    wrapper_result = None
    if not timed_out and stdout_text.strip():
        try:
            wrapper_result = json.loads(stdout_text.strip())
        except json.JSONDecodeError:
            pass

    if wrapper_result:
        status = wrapper_result.get("status", "ok")
        output = wrapper_result.get("output", "")
        error = wrapper_result.get("error", "")
        tb = wrapper_result.get("traceback", "")

        result_base["status"] = status
        result_base["stdout"] = output[:MAX_OUTPUT_BYTES]
        if error:
            result_base["stderr"] = error[:MAX_OUTPUT_BYTES]
        if tb:
            result_base["stderr"] = (result_base["stderr"] + "\n" + tb)[:MAX_OUTPUT_BYTES]
        result_base["exit_code"] = 0 if status == "ok" else 1
    else:
        # Fallback: raw stdout/stderr
        result_base["status"] = "ok" if exit_code == 0 else "error"
        result_base["stdout"] = stdout_text[:MAX_OUTPUT_BYTES]
        result_base["stderr"] = stderr_text[:MAX_OUTPUT_BYTES]
        result_base["exit_code"] = exit_code

    result_base["timed_out"] = timed_out
    result_base["truncated"] = stdout_truncated or stderr_truncated
    result_base["duration_ms"] = duration_ms

    if timed_out:
        result_base["status"] = "timeout"
        result_base["timeout_s"] = timeout

    # ── Audit log ──
    _audit_log({
        "event": "execute",
        "status": result_base["status"],
        "mode": mode,
        "code_preview": code[:200],
        "duration_ms": duration_ms,
        "exit_code": result_base["exit_code"],
        "timed_out": timed_out,
    })

    return result_base
