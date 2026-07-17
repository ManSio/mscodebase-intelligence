"""Cypher query engine — компонент для подмножества openCypher."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from src.core.search.cypher_ast import Query
from src.core.search.cypher_lexer import CypherLexer
from src.core.search.cypher_parser import CypherParser
from src.core.search.cypher_sql import CypherToSQL

logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════
# Executor
# ════════════════════════════════════════════════════════════

class CypherExecutor:
    """Выполняет Cypher-запросы на PropertyGraph.

    Использование:
        executor = CypherExecutor(property_graph)
        result = executor.execute("MATCH (f:Function)-[:CALLS]->(g) RETURN f.name, g.name LIMIT 10")
    """

    def __init__(self, graph):
        self._graph = graph
        self._parser_cache: Dict[str, Query] = {}

    def execute(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Выполняет Cypher-запрос и возвращает результаты.

        Args:
            query: Cypher-like запрос
            params: Параметры (пока не используются, только для API совместимости)

        Returns:
            {
                "columns": ["f.name", "g.name"],
                "results": [{"f.name": "...", "g.name": "..."}],
                "stats": {"elapsed_ms": 5, "rows": 10}
            }
        """
        import time

        start = time.monotonic()

        try:
            # 1. Lex
            lexer = CypherLexer(query)
            tokens = lexer.tokenize()

            # 2. Parse
            parser = CypherParser(tokens)
            ast = parser.parse()

            # 3. Translate to SQL
            translator = CypherToSQL(self._graph)
            sql, sql_params = translator.translate(ast)

            # 4. Execute
            conn = self._graph._get_conn()
            cursor = conn.execute(sql, sql_params)
            rows = cursor.fetchall()

            # 5. Format results
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            results = []
            for row in rows:
                result_row = {}
                for i, col in enumerate(columns):
                    result_row[col] = row[i]
                results.append(result_row)

            elapsed = (time.monotonic() - start) * 1000

            return {
                "columns": columns,
                "results": results,
                "stats": {
                    "elapsed_ms": round(elapsed, 1),
                    "rows": len(results),
                    "sql": sql,
                    "sql_params": sql_params,
                },
            }

        except SyntaxError as e:
            return {
                "columns": [],
                "results": [],
                "error": f"Syntax error: {e}",
                "stats": {"elapsed_ms": 0, "rows": 0, "sql": ""},
            }
        except Exception as e:
            logger.exception(f"Cypher execution failed: {e}")
            return {
                "columns": [],
                "results": [],
                "error": str(e),
                "stats": {"elapsed_ms": 0, "rows": 0, "sql": ""},
            }

    def execute_with_explain(self, query: str) -> Dict[str, Any]:
        """Выполняет запрос и возвращает результат + explain."""
        result = self.execute(query)
        result["explain"] = {
            "cypher": query,
            "parsed_tokens": len(CypherLexer(query).tokenize()),
        }
        return result
