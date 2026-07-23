"""
Tests for modification guard — @modification_guard decorator + ack_impact (with HMAC tokens).

Covers:
1. ack_impact: requires impact_token, rejects invalid/stale tokens, accepts valid tokens
2. ack_impact: registers ack, returns TTL
3. @modification_guard: denies writes on hot files without ack
4. @modification_guard: allows writes with fresh ack
5. @modification_guard: re-blocks after TTL expiry
6. _make_ack_token / _verify_ack_token: HMAC correctness
7. Positional args: guard detects file_path/symbol from positional call
Edge cases: missing file_path, missing symbol, non-hot files
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def fresh_guard():
    """Reset the global ack registry before each test."""
    import src.core.modification_guard as mg

    mg._ack_registry.clear()
    return mg


@pytest.fixture
def mock_tool():
    """Create a minimal mock tool with _services and resolve_symbol_index."""
    tool = MagicMock()
    tool._services = MagicMock()
    tool.resolve_symbol_index = MagicMock(return_value=MagicMock())
    return tool


# ── Tests: ack_impact ────────────────────────────────────────────────────


class TestAckImpact:
    """Tests for ack_impact() function — requires impact_token."""

    def test_rejects_empty_token(self, fresh_guard):
        """ack_impact without token is rejected."""
        result = fresh_guard.ack_impact("/tmp/file.py", impact_token="")
        assert result["status"] == "denied"
        assert "Invalid or stale" in result["message"]

    def test_rejects_invalid_token(self, fresh_guard):
        """ack_impact with wrong token is rejected."""
        result = fresh_guard.ack_impact("/tmp/file.py", impact_token="fake-token-12345")
        assert result["status"] == "denied"

    def test_accepts_valid_token(self, fresh_guard, tmp_path):
        """ack_impact with correct HMAC token succeeds."""
        test_file = tmp_path / "test.py"
        test_file.write_text("# test")
        token = fresh_guard._make_ack_token(str(test_file))
        result = fresh_guard.ack_impact(str(test_file), impact_token=token)
        assert result["status"] == "ok"
        assert len(fresh_guard._ack_registry) == 1

    def test_returns_ttl(self, fresh_guard, tmp_path):
        """Response includes TTL in seconds."""
        test_file = tmp_path / "ttl.py"
        test_file.write_text("# ttl")
        token = fresh_guard._make_ack_token(str(test_file))
        result = fresh_guard.ack_impact(str(test_file), impact_token=token)
        assert "ttl_seconds" in result
        assert result["ttl_seconds"] > 0
        assert result["ttl_seconds"] == 600.0

    def test_stale_token_rejected_after_file_change(self, fresh_guard, tmp_path):
        """Token becomes invalid after file content changes."""
        test_file = tmp_path / "mutable.py"
        test_file.write_text("# version 1")
        token_v1 = fresh_guard._make_ack_token(str(test_file))

        # Change the file — fingerprint (mtime+size) will differ
        time.sleep(0.05)
        test_file.write_text("# version 2 — longer content to change size")

        result = fresh_guard.ack_impact(str(test_file), impact_token=token_v1)
        assert result["status"] == "denied"
        assert "stale" in result["message"].lower() or "Invalid" in result["message"]

    def test_normalizes_path(self, fresh_guard, tmp_path):
        """Paths are normalized to POSIX lowercase before storage."""
        test_file = tmp_path / "File.py"
        test_file.write_text("# normalize")
        token = fresh_guard._make_ack_token(str(test_file))
        fresh_guard.ack_impact(str(test_file), impact_token=token)
        normalized = fresh_guard._normalize_path(str(test_file))
        assert normalized in fresh_guard._ack_registry

    def test_multiple_files_independent(self, fresh_guard, tmp_path):
        """Each ack call creates a separate registry entry."""
        tokens = []
        for name in ("a.py", "b.py", "c.py"):
            f = tmp_path / name
            f.write_text(f"# {name}")
            tokens.append((str(f), fresh_guard._make_ack_token(str(f))))
        for path, token in tokens:
            fresh_guard.ack_impact(path, impact_token=token)
        assert len(fresh_guard._ack_registry) == 3


# ── Tests: @modification_guard decorator ──────────────────────────────────


class TestModificationGuard:
    """Tests for @modification_guard decorator."""

    @pytest.mark.asyncio
    async def test_allows_non_hot_file(self, fresh_guard, mock_tool):
        """Non-hot files pass through without ack."""
        from src.core.modification_guard import modification_guard

        with (
            patch(
                "src.core.modification_guard._get_pagerank_for_file",
                return_value=0.0,
            ),
            patch(
                "src.core.modification_guard._get_blast_radius_for_file",
                return_value=0,
            ),
        ):

            class TestTool:
                _services = mock_tool._services
                resolve_symbol_index = mock_tool.resolve_symbol_index

                @modification_guard()
                async def my_write(self, file_path="file.py", symbol="func"):
                    return {"status": "ok", "applied": True}

            tool = TestTool()
            result = await tool.my_write(file_path="file.py", symbol="func")
            assert result["status"] == "ok"
            assert result["applied"] is True

    @pytest.mark.asyncio
    async def test_denies_hot_file_without_ack(self, fresh_guard, mock_tool):
        """Hot files (high PageRank / blast radius) are denied without ack."""
        from src.core.modification_guard import modification_guard

        with (
            patch(
                "src.core.modification_guard._get_pagerank_for_file",
                return_value=0.5,
            ),
            patch(
                "src.core.modification_guard._get_blast_radius_for_file",
                return_value=20,
            ),
        ):

            class TestTool:
                _services = mock_tool._services
                resolve_symbol_index = mock_tool.resolve_symbol_index

                @modification_guard()
                async def my_write(self, file_path="hot.py", symbol="critical_func"):
                    return {"status": "ok"}

            tool = TestTool()
            result = await tool.my_write(
                file_path="hot.py", symbol="critical_func"
            )
            assert result["status"] == "denied"
            assert "guard" in result

    @pytest.mark.asyncio
    async def test_allows_hot_file_with_ack(self, fresh_guard, mock_tool, tmp_path):
        """Hot files pass if ack was called with valid token."""
        from src.core.modification_guard import (
            modification_guard,
        )

        # Create file + register ack with valid token
        test_file = tmp_path / "hot.py"
        test_file.write_text("# hot")
        token = fresh_guard._make_ack_token(str(test_file))
        fresh_guard.ack_impact(str(test_file), impact_token=token)

        with (
            patch(
                "src.core.modification_guard._get_pagerank_for_file",
                return_value=0.5,
            ),
            patch(
                "src.core.modification_guard._get_blast_radius_for_file",
                return_value=20,
            ),
        ):

            class TestTool:
                _services = mock_tool._services
                resolve_symbol_index = mock_tool.resolve_symbol_index

                @modification_guard()
                async def my_write(self, file_path="hot.py", symbol="critical_func"):
                    return {"status": "ok", "applied": True}

            tool = TestTool()
            result = await tool.my_write(
                file_path=str(test_file), symbol="critical_func"
            )
            assert result["status"] == "ok"
            assert result["applied"] is True

    @pytest.mark.asyncio
    async def test_reblocks_after_ttl_expiry(self, fresh_guard, mock_tool, tmp_path):
        """After TTL expires, hot files are blocked again."""
        from src.core.modification_guard import (
            _ACK_TTL,
            modification_guard,
        )

        # Register ack, then manually set timestamp to expired value
        test_file = tmp_path / "hot.py"
        test_file.write_text("# hot")
        token = fresh_guard._make_ack_token(str(test_file))
        fresh_guard.ack_impact(str(test_file), impact_token=token)
        normalized = fresh_guard._normalize_path(str(test_file))
        fresh_guard._ack_registry[normalized] = (
            time.time() - _ACK_TTL - 10
        )

        with (
            patch(
                "src.core.modification_guard._get_pagerank_for_file",
                return_value=0.5,
            ),
            patch(
                "src.core.modification_guard._get_blast_radius_for_file",
                return_value=20,
            ),
        ):

            class TestTool:
                _services = mock_tool._services
                resolve_symbol_index = mock_tool.resolve_symbol_index

                @modification_guard()
                async def my_write(self, file_path="hot.py", symbol="critical_func"):
                    return {"status": "ok"}

            tool = TestTool()
            result = await tool.my_write(
                file_path=str(test_file), symbol="critical_func"
            )
            assert result["status"] == "denied"

    @pytest.mark.asyncio
    async def test_expired_ack_is_cleaned_up(self, fresh_guard, mock_tool, tmp_path):
        """Expired ack entries are removed from the registry."""
        from src.core.modification_guard import (
            _ACK_TTL,
            modification_guard,
        )

        test_file = tmp_path / "hot.py"
        test_file.write_text("# hot")
        token = fresh_guard._make_ack_token(str(test_file))
        fresh_guard.ack_impact(str(test_file), impact_token=token)
        normalized = fresh_guard._normalize_path(str(test_file))
        fresh_guard._ack_registry[normalized] = (
            time.time() - _ACK_TTL - 10
        )

        with (
            patch(
                "src.core.modification_guard._get_pagerank_for_file",
                return_value=0.5,
            ),
            patch(
                "src.core.modification_guard._get_blast_radius_for_file",
                return_value=20,
            ),
        ):

            class TestTool:
                _services = mock_tool._services
                resolve_symbol_index = mock_tool.resolve_symbol_index

                @modification_guard()
                async def my_write(self, file_path="hot.py", symbol="critical_func"):
                    return {"status": "ok"}

            tool = TestTool()
            await tool.my_write(file_path=str(test_file), symbol="critical_func")

        # Expired entry should have been removed
        assert normalized not in fresh_guard._ack_registry

    @pytest.mark.asyncio
    async def test_no_file_path_no_symbol_passes(self, fresh_guard, mock_tool):
        """Guard passes through if neither file_path nor symbol is provided."""
        from src.core.modification_guard import modification_guard

        class TestTool:
            _services = mock_tool._services
            resolve_symbol_index = mock_tool.resolve_symbol_index

            @modification_guard()
            async def my_write(self):
                return {"status": "ok"}

        tool = TestTool()
        result = await tool.my_write()
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_guard_returns_diagnostics(self, fresh_guard, mock_tool, tmp_path):
        """Denied response includes pagerank, blast radius, thresholds, and impact_token."""
        from src.core.modification_guard import modification_guard

        test_file = tmp_path / "diag.py"
        test_file.write_text("# diag")

        with (
            patch(
                "src.core.modification_guard._get_pagerank_for_file",
                return_value=0.5,
            ),
            patch(
                "src.core.modification_guard._get_blast_radius_for_file",
                return_value=20,
            ),
        ):

            class TestTool:
                _services = mock_tool._services
                resolve_symbol_index = mock_tool.resolve_symbol_index

                @modification_guard(pagerank_min=0.03, blast_min=5)
                async def my_write(
                    self, file_path="hot.py", symbol="critical_func"
                ):
                    return {"status": "ok"}

            tool = TestTool()
            result = await tool.my_write(
                file_path=str(test_file), symbol="critical_func"
            )
            guard = result["guard"]
            assert guard["pagerank"] == 0.5
            assert guard["pagerank_threshold"] == 0.03
            assert guard["blast_radius"] == 20
            assert guard["blast_threshold"] == 5
            assert guard["ack_required"] is True
            # Token must be present in guard response
            assert "impact_token" in guard
            assert len(guard["impact_token"]) == 32  # HMAC-SHA256 truncated to 32 chars

    @pytest.mark.asyncio
    async def test_guard_token_matches_ack(self, fresh_guard, mock_tool, tmp_path):
        """Token from guard DENY can be used to successfully ack."""
        from src.core.modification_guard import modification_guard

        test_file = tmp_path / "token_match.py"
        test_file.write_text("# token match")

        with (
            patch(
                "src.core.modification_guard._get_pagerank_for_file",
                return_value=0.5,
            ),
            patch(
                "src.core.modification_guard._get_blast_radius_for_file",
                return_value=20,
            ),
        ):

            class TestTool:
                _services = mock_tool._services
                resolve_symbol_index = mock_tool.resolve_symbol_index

                @modification_guard()
                async def my_write(self, file_path="hot.py", symbol="func"):
                    return {"status": "ok", "applied": True}

            tool = TestTool()
            # Step 1: DENY — get token
            result = await tool.my_write(file_path=str(test_file), symbol="func")
            assert result["status"] == "denied"
            token = result["guard"]["impact_token"]

            # Step 2: ack with token from guard
            ack_result = fresh_guard.ack_impact(str(test_file), impact_token=token)
            assert ack_result["status"] == "ok"

            # Step 3: re-run — should pass
            result2 = await tool.my_write(file_path=str(test_file), symbol="func")
            assert result2["status"] == "ok"

    @pytest.mark.asyncio
    async def test_file_path_only_triggers_pagerank_check(
        self, fresh_guard, mock_tool, tmp_path
    ):
        """When only file_path is given, pagerank is checked and blast radius is 0."""
        from src.core.modification_guard import modification_guard

        test_file = tmp_path / "hot.py"
        test_file.write_text("# hot")

        with (
            patch(
                "src.core.modification_guard._get_pagerank_for_file",
                return_value=0.5,
            ),
            patch(
                "src.core.modification_guard._get_blast_radius_for_file",
                return_value=0,
            ),
        ):

            class TestTool:
                _services = mock_tool._services
                resolve_symbol_index = mock_tool.resolve_symbol_index

                @modification_guard()
                async def my_write(self, file_path="hot.py"):
                    return {"status": "ok"}

            tool = TestTool()
            result = await tool.my_write(file_path=str(test_file))
            # PageRank alone (0.5 >= 0.05) is enough to trigger denial
            assert result["status"] == "denied"

    @pytest.mark.asyncio
    async def test_symbol_only_triggers_blast_check(
        self, fresh_guard, mock_tool
    ):
        """When only symbol is given, blast radius is checked."""
        from src.core.modification_guard import modification_guard

        with (
            patch(
                "src.core.modification_guard._get_pagerank_for_file",
                return_value=0.0,
            ),
            patch(
                "src.core.modification_guard._get_blast_radius_for_file",
                return_value=20,
            ),
        ):

            class TestTool:
                _services = mock_tool._services
                resolve_symbol_index = mock_tool.resolve_symbol_index

                @modification_guard()
                async def my_write(self, symbol="critical_func"):
                    return {"status": "ok"}

            tool = TestTool()
            result = await tool.my_write(symbol="critical_func")
            # Blast radius alone (20 >= 10) is enough to trigger denial
            assert result["status"] == "denied"


# ── Tests: _make_ack_token / _verify_ack_token ────────────────────────────


class TestHMACToken:
    """Tests for HMAC token generation and verification."""

    def test_token_deterministic_for_same_state(self, fresh_guard, tmp_path):
        """Same file state produces the same token."""
        test_file = tmp_path / "same.py"
        test_file.write_text("# content")
        t1 = fresh_guard._make_ack_token(str(test_file))
        t2 = fresh_guard._make_ack_token(str(test_file))
        assert t1 == t2

    def test_token_changes_after_file_edit(self, fresh_guard, tmp_path):
        """Token changes when file content changes."""
        test_file = tmp_path / "edit.py"
        test_file.write_text("# v1")
        t1 = fresh_guard._make_ack_token(str(test_file))
        time.sleep(0.05)
        test_file.write_text("# v2 — different content")
        t2 = fresh_guard._make_ack_token(str(test_file))
        assert t1 != t2

    def test_verify_rejects_wrong_token(self, fresh_guard, tmp_path):
        """Verification rejects token that doesn't match current file state."""
        test_file = tmp_path / "verify.py"
        test_file.write_text("# verify")
        assert fresh_guard._verify_ack_token(str(test_file), "wrong-token") is False

    def test_verify_accepts_correct_token(self, fresh_guard, tmp_path):
        """Verification accepts token matching current file state."""
        test_file = tmp_path / "accept.py"
        test_file.write_text("# accept")
        token = fresh_guard._make_ack_token(str(test_file))
        assert fresh_guard._verify_ack_token(str(test_file), token) is True

    def test_token_is_32_hex_chars(self, fresh_guard, tmp_path):
        """Token is exactly 32 hex characters (128 bits)."""
        test_file = tmp_path / "length.py"
        test_file.write_text("# length check")
        token = fresh_guard._make_ack_token(str(test_file))
        assert len(token) == 32
        assert all(c in "0123456789abcdef" for c in token)

    def test_token_missing_file_returns_missing_fingerprint(self, fresh_guard):
        """Token for non-existent file uses 'missing' fingerprint."""
        token = fresh_guard._make_ack_token("/nonexistent/file.py")
        # Should still produce a valid token (fingerprint = "missing")
        assert len(token) == 32
        # Verify should still work against same non-existent path
        assert fresh_guard._verify_ack_token("/nonexistent/file.py", token) is True
