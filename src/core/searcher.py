import logging
import re
import threading
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class Searcher:
    """Выполняет гибридный семантический поиск по кодовой базе."""

    def __init__(self, indexer, embedder):
        self.indexer = indexer
        self.embedder = embedder
        self._bm25 = None
        self._bm25_ids: List[str] = []
        self._bm25_lock = threading.Lock()
        self._tokenizer_re = re.compile(r"\W+")

    def reindex(self):
        with self._bm25_lock:
            self._bm25 = None
            self._bm25_ids = []
            logger.debug("🔄 Индекс BM25 сброшен для реиндексации")

    def vector_search(self, query_vector: List[float], limit: int = 5) -> List[dict]:
        """Прямой векторный поиск через таблицу LanceDB."""
        if self.indexer.table is None or len(self.indexer.table) == 0:
            return []
        try:
            df = self.indexer.table.search(query_vector).limit(limit).to_pandas()
            results = []
            for _, row in df.iterrows():
                results.append(
                    {
                        "text": row["text"],
                        "metadata": {
                            "file": row["file_path"],
                            "chunk_index": row["chunk_index"],
                        },
                    }
                )
            return results
        except Exception as e:
            logger.error(f"Ошибка векторного поиска LanceDB: {e}")
            return []

    def search(self, query: str, limit: int = 5) -> str:
        """Фолбэк-метод гибридного поиска для MCP-инструмента search_code."""
        try:
            query_vector = self.embedder.embed(query)
            v_results = self.vector_search(query_vector, limit=limit)
            if not v_results:
                return "🔍 По запросу ничего не найдено (база пуста или эмбеддер недоступен)."

            output = [f"📊 Найдено {len(v_results)} релевантных фрагментов кода:\n"]
            for i, res in enumerate(v_results, 1):
                output.append(
                    f"{i}. 📄 {res['metadata']['file']} [Чанк #{res['metadata']['chunk_index']}]\n"
                    f"```\n{res['text']}\n```\n"
                    f"{'-' * 60}\n"
                )
            return "".join(output)
        except Exception as e:
            return f"❌ Ошибка поискового движка: {str(e)}"
