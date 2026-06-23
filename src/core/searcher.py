import logging
import math
import re
import threading
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def _tokenize(text: str, tokenizer_re: re.Pattern) -> List[str]:
    """Простейшее токенизирование для BM25."""
    return tokenizer_re.split(text.lower()) if text else []


class Searcher:
    """Выполняет гибридный семантический поиск по кодовой базе."""

    def __init__(self, indexer, embedder):
        self.indexer = indexer
        self.embedder = embedder
        self._bm25: Optional[Dict[str, Dict[str, float]]] = None
        self._bm25_ids: List[str] = []
        self._bm25_lock = threading.Lock()
        self._tokenizer_re = re.compile(r"\W+")

    def reindex(self):
        with self._bm25_lock:
            self._bm25 = None
            self._bm25_ids = []
            logger.debug("🔄 Индекс BM25 сброшен для реиндексации")

    def _build_bm25_index(self) -> None:
        """Ленивая инициализация BM25 индекса из текущей таблицы LanceDB."""
        if self._bm25 is not None:
            return
        if self.indexer.table is None or len(self.indexer.table) == 0:
            return

        try:
            df = self.indexer.table.to_pandas()
            if df.empty:
                return

            # Считаем TF для каждого термина в каждом документе
            doc_count = len(df)
            term_doc_freq: Dict[str, int] = {}
            term_doc_scores: Dict[str, Dict[str, float]] = {}

            for idx, row in df.iterrows():
                doc_id = f"{row['file_path']}:{row['chunk_index']}"
                text = str(row.get("text", ""))
                tokens = _tokenize(text, self._tokenizer_re)

                # TF (частота термина в документе)
                term_tf: Dict[str, float] = {}
                for token in tokens:
                    term_tf[token] = term_tf.get(token, 0) + 1

                # Сохраняем TF для документа
                self._bm25_ids.append(doc_id)
                term_doc_scores[doc_id] = term_tf

                # DF (число документов, содержащих термин)
                for token in term_tf:
                    term_doc_freq[token] = term_doc_freq.get(token, 0) + 1

            # Вычисляем IDF: log((N - df + 0.5) / (df + 0.5))
            self._bm25 = {}
            for doc_id, tf_dict in term_doc_scores.items():
                self._bm25[doc_id] = {}
                for term, tf in tf_dict.items():
                    df = term_doc_freq.get(term, 0)
                    idf = math.log((doc_count - df + 0.5) / (df + 0.5) + 1)
                    self._bm25[doc_id][term] = tf * idf

            logger.debug(f"📊 BM25 индекс построен: {len(self._bm25)} документов")
        except Exception as e:
            logger.error(f"Ошибка построения BM25 индекса: {e}")

    def _bm25_search(self, query: str, limit: int = 5) -> List[dict]:
        """Полнотекстовый поиск BM25 по текущей базе."""
        self._build_bm25_index()
        if not self._bm25:
            return []

        query_tokens = _tokenize(query, self._tokenizer_re)
        scores: Dict[str, float] = {}

        for doc_id in self._bm25_ids:
            scores[doc_id] = 0.0
            for token in query_tokens:
                scores[doc_id] += self._bm25[doc_id].get(token, 0.0)

        # Сортируем по убыванию скора
        top_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)[:limit]

        # Формируем результаты
        results = []
        try:
            df = self.indexer.table.to_pandas()
            for doc_id in top_ids:
                if scores[doc_id] <= 0:
                    continue
                file_path, chunk_idx = doc_id.rsplit(":", 1)
                match = df[
                    (df["file_path"] == file_path)
                    & (df["chunk_index"] == int(chunk_idx))
                ]
                if not match.empty:
                    row = match.iloc[0]
                    results.append(
                        {
                            "text": row["text"],
                            "metadata": {
                                "file": row["file_path"],
                                "chunk_index": row["chunk_index"],
                            },
                        }
                    )
        except Exception as e:
            logger.error(f"Ошибка выполнения BM25 поиска: {e}")

        return results

    def vector_search(self, query_vector: List[float], limit: int = 5) -> List[dict]:
        """Прямой векторный поиск через таблицу LanceDB."""
        if self.indexer.table is None or len(self.indexer.table) == 0:
            return []

        try:
            df = (
                self.indexer.table.search(query_vector, vector_column_name="vector")
                .limit(limit)
                .to_pandas()
            )
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
            return [{"error": str(e)}]

    def hybrid_search(self, query: str, limit: int = 5) -> List[dict]:
        """Гибридный поиск: комбинирует BM25 (sparse) и векторный (dense) поиск.

        Алгоритм:
        1. Выполняем BM25 поиск для точных совпадений терминов
        2. Выполняем векторный поиск для семантически релевантных результатов
        3. Объединяем результаты с весом: BM25 = 0.3, Dense = 0.7
        """
        results_map: Dict[str, dict] = {}

        # BM25 поиск (sparse)
        bm25_results = self._bm25_search(query, limit=limit * 2)
        for i, res in enumerate(bm25_results):
            key = f"{res['metadata']['file']}:{res['metadata']['chunk_index']}"
            results_map[key] = {
                "text": res["text"],
                "metadata": res["metadata"],
                "bm25_score": 1.0 - (i / len(bm25_results)) if bm25_results else 0,
                "dense_score": 0.0,
            }

        # Векторный поиск (dense)
        try:
            query_vector = self.embedder.embed(query)
            if query_vector:
                dense_results = self.vector_search(query_vector, limit=limit * 2)
                for i, res in enumerate(dense_results):
                    if "error" in res:
                        continue
                    key = f"{res['metadata']['file']}:{res['metadata']['chunk_index']}"
                    if key in results_map:
                        results_map[key]["dense_score"] = 1.0 - (i / len(dense_results))
                    else:
                        results_map[key] = {
                            "text": res["text"],
                            "metadata": res["metadata"],
                            "bm25_score": 0.0,
                            "dense_score": 1.0 - (i / len(dense_results)),
                        }
        except Exception as e:
            logger.warning(f"Не удалось выполнить dense поиск: {e}")

        # Комбинируем скоры
        combined = []
        for key, res in results_map.items():
            final_score = res["bm25_score"] * 0.3 + res["dense_score"] * 0.7
            combined.append((final_score, res))

        # Сортируем и ограничиваем
        combined.sort(key=lambda x: x[0], reverse=True)
        return [res for _, res in combined[:limit]]

    def search(self, query: str, limit: int = 5) -> str:
        """Гибридный поиск для MCP-инструмента search_code."""
        try:
            results = self.hybrid_search(query, limit=limit)
            if not results:
                return "🔍 По запросу ничего не найдено (база пуста или эмбеддер недоступен)."

            output = [
                f"📊 Найдено {len(results)} релевантных фрагментов кода (гибридный поиск):\n"
            ]
            for i, res in enumerate(results, 1):
                output.append(
                    f"{i}. 📄 {res['metadata']['file']} [Чанк #{res['metadata']['chunk_index']}]\n"
                    f"```\n{res['text']}\n```\n"
                    f"{'-' * 60}\n"
                )
            return "".join(output)
        except Exception as e:
            return f"❌ Ошибка поискового движка: {str(e)}"
