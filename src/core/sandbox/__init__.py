"""Sandboxed Python code execution for ExecuteScriptTool.

Provides AST-based validation, module allowlist, and audit logging
for untrusted code execution via MCP tools.

Security levels:
- strict: AST validation + module allowlist + blocked patterns + timeout
- permissive: timeout only (legacy behavior)
- off: no sandbox (NOT RECOMMENDED)
"""

from src.core.sandbox.executor import (
    SandboxViolation,
    validate_code,
    execute_sandboxed,
    SANDBOX_MODE_STRICT,
    SANDBOX_MODE_PERMISSIVE,
    SANDBOX_MODE_OFF,
)

__all__ = [
    "SandboxViolation",
    "validate_code",
    "execute_sandboxed",
    "SANDBOX_MODE_STRICT",
    "SANDBOX_MODE_PERMISSIVE",
    "SANDBOX_MODE_OFF",
]
