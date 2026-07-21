"""
Benchmark suite for Agentic Code Search.

Compares agentic_code_search vs hybrid_search across different query types:
- Simple queries (1 concept): hybrid should be faster
- Complex queries (3+ concepts): agentic should be more accurate
- Decomposition quality: LLM vs rules
- Call Graph overhead: symbol_index impact

Uses MagicMock to avoid real LM Studio dependency.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from src.core.search.engine import Searcher


# ─── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def searcher():
    """Create a Searcher with mocked indexer and embedder."""
    indexer = MagicMock()
    embedder = MagicMock()
    return Searcher(indexer, embedder)


def _make_result(file_name: str, chunk_idx: int = 0, score: float = 0.8) -> dict:
    """Helper to create a mock search result."""
    return {
        "metadata": {"file": file_name, "chunk_index": chunk_idx},
        "text": f"code in {file_name}",
        "final_score": score,
    }


def _make_results(count: int, prefix: str = "file") -> list:
    """Helper to create multiple mock search results."""
    return [_make_result(f"{prefix}{i}.py", i, 0.9 - i * 0.01) for i in range(count)]


# ─── Benchmark: Simple Query ────────────────────────────────────────────────


class TestBenchmarkSimpleQuery:
    """Benchmark: simple single-concept query.

    Hybrid search should be faster since it skips decomposition overhead.
    Agentic search adds LLM/rules decomposition latency even for simple queries.
    """

    @pytest.mark.benchmark
    def test_benchmark_simple_query(self, searcher):
        """Compare agentic vs hybrid for a simple 1-concept query."""
        simple_results = _make_results(3, "simple")
        searcher.hybrid_search = MagicMock(return_value=simple_results)

        # Benchmark hybrid_search
        start_hybrid = time.time()
        hybrid_results = searcher.hybrid_search("auth", limit=5)
        hybrid_time = time.time() - start_hybrid

        # Benchmark agentic_code_search
        start_agentic = time.time()
        agentic_results, meta = searcher.agentic_code_search("auth")
        agentic_time = time.time() - start_agentic

        # Assertions
        assert len(hybrid_results) > 0
        assert len(agentic_results) > 0
        assert meta["decomposition_method"] == "none"

        # Log timing (printed in pytest output with -v)
        print(f"\n[Benchmark Simple] hybrid={hybrid_time*1000:.2f}ms, agentic={agentic_time*1000:.2f}ms")

        # For simple queries, hybrid should not be slower than agentic
        # (agentic has decomposition overhead)
        assert hybrid_time <= agentic_time * 1.5, (
            f"Hybrid ({hybrid_time*1000:.2f}ms) should not be much slower "
            f"than agentic ({agentic_time*1000:.2f}ms) for simple queries"
        )


# ─── Benchmark: Complex Query ───────────────────────────────────────────────


class TestBenchmarkComplexQuery:
    """Benchmark: complex multi-concept query (3+ concepts).

    Agentic search should find more unique results due to decomposition
    and parallel subquery execution, even though it takes more time.
    """

    @pytest.mark.benchmark
    def test_benchmark_complex_query(self, searcher):
        """Compare agentic vs hybrid for a complex 3-concept query."""
        # Hybrid returns the same results regardless of query complexity
        hybrid_results_set = _make_results(5, "hybrid")
        searcher.hybrid_search = MagicMock(return_value=hybrid_results_set)

        # Agentic returns different results per subquery (simulating decomposition)
        call_count = 0

        def mock_hybrid_search(query, limit=5, use_rrf=True, expand=True):
            nonlocal call_count
            call_count += 1
            return _make_results(5, f"sq{call_count}")

        searcher.hybrid_search = MagicMock(side_effect=mock_hybrid_search)

        complex_query = (
            "как работает авторизация и где проверяются права "
            "и что делает middleware"
        )

        # Benchmark hybrid_search (single pass)
        start_hybrid = time.time()
        hybrid_results = searcher.hybrid_search(complex_query, limit=10)
        hybrid_time = time.time() - start_hybrid

        # Benchmark agentic_code_search (decomposed search)
        start_agentic = time.time()
        agentic_results, meta = searcher.agentic_code_search(
            complex_query, max_total_results=10
        )
        agentic_time = time.time() - start_agentic

        # Assertions: agentic should find more unique results
        hybrid_files = {r["metadata"]["file"] for r in hybrid_results}
        agentic_files = {r["metadata"]["file"] for r in agentic_results}

        print(
            f"\n[Benchmark Complex] hybrid={hybrid_time*1000:.2f}ms "
            f"({len(hybrid_results)} results, {len(hybrid_files)} unique files), "
            f"agentic={agentic_time*1000:.2f}ms "
            f"({len(agentic_results)} results, {len(agentic_files)} unique files)"
        )

        # Agentic should have more unique files due to decomposition
        assert len(agentic_files) >= len(hybrid_files), (
            f"Agentic ({len(agentic_files)} unique files) should find >= "
            f"hybrid ({len(hybrid_files)} unique files) for complex queries"
        )

        # Agentic should have multiple subqueries
        assert len(meta["subqueries"]) >= 2

        # Agentic should be expected to take more time (decomposition + parallel search)
        # but should still be reasonable (< 500ms absolute for mocked test)
        assert agentic_time < 0.5, (
            f"Agentic ({agentic_time*1000:.2f}ms) should be under 500ms "
            f"even with ThreadPoolExecutor overhead"
        )


# ─── Benchmark: Decomposition Quality ───────────────────────────────────────


class TestBenchmarkDecompositionQuality:
    """Benchmark: LLM vs rule-based decomposition quality.

    Measures:
    - Number of subqueries generated
    - Coverage (unique results / total results)
    - Time overhead of LLM decomposition
    """

    @pytest.mark.benchmark
    def test_benchmark_decomposition_quality(self, searcher):
        """Compare rule-based decomposition for different query complexities."""
        # Mock hybrid_search to return predictable results per query
        search_results_map = {
            "auth": [_make_result("auth.py", 0, 0.95)],
            "permissions": [_make_result("perms.py", 0, 0.90)],
            "middleware": [_make_result("mw.py", 0, 0.85)],
            "как работает auth": [_make_result("auth.py", 0, 0.95)],
            "где проверяются permissions": [_make_result("perms.py", 0, 0.90)],
            "что делает middleware": [_make_result("mw.py", 0, 0.85)],
        }

        def mock_hybrid_search(query, limit=5, use_rrf=True, expand=True):
            for key, results in search_results_map.items():
                if key in query.lower():
                    return results
            return [_make_result(f"general_{hash(query) % 100}.py", 0, 0.5)]

        searcher.hybrid_search = MagicMock(side_effect=mock_hybrid_search)

        # Test with rule-based decomposition (LLM unavailable)
        complex_query = (
            "как работает auth и где проверяются permissions и что делает middleware"
        )

        start = time.time()
        results, meta = searcher.agentic_code_search(complex_query)
        elapsed = time.time() - start

        subqueries = meta["subqueries"]
        decomposition_method = meta["decomposition_method"]

        print(
            f"\n[Benchmark Decomposition] method={decomposition_method}, "
            f"subqueries={len(subqueries)}, results={len(results)}, "
            f"time={elapsed*1000:.2f}ms"
        )
        print(f"  Subqueries: {subqueries}")

        # Assertions
        assert len(subqueries) >= 2, "Should decompose into at least 2 subqueries"
        assert decomposition_method in ("llm", "rules"), (
            f"Unexpected decomposition method: {decomposition_method}"
        )
        assert len(results) >= 3, (
            f"Should find at least 3 unique results for 3-concept query, got {len(results)}"
        )

    @pytest.mark.benchmark
    def test_benchmark_llm_vs_rules_speed(self, searcher):
        """Compare decomposition speed: LLM (mocked as slow) vs rules."""
        # Simulate slow LLM decomposition
        def slow_llm_decompose(query):
            time.sleep(0.1)  # Simulate 100ms LLM latency
            return ["subquery 1", "subquery 2", "subquery 3"]

        # Patch _try_llm_decompose to be slow
        with patch.object(searcher, '_try_llm_decompose', side_effect=slow_llm_decompose):
            searcher.hybrid_search = MagicMock(return_value=_make_results(3))

            start = time.time()
            results, meta = searcher.agentic_code_search("сложный запрос и проверка")
            llm_time = time.time() - start

        # Now test with rules only (no LLM)
        with patch.object(searcher, '_try_llm_decompose', return_value=None):
            searcher.hybrid_search = MagicMock(return_value=_make_results(3))

            start = time.time()
            results, meta = searcher.agentic_code_search("сложный запрос и проверка")
            rules_time = time.time() - start

        print(
            f"\n[Benchmark LLM vs Rules] llm={llm_time*1000:.2f}ms, "
            f"rules={rules_time*1000:.2f}ms"
        )

        # Rules should be faster than LLM
        assert rules_time < llm_time, (
            f"Rules ({rules_time*1000:.2f}ms) should be faster "
            f"than LLM ({llm_time*1000:.2f}ms)"
        )


# ─── Benchmark: Call Graph Overhead ─────────────────────────────────────────


class TestBenchmarkCallGraphOverhead:
    """Benchmark: overhead of Call Graph analysis in agentic search.

    Compares agentic search with and without symbol_index to measure
    the impact of _analyze_subquery_relations on latency.
    """

    @pytest.mark.benchmark
    def test_benchmark_call_graph_overhead(self, searcher):
        """Measure latency with and without Call Graph analysis."""
        # Setup: mock hybrid_search to return results with overlapping files
        shared_results = [
            _make_result("shared.py", 0, 0.95),
            _make_result("auth.py", 0, 0.90),
            _make_result("perms.py", 0, 0.85),
        ]
        searcher.hybrid_search = MagicMock(return_value=shared_results)

        # Mock symbol_index with slow build_call_graph
        mock_symbol_index = MagicMock()

        def slow_build_call_graph(*args, **kwargs):
            time.sleep(0.05)  # Simulate 50ms call graph construction
            return {"auth": ["perms"], "perms": ["shared"]}

        mock_symbol_index.build_call_graph = MagicMock(
            side_effect=slow_build_call_graph
        )

        # Benchmark WITHOUT symbol_index
        with patch.object(searcher, '_analyze_subquery_relations') as mock_analyze:
            mock_analyze.return_value = {
                "coverage_score": 0.0,
                "common_files": [],
                "flow_description": "",
            }

            start = time.time()
            results_without_cg, meta_without = searcher.agentic_code_search(
                "auth и permissions и middleware"
            )
            time_without_cg = time.time() - start

        # Benchmark WITH symbol_index (real _analyze_subquery_relations)
        # Need to mock SymbolIndex methods used by _analyze_subquery_relations
        with patch.object(searcher, '_analyze_subquery_relations', wraps=searcher._analyze_subquery_relations) as wrapped_analyze:
            # Setup symbol_index mock to return realistic data (build_call_graph API)
            mock_symbol_index = MagicMock()
            mock_symbol_index.get_symbols_in_file.return_value = ["auth", "check_permissions"]
            mock_symbol_index.build_call_graph.return_value = {
                "symbol": "auth",
                "definition": [{"file": "auth.py", "line": 10, "kind": "function"}],
                "callers": [{"file": "routes.py", "line": 5, "kind": "call"}],
                "callees": [{"symbol": "validate", "file": "auth.py", "line": 15, "kind": "function"}],
                "impact_files": ["auth.py", "routes.py"],
            }

            start = time.time()
            results_with_cg, meta_with = searcher.agentic_code_search(
                "auth и permissions и middleware",
                symbol_index=mock_symbol_index,
            )
            time_with_cg = time.time() - start

        print(
            f"\n[Benchmark Call Graph] without_cg={time_without_cg*1000:.2f}ms, "
            f"with_cg={time_with_cg*1000:.2f}ms, "
            f"overhead={((time_with_cg - time_without_cg) / max(time_without_cg, 0.001)) * 100:.1f}%"
        )

        # Both should produce valid results
        assert len(results_without_cg) > 0
        assert len(results_with_cg) > 0

        # Call graph overhead should be reasonable (< 3x total time)
        assert time_with_cg <= time_without_cg * 3.0, (
            f"Call graph analysis ({time_with_cg*1000:.2f}ms) should not be >3x "
            f"baseline ({time_without_cg*1000:.2f}ms)"
        )

    @pytest.mark.benchmark
    def test_benchmark_call_graph_with_realistic_data(self, searcher):
        """Benchmark call graph analysis with realistic symbol index data."""
        # Create results that share files (common scenario)
        results_sq1 = [
            _make_result("auth/handler.py", 0, 0.95),
            _make_result("auth/validator.py", 0, 0.90),
            _make_result("shared/utils.py", 0, 0.80),
        ]
        results_sq2 = [
            _make_result("auth/validator.py", 0, 0.92),
            _make_result("auth/permissions.py", 0, 0.88),
            _make_result("shared/utils.py", 0, 0.85),
        ]
        results_sq3 = [
            _make_result("auth/permissions.py", 0, 0.91),
            _make_result("auth/decorator.py", 0, 0.87),
            _make_result("shared/types.py", 0, 0.82),
        ]

        call_count = 0

        def mock_hybrid_search(query, limit=5, use_rrf=True, expand=True):
            nonlocal call_count
            call_count += 1
            mapping = {
                1: results_sq1,
                2: results_sq2,
                3: results_sq3,
            }
            return mapping.get(call_count, [_make_result(f"default{call_count}.py")])

        searcher.hybrid_search = MagicMock(side_effect=mock_hybrid_search)

        # Benchmark
        start = time.time()
        results, meta = searcher.agentic_code_search(
            "как работает auth handler и где проверяются permissions и что делает decorator"
        )
        elapsed = time.time() - start

        relations = meta.get("relations", {})

        print(
            f"\n[Benchmark Call Graph Realistic] "
            f"results={len(results)}, "
            f"relations={relations.get('coverage_score', 'N/A')}, "
            f"common_files={len(relations.get('common_files', []))}, "
            f"time={elapsed*1000:.2f}ms"
        )

        # Assertions
        assert len(results) > 0
        assert relations is not None
        assert "coverage_score" in relations


# ─── Benchmark: End-to-End Comparison ────────────────────────────────────────


class TestBenchmarkEndToEnd:
    """End-to-end benchmark comparing all search modes."""

    @pytest.mark.benchmark
    def test_benchmark_e2e_comparison(self, searcher):
        """Run a comprehensive comparison of search modes."""
        test_cases = [
            ("simple", "auth"),
            ("medium", "auth и permissions"),
            ("complex", "как работает авторизация и где проверяются права и что делает middleware"),
        ]

        results_table = []

        for label, query in test_cases:
            # Mock fresh results for each call
            searcher.hybrid_search = MagicMock(return_value=_make_results(5, f"{label}_hybrid"))

            # Hybrid
            start = time.time()
            hybrid_results = searcher.hybrid_search(query, limit=10)
            hybrid_time = time.time() - start

            # Agentic
            call_count = 0

            def mock_hybrid_sq(q, limit=5, use_rrf=True, expand=True):
                nonlocal call_count
                call_count += 1
                return _make_results(5, f"{label}_sq{call_count}")

            searcher.hybrid_search = MagicMock(side_effect=mock_hybrid_sq)

            start = time.time()
            agentic_results, meta = searcher.agentic_code_search(query, max_total_results=10)
            agentic_time = time.time() - start

            results_table.append({
                "label": label,
                "query": query[:40],
                "hybrid_ms": hybrid_time * 1000,
                "agentic_ms": agentic_time * 1000,
                "hybrid_count": len(hybrid_results),
                "agentic_count": len(agentic_results),
                "subqueries": len(meta["subqueries"]),
            })

        # Print results table
        print("\n[Benchmark E2E Results]")
        print(f"{'Type':<10} {'Hybrid(ms)':<12} {'Agentic(ms)':<13} {'H-Count':<9} {'A-Count':<9} {'SubQ':<6}")
        print("-" * 60)
        for row in results_table:
            print(
                f"{row['label']:<10} {row['hybrid_ms']:<12.2f} {row['agentic_ms']:<13.2f} "
                f"{row['hybrid_count']:<9} {row['agentic_count']:<9} {row['subqueries']:<6}"
            )

        # All queries should return results
        for row in results_table:
            assert row["hybrid_count"] > 0, f"Hybrid returned 0 results for {row['label']}"
            assert row["agentic_count"] > 0, f"Agentic returned 0 results for {row['label']}"
