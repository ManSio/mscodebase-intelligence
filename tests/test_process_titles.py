"""Unit tests for process naming (MCP title + llama role hardlinks)."""

import sys
from pathlib import Path
from unittest.mock import patch


def test_build_mcp_title_format(tmp_path):
    from src.core import process_titles as pt
    from src.core.artifact_paths import project_hash

    p = tmp_path / "MyProj"
    p.mkdir()
    title = pt.build_mcp_title(p)
    assert title == f"mscodebase-mcp:MyProj-{project_hash(p)}"


def test_build_mcp_title_none():
    from src.core import process_titles as pt

    assert pt.build_mcp_title(None) == "mscodebase-mcp:unknown-unknown"


def test_set_console_title_non_win_returns_false():
    from src.core import process_titles as pt

    with patch.object(sys, "platform", "linux"):
        assert pt.set_console_title("x") is False


def test_role_bin_name_mapping():
    from src.core import process_titles as pt

    if sys.platform == "win32":
        assert pt.role_bin_name("embed") == "llama-embed.exe"
        assert pt.role_bin_name("rerank") == "llama-rerank.exe"
        assert pt.role_bin_name("other") == "llama-server.exe"
    else:
        assert pt.role_bin_name("embed") == "llama-server.exe"


def test_ensure_role_hardlink_mock_link(tmp_path):
    from src.core import process_titles as pt

    src = tmp_path / "llama-server.exe"
    src.write_bytes(b"x")
    with patch.object(sys, "platform", "win32"):
        created = []

        def fake_link(a, b):
            created.append((a, b))
            Path(b).write_bytes(b"x")

        with patch("os.link", side_effect=fake_link):
            out = pt.ensure_role_hardlink(src, "embed")
        assert out == tmp_path / "llama-embed.exe"
        assert out.exists()
        assert created


def test_ensure_role_hardlink_fallback_on_error(tmp_path):
    from src.core import process_titles as pt

    src = tmp_path / "llama-server.exe"
    src.write_bytes(b"x")
    with patch.object(sys, "platform", "win32"):
        with patch("os.link", side_effect=OSError("denied")):
            out = pt.ensure_role_hardlink(src, "rerank")
        assert out == src


def test_ensure_role_hardlink_reuses_existing(tmp_path):
    from src.core import process_titles as pt

    src = tmp_path / "llama-server.exe"
    src.write_bytes(b"x")
    link = tmp_path / "llama-embed.exe"
    link.write_bytes(b"x")
    with patch.object(sys, "platform", "win32"):
        with patch("os.link", side_effect=AssertionError("must not be called")):
            assert pt.ensure_role_hardlink(src, "embed") == link


def test_ensure_role_hardlink_non_win_no_link(tmp_path):
    from src.core import process_titles as pt

    src = tmp_path / "llama-server.exe"
    src.write_bytes(b"x")
    with patch.object(sys, "platform", "linux"):
        with patch("os.link", side_effect=AssertionError("must not be called")):
            assert pt.ensure_role_hardlink(src, "embed") == src
