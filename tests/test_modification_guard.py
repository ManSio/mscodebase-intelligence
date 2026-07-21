"""
Tests for modification guard — @modification_guard decorator + ack_impact.

Covers:
1. ack_impact: registers ack, returns TTL
2. @modification_guard: denies writes on hot files without ack
3. @modification_guard: allows writes with fresh ack
4. @modification_guard: re-blocks after TTL expiry
5. Edge cases: missing file_path, missing symbol, non-hot files
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
    """Tests for ack_impact() function."""

    def test_registers_ack(self, fresh_guard):
        """ack_impact adds an entry to _ack_registry."""
        result = fresh_guard.ack_impact("/tmp/file.py")
        assert result["status"] == "ok"
        assert len(fresh_guard._ack_registry) == 1

    def test_returns_ttl(self, fresh_guard):
        """Response includes TTL in seconds."""
        result = fresh_guard.ack_impact("/tmp/file.py")
        assert "ttl_seconds" in result
        assert result["ttl_seconds"] > 0
        assert result["ttl_seconds"] == 600.0

    def test_normalizes_path(self, fresh_guard):
        """Paths are normalized to POSIX lowercase before storage."""
        fresh_guard.ack_impact("src\\CORE\\File.py")
        normalized = fresh_guard._normalize_path("src\\CORE\\File.py")
        assert normalized in fresh_guard._ack_registry

    def test_multiple_files_independent(self, fresh_guard):
        """Each ack call creates a separate registry entry."""
        fresh_guard.ack_impact("/tmp/a.py")
        fresh_guard.ack_impact("/tmp/b.py")
        fresh_guard.ack_impact("/tmp/c.py")
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
    async def test_allows_hot_file_with_ack(self, fresh_guard, mock_tool):
        """Hot files pass if ack was called within TTL."""
        from src.core.modification_guard import (
            ack_impact,
            modification_guard,
        )

        # Register ack first
        ack_impact("hot.py")

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
                file_path="hot.py", symbol="critical_func"
            )
            assert result["status"] == "ok"
            assert result["applied"] is True

    @pytest.mark.asyncio
    async def test_reblocks_after_ttl_expiry(self, fresh_guard, mock_tool):
        """After TTL expires, hot files are blocked again."""
        from src.core.modification_guard import (
            _ACK_TTL,
            ack_impact,
            modification_guard,
        )

        # Register ack, then manually set timestamp to expired value
        ack_impact("hot.py")
        normalized = Path("hot.py").resolve().as_posix().lower()
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
                file_path="hot.py", symbol="critical_func"
            )
            assert result["status"] == "denied"

    @pytest.mark.asyncio
    async def test_expired_ack_is_cleaned_up(self, fresh_guard, mock_tool):
        """Expired ack entries are removed from the registry."""
        from src.core.modification_guard import (
            _ACK_TTL,
            ack_impact,
            modification_guard,
        )

        ack_impact("hot.py")
        normalized = Path("hot.py").resolve().as_posix().lower()
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
            await tool.my_write(file_path="hot.py", symbol="critical_func")

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
    async def test_guard_returns_diagnostics(self, fresh_guard, mock_tool):
        """Denied response includes pagerank, blast radius, and thresholds."""
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

                @modification_guard(pagerank_min=0.03, blast_min=5)
                async def my_write(
                    self, file_path="hot.py", symbol="critical_func"
                ):
                    return {"status": "ok"}

            tool = TestTool()
            result = await tool.my_write(
                file_path="hot.py", symbol="critical_func"
            )
            guard = result["guard"]
            assert guard["pagerank"] == 0.5
            assert guard["pagerank_threshold"] == 0.03
            assert guard["blast_radius"] == 20
            assert guard["blast_threshold"] == 5
            assert guard["ack_required"] is True

    @pytest.mark.asyncio
    async def test_file_path_only_triggers_pagerank_check(
        self, fresh_guard, mock_tool
    ):
        """When only file_path is given, pagerank is checked and blast radius is 0."""
        from src.core.modification_guard import modification_guard

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
            result = await tool.my_write(file_path="hot.py")
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
