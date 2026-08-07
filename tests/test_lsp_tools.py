"""
Tests for LSP tools: lsp_get_type_info / lsp_get_diagnostics + formatters.

LSP-запуск basedpyright (реальный процесс) в CI не гарантирован — здесь
покрываются чистые функции и контракт имён тулов. Реальный smoke — ручной
(см. AGENT_DIARY 2026-08-06: references 2/2, start 267ms).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.mcp.tools.lsp_tools import (
    LspGetDiagnosticsTool,
    LspGetTypeInfoTool,
    _format_diagnostics,
)

from src.core.lsp_client import LspClient


# ── Нормализация publishDiagnostics-uri (регрессия 2026-08-07) ──────────
# basedpyright на Windows перекодирует uri (file:///D:/x → file:///d%3A/x);
# без нормализации диагностика молча терялась (key mismatch в _diagnostics).


def test_normalize_diag_uri_win_drive():
    server_uri = "file:///d%3A/Project/MSCodeBase/_smoke_tmp.py"
    canonical = LspClient._normalize_diag_uri(server_uri)
    assert canonical == "file:///D:/Project/MSCodeBase/_smoke_tmp.py"


def test_normalize_diag_uri_already_canonical():
    canonical = "file:///D:/Project/MSCodeBase/_smoke_tmp.py"
    assert LspClient._normalize_diag_uri(canonical) == canonical


def test_normalize_diag_uri_idempotent():
    """Повторная нормализация не меняет результат (идемпотентность)."""
    server_uri = "file:///d%3A/Project/MSCodeBase/_smoke_tmp.py"
    once = LspClient._normalize_diag_uri(server_uri)
    assert LspClient._normalize_diag_uri(once) == once


# ── _format_diagnostics ───────────────────────────────────────────────


def test_format_diagnostics_empty():
    assert "не найдено" in _format_diagnostics([])
    assert "✅" in _format_diagnostics([])


def test_format_diagnostics_maps_severity_and_position():
    diags = [
        {
            "severity": 1,
            "code": "reportUndefinedVariable",
            "message": '"x" is not defined',
            "range": {"start": {"line": 3, "character": 8}},
        },
        {
            "severity": 2,
            "code": "reportUnusedVariable",
            "message": '"y" is unused',
            "range": {"start": {"line": 5, "character": 0}},
        },
    ]
    out = _format_diagnostics(diags)
    assert "2" in out  # count
    assert "[ERROR]" in out
    assert "[WARNING]" in out
    assert "L3:8" in out
    assert '"x" is not defined' in out
    assert "reportUndefinedVariable" in out


# ── Контракт имён ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("cls", "expected_name"),
    [
        (LspGetTypeInfoTool, "lsp_get_type_info"),
        (LspGetDiagnosticsTool, "lsp_get_diagnostics"),
    ],
)
def test_tool_names(cls, expected_name):
    tool = cls(MagicMock())
    assert tool.name == expected_name
