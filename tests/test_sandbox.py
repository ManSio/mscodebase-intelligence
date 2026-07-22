"""Tests for sandboxed code execution.

Covers:
- Module allowlist (allowed vs blocked imports)
- Blocked patterns (os.system, eval, exec, etc.)
- AST-level validation (dangerous constructs)
- Execution in subprocess (success, error, timeout)
- Audit logging
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.sandbox.executor import (
    ALLOWED_MODULES,
    BLOCKED_STR_PATTERNS,
    SANDBOX_MODE_OFF,
    SANDBOX_MODE_PERMISSIVE,
    SANDBOX_MODE_STRICT,
    SandboxViolation,
    execute_sandboxed,
    validate_code,
)


# ═══════════════════════════════════════════════════════════════
# validate_code — AST + string validation
# ═══════════════════════════════════════════════════════════════


class TestValidateCode:
    """Test code validation before execution."""

    def test_safe_code_passes(self):
        code = "import math\nresult = math.sqrt(16)"
        warnings = validate_code(code)
        assert isinstance(warnings, list)

    def test_allowed_modules(self):
        for mod in ["math", "json", "re", "datetime", "collections", "hashlib"]:
            code = f"import {mod}"
            validate_code(code)  # Should not raise

    def test_blocked_import_os(self):
        with pytest.raises(SandboxViolation, match="not in allowlist"):
            validate_code("import os")

    def test_blocked_import_subprocess(self):
        with pytest.raises(SandboxViolation):
            validate_code("import subprocess")

    def test_blocked_import_sys(self):
        with pytest.raises(SandboxViolation, match="not in allowlist"):
            validate_code("import sys")

    def test_blocked_from_import(self):
        with pytest.raises(SandboxViolation, match="not in allowlist"):
            validate_code("from os import system")

    def test_blocked_string_pattern_os_system(self):
        with pytest.raises(SandboxViolation, match="Blocked pattern"):
            validate_code('result = os.system("ls")')

    def test_blocked_string_pattern_eval(self):
        with pytest.raises(SandboxViolation, match="Blocked pattern"):
            validate_code('eval("1+1")')

    def test_blocked_string_pattern_exec(self):
        with pytest.raises(SandboxViolation, match="Blocked pattern"):
            validate_code('exec("print(1)")')

    def test_blocked_string_pattern_subprocess(self):
        with pytest.raises(SandboxViolation, match="Blocked pattern"):
            validate_code("import subprocess")

    def test_blocked_string_pattern_dunder_import(self):
        with pytest.raises(SandboxViolation, match="Blocked pattern"):
            validate_code('__import__("os")')

    def test_blocked_ast_eval_call(self):
        with pytest.raises(SandboxViolation):
            validate_code('x = eval("1+1")')

    def test_blocked_ast_dunder_subclasses(self):
        with pytest.raises(SandboxViolation, match="Blocked attribute"):
            validate_code("x = ().__class__.__subclasses__()")

    def test_syntax_error(self):
        with pytest.raises(SandboxViolation, match="Syntax error"):
            validate_code("def foo(")

    def test_empty_code(self):
        warnings = validate_code("")
        assert isinstance(warnings, list)

    # ── R1: Blocked built-in names ──

    def test_blocked_name_getattr(self):
        with pytest.raises(SandboxViolation, match="Blocked name"):
            validate_code("x = getattr(obj, 'attr')")

    def test_blocked_name_setattr(self):
        with pytest.raises(SandboxViolation, match="Blocked name"):
            validate_code("setattr(obj, 'attr', value)")

    def test_blocked_name_delattr(self):
        with pytest.raises(SandboxViolation, match="Blocked name"):
            validate_code("delattr(obj, 'attr')")

    def test_blocked_name_globals(self):
        with pytest.raises(SandboxViolation):
            validate_code("x = globals()")

    def test_blocked_name_locals(self):
        with pytest.raises(SandboxViolation):
            validate_code("x = locals()")

    # ── R2: pathlib removed from allowlist ──

    def test_pathlib_blocked(self):
        with pytest.raises(SandboxViolation, match="not in allowlist"):
            validate_code("from pathlib import Path")

    # ── Bypass attempts ──

    def test_concatenated_import_bypass(self):
        """String concatenation to evade string scan.

        Note: Pure string concat ("__imp" + "ort") is harmless by itself —
        it's just a string literal. The bypass only works when combined
        with __import__() or eval(), which ARE caught. We verify that
        the dangerous CALL is caught even if the import name is constructed.
        """
        with pytest.raises(SandboxViolation):
            validate_code('x = __import__("os")')

    def test_dynamic_getattr_bypass(self):
        """getattr with string concatenation to import os."""
        with pytest.raises(SandboxViolation):
            validate_code('getattr(__import__("os"), "sys" + "tem")')


# ═══════════════════════════════════════════════════════════════
# execute_sandboxed — subprocess execution
# ═══════════════════════════════════════════════════════════════


class TestExecuteSandboxed:
    """Test sandboxed code execution in subprocess."""

    def test_simple_execution(self):
        result = execute_sandboxed(
            code="print('hello')",
            timeout=10,
            mode=SANDBOX_MODE_PERMISSIVE,
        )
        assert result["status"] == "ok"
        assert "hello" in result["stdout"]
        assert result["exit_code"] == 0

    def test_math_result(self):
        result = execute_sandboxed(
            code="result = 2 + 2",
            timeout=10,
            mode=SANDBOX_MODE_PERMISSIVE,
        )
        assert result["status"] == "ok"
        assert "4" in result["stdout"]

    def test_import_allowed_module(self):
        result = execute_sandboxed(
            code="import math; result = math.pi",
            timeout=10,
            mode=SANDBOX_MODE_STRICT,
        )
        assert result["status"] == "ok"
        assert "3.14" in result["stdout"]

    def test_import_blocked_module_strict(self):
        result = execute_sandboxed(
            code="import os; result = os.getcwd()",
            timeout=10,
            mode=SANDBOX_MODE_STRICT,
        )
        assert result["status"] == "violation"
        assert "not in allowlist" in result["stderr"]

    def test_timeout(self):
        result = execute_sandboxed(
            code="import time; time.sleep(60)",
            timeout=3,
            mode=SANDBOX_MODE_PERMISSIVE,
        )
        assert result["timed_out"] is True
        assert result["status"] == "timeout"

    def test_execution_error(self):
        result = execute_sandboxed(
            code="raise ValueError('test error')",
            timeout=10,
            mode=SANDBOX_MODE_PERMISSIVE,
        )
        assert result["status"] == "error"
        assert "test error" in result["stderr"]

    def test_output_limit(self):
        # Generate output larger than MAX_OUTPUT_BYTES
        code = "print('x' * 2_000_000)"
        result = execute_sandboxed(
            code=code,
            timeout=10,
            mode=SANDBOX_MODE_PERMISSIVE,
        )
        # Output should be truncated by wrapper
        assert len(result.get("stdout", "")) <= 1_000_000 + 100  # some margin

    def test_off_mode_no_validation(self):
        result = execute_sandboxed(
            code="import os; result = os.getcwd()",
            timeout=10,
            mode=SANDBOX_MODE_OFF,
        )
        # Off mode: no validation, but os may not be importable in restricted env
        # The key is that validation is skipped
        assert result["status"] in ("ok", "error")  # not "violation"

    def test_syntax_error_in_code(self):
        result = execute_sandboxed(
            code="def foo(",
            timeout=10,
            mode=SANDBOX_MODE_STRICT,
        )
        # Syntax error caught by validate_code or subprocess
        assert result["status"] in ("violation", "error")


# ═══════════════════════════════════════════════════════════════
# Audit logging
# ═══════════════════════════════════════════════════════════════


class TestAuditLog:
    """Test that execution events are logged."""

    def test_violation_logged(self):
        with patch("src.core.sandbox.executor._get_audit_log_path") as mock_path:
            audit_file = Path(tempfile.mktemp(suffix=".jsonl"))
            mock_path.return_value = audit_file
            try:
                result = execute_sandboxed(
                    code="import os",
                    timeout=10,
                    mode=SANDBOX_MODE_STRICT,
                )
                assert result["status"] == "violation"
                assert audit_file.exists()
                with open(audit_file) as f:
                    lines = f.readlines()
                assert len(lines) >= 1
                entry = json.loads(lines[-1])
                assert entry["event"] == "violation"
            finally:
                audit_file.unlink(missing_ok=True)

    def test_execution_logged(self):
        with patch("src.core.sandbox.executor._get_audit_log_path") as mock_path:
            audit_file = Path(tempfile.mktemp(suffix=".jsonl"))
            mock_path.return_value = audit_file
            try:
                result = execute_sandboxed(
                    code="print('test')",
                    timeout=10,
                    mode=SANDBOX_MODE_PERMISSIVE,
                )
                assert audit_file.exists()
                with open(audit_file) as f:
                    lines = f.readlines()
                assert len(lines) >= 1
                entry = json.loads(lines[-1])
                assert entry["event"] == "execute"
                assert entry["status"] == "ok"
            finally:
                audit_file.unlink(missing_ok=True)
