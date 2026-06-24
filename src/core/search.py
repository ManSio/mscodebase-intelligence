"""
Hybrid search engine combining vector and lexical search.
Implements Reciprocal Rank Fusion (RRF) for optimal result merging.
"""

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class HybridSearchEngine:
    """Hybrid search engine combining vector and lexical search with RRF fusion."""

    def __init__(self, vector_storage=None, lexical_indexer=None):
        self.vector_storage = vector_storage
        self.lexical_indexer = lexical_indexer
        self.rrf_k = 60  # RRF constant for score calculation

    def search(
        self, query: str, filters: Optional[Dict] = None, top_k: int = 20
    ) -> List[Dict[str, Any]]:
        """Perform hybrid search combining vector and lexical results.

        Args:
            query: Search query
            filters: Optional filters for search
            top_k: Number of results to return

        Returns:
            List of search results with combined scores
        """
        logger.info(f"🔍 Hybrid search for: '{query}' (top_k={top_k})")

        # Parallel search in both indexes
        start_time = time.time()

        vector_results = self._vector_search(query, filters, top_k * 2)
        lexical_results = self._lexical_search(query, filters, top_k * 2)

        search_time = time.time() - start_time
        logger.debug(
            f"📊 Search completed in {search_time:.2f}s: "
            f"{len(vector_results)} vector, {len(lexical_results)} lexical results"
        )

        # Apply RRF fusion
        fused_results = self._reciprocal_rank_fusion(
            vector_results, lexical_results, top_k
        )

        # Enhance results with metadata
        enhanced_results = self._enhance_results(fused_results, query)

        logger.info(f"✅ Hybrid search returned {len(enhanced_results)} results")
        return enhanced_results

    def _vector_search(
        self, query: str, filters: Optional[Dict], limit: int
    ) -> List[Dict[str, Any]]:
        """Perform vector search using semantic embeddings."""
        if not self.vector_storage:
            logger.debug("⚠️ Vector storage not available")
            return []

        try:
            # Use vector storage to find semantically similar content
            results = self.vector_storage.search(query, limit, filters)

            # Convert to standardized format
            formatted_results = []
            for result in results:
                formatted_results.append(
                    {
                        "id": result.get("id", f"vec_{len(formatted_results)}"),
                        "content": result.get("content", ""),
                        "metadata": result.get("metadata", {}),
                        "score": result.get("score", 0.0),
                        "source": "vector",
                        "rank": len(formatted_results) + 1,
                    }
                )

            logger.debug(f"🧠 Vector search found {len(formatted_results)} results")
            return formatted_results

        except Exception as e:
            logger.warning(f"⚠️ Vector search failed: {e}")
            return []

    def _lexical_search(
        self, query: str, filters: Optional[Dict], limit: int
    ) -> List[Dict[str, Any]]:
        """Perform lexical search using keyword matching."""
        if not self.lexical_indexer:
            logger.debug("⚠️ Lexical indexer not available")
            return []

        try:
            # Use lexical indexer for keyword-based search
            results = self.lexical_indexer.search(query, limit, filters)

            # Convert to standardized format
            formatted_results = []
            for result in results:
                formatted_results.append(
                    {
                        "id": result.get("id", f"lex_{len(formatted_results)}"),
                        "content": result.get("content", ""),
                        "metadata": result.get("metadata", {}),
                        "score": result.get("score", 0.0),
                        "source": "lexical",
                        "rank": len(formatted_results) + 1,
                    }
                )

            logger.debug(f"📝 Lexical search found {len(formatted_results)} results")
            return formatted_results

        except Exception as e:
            logger.warning(f"⚠️ Lexical search failed: {e}")
            return []

    def _reciprocal_rank_fusion(
        self, vector_results: List[Dict], lexical_results: List[Dict], top_k: int
    ) -> List[Tuple[str, float]]:
        """Apply Reciprocal Rank Fusion to combine results.

        Args:
            vector_results: Results from vector search
            lexical_results: Results from lexical search
            top_k: Number of final results to return

        Returns:
            List of (result_id, fused_score) tuples
        """
        # Initialize score dictionary
        scores = {}

        # Process vector results
        for rank, result in enumerate(vector_results, 1):
            result_id = result["id"]
            # RRF formula: 1 / (k + rank) - protect against division by zero
            denominator = self.rrf_k + rank
            if denominator > 0:
                score = 1.0 / denominator
            else:
                score = 0.0
            scores[result_id] = scores.get(result_id, 0) + score

        # Process lexical results
        for rank, result in enumerate(lexical_results, 1):
            result_id = result["id"]
            # RRF formula: 1 / (k + rank) - protect against division by zero
            denominator = self.rrf_k + rank
            if denominator > 0:
                score = 1.0 / denominator
            else:
                score = 0.0
            scores[result_id] = scores.get(result_id, 0) + score

        # Sort by combined score and return top_k
        sorted_results = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        logger.debug(
            f"🔀 RRF fusion: {len(scores)} unique results, "
            f"top score: {sorted_results[0][1]:.4f if sorted_results else 0}"
        )

        return sorted_results[:top_k]

    def _enhance_results(
        self, fused_results: List[Tuple[str, float]], query: str
    ) -> List[Dict[str, Any]]:
        """Enhance fused results with additional metadata and context.

        Args:
            fused_results: List of (result_id, fused_score) tuples
            query: Original search query

        Returns:
            Enhanced search results
        """
        enhanced = []

        for result_id, fused_score in fused_results:
            # Find the original result from either index
            original_result = None

            # Check vector results
            for vec_result in self._get_last_vector_results():
                if vec_result["id"] == result_id:
                    original_result = vec_result
                    break

            # Check lexical results
            if not original_result:
                for lex_result in self._get_last_lexical_results():
                    if lex_result["id"] == result_id:
                        original_result = lex_result
                        break

            if original_result:
                # Enhance with additional metadata
                enhanced_result = {
                    **original_result,
                    "hybrid_score": fused_score,
                    "relevance": self._calculate_relevance(fused_score, query),
                    "source_confidence": self._calculate_source_confidence(
                        original_result
                    ),
                    "combined_rank": len(enhanced) + 1,
                }

                enhanced.append(enhanced_result)

        return enhanced

    def _calculate_relevance(self, score: float, query: str) -> str:
        """Calculate relevance level based on score."""
        if score > 0.1:
            return "high"
        elif score > 0.05:
            return "medium"
        else:
            return "low"

    def _calculate_source_confidence(self, result: Dict[str, Any]) -> float:
        """Calculate confidence based on source type."""
        source = result.get("source", "unknown")
        base_confidence = {"vector": 0.7, "lexical": 0.8, "hybrid": 0.9, "unknown": 0.5}
        return base_confidence.get(source, 0.5)

    def _get_last_vector_results(self) -> List[Dict[str, Any]]:
        """Get last vector search results (placeholder)."""
        # This would be implemented with proper result caching
        return []

    def _get_last_lexical_results(self) -> List[Dict[str, Any]]:
        """Get last lexical search results (placeholder)."""
        # This would be implemented with proper result caching
        return []

    def set_result_cache(self, vector_results: List[Dict], lexical_results: List[Dict]):
        """Set result cache for enhancement purposes."""
        self._last_vector_results = vector_results
        self._last_lexical_results = lexical_results


class AdvancedSearchEngine(HybridSearchEngine):
    """Advanced search engine with additional features."""

    def __init__(self, vector_storage=None, lexical_indexer=None, reranker=None):
        super().__init__(vector_storage, lexical_indexer)
        self.reranker = reranker

    def search(
        self,
        query: str,
        filters: Optional[Dict] = None,
        top_k: int = 20,
        include_expansion: bool = True,
    ) -> Dict[str, Any]:
        """Advanced search with result expansion and reranking.

        Args:
            query: Search query
            filters: Optional filters
            top_k: Number of results to return
            include_expansion: Whether to include related queries

        Returns:
            Comprehensive search results with metadata
        """
        logger.info(f"🚀 Advanced search for: '{query}'")

        # Initial hybrid search
        base_results = super().search(query, filters, top_k)

        # Result expansion (related queries)
        expanded_results = base_results
        if include_expansion:
            expanded_results = self._expand_search_results(base_results, query)

        # Reranking if configured
        final_results = expanded_results
        if self.reranker:
            final_results = self.reranker.rerank(query, expanded_results, top_k)

        # Compile comprehensive response
        response = {
            "query": query,
            "results": final_results,
            "metadata": {
                "total_results": len(final_results),
                "search_time": time.time(),
                "engine_version": "advanced_v1.0",
                "features": ["hybrid_search", "result_expansion", "reranking"],
            },
        }

        logger.info(f"✅ Advanced search completed: {len(final_results)} results")
        return response

    def _expand_search_results(
        self, base_results: List[Dict], query: str
    ) -> List[Dict[str, Any]]:
        """Expand search results with related queries and concepts."""
        expanded = list(base_results)  # Start with base results

        # Generate related queries based on original query
        related_queries = self._generate_related_queries(query)

        # Search for each related query
        for related_query in related_queries:
            if related_query != query:  # Skip duplicate
                related_results = super().search(related_query, top_k=5)

                # Add related results with lower weight
                for result in related_results:
                    result["expansion_source"] = related_query
                    result["expansion_weight"] = 0.5
                    expanded.append(result)

        logger.debug(f"🔗 Expanded search with {len(related_queries)} related queries")
        return expanded

    def _generate_related_queries(self, query: str) -> List[str]:
        """Generate related queries for search expansion."""
        # Simple query expansion - could be enhanced with NLP
        related = []

        # Add singular/plural variations
        if query.endswith("s"):
            related.append(query[:-1])
        else:
            related.append(query + "s")

        # Add common prefixes/suffixes
        prefixes = ["how to", "what is", "why", "when", "where"]
        for prefix in prefixes:
            if not query.startswith(prefix):
                related.append(f"{prefix} {query}")

        return related[:3]  # Limit to top 3 related queries
