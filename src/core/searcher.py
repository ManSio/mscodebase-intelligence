import logging
import math
import re
import threading
from typing import Dict, List, Optional

from src.core.query_expansion import expand_query
from src.core.reranker import SearchResultReranker

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
        self._reranker = SearchResultReranker(bm25_weight=0.3, dense_weight=0.7)

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

    def _reciprocal_rank_fusion(
        self,
        bm25_results: List[dict],
        dense_results: List[dict],
        limit: int = 5,
        rrf_k: int = 60,
    ) -> List[dict]:
        """Reciprocal Rank Fusion (RRF) для объединения BM25 и dense результатов.

        Формула: rrf_score(d) = Σ 1/(k + rank_i(d))
        RRF устойчив к разным масштабам скоров и не требует нормализации.

        Args:
            bm25_results: Результаты BM25 поиска
            dense_results: Результаты векторного поиска
            limit: Максимальное число результатов
            rrf_k: Константа RRF (обычно 60), сглаживает вклад рангов
        """
        scores: Dict[str, float] = {}
        results_map: Dict[str, dict] = {}

        # BM25 ранги
        for rank, result in enumerate(bm25_results, 1):
            key = f"{result['metadata']['file']}:{result['metadata']['chunk_index']}"
            scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank)
            if key not in results_map:
                results_map[key] = {**result, "bm25_score": 1.0 / (rrf_k + rank), "dense_score": 0.0}
            else:
                results_map[key]["bm25_score"] = 1.0 / (rrf_k + rank)

        # Dense ранги
        for rank, result in enumerate(dense_results, 1):
            key = f"{result['metadata']['file']}:{result['metadata']['chunk_index']}"
            scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank)
            if key not in results_map:
                results_map[key] = {**result, "bm25_score": 0.0, "dense_score": 1.0 / (rrf_k + rank)}
            else:
                results_map[key]["dense_score"] = 1.0 / (rrf_k + rank)

        # Сортировка по RRF скору
        sorted_keys = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)[:limit]

        results = []
        for key in sorted_keys:
            result = results_map[key]
            results.append({
                "text": result["text"],
                "metadata": result["metadata"],
                "bm25_score": result["bm25_score"],
                "dense_score": result["dense_score"],
                "final_score": scores[key],
            })

        return results

    def hybrid_search(self, query: str, limit: int = 5, use_rrf: bool = True, expand: bool = True) -> List[dict]:
        """Гибридный поиск: комбинирует BM25 (sparse) и векторный (dense) поиск.

        Алгоритм:
        1. (Опционально) Расширяем запрос синонимами через query expansion
        2. Выполняем BM25 поиск для точных совпадений терминов
        3. Выполняем векторный поиск для семантически релевантных результатов
        4. Объединяем через RRF (Reciprocal Rank Fusion) или реранкер

        Args:
            query: Поисковый запрос
            limit: Максимальное число результатов
            use_rrf: Использовать RRF (True) или реранкер (False)
            expand: Использовать query expansion (синонимы, стемминг)
        """
        # Query Expansion: генерируем варианты запроса
        if expand:
            query_variants = expand_query(query, max_expansions=3)
        else:
            query_variants = [query]

        # Собираем результаты от всех вариантов
        all_bm25_results = []
        all_dense_results = []

        for variant in query_variants:
            # BM25 поиск (sparse)
            bm25_results = self._bm25_search(variant, limit=limit * 2)
            all_bm25_results.extend(bm25_results)

            # Векторный поиск (dense) — только для оригинального запроса
            # (варианты синонимов дают те же эмбеддинги)
            if variant == query and not all_dense_results:
                try:
                    query_vector = self.embedder.embed(variant)
                    if query_vector:
                        dense_results = self.vector_search(query_vector, limit=limit * 2)
                        all_dense_results = [r for r in dense_results if "error" not in r]
                except Exception as e:
                    logger.warning(f"Не удалось выполнить dense поиск: {e}")

        # Дедупликация BM25 результатов
        seen_keys = set()
        unique_bm25 = []
        for r in all_bm25_results:
            key = f"{r['metadata']['file']}:{r['metadata']['chunk_index']}"
            if key not in seen_keys:
                seen_keys.add(key)
                unique_bm25.append(r)

        if use_rrf:
            # RRF Fusion — устойчив к разным масштабам скоров
            return self._reciprocal_rank_fusion(unique_bm25, all_dense_results, limit=limit)
        else:
            # Fallback: реранкер с relevance factor
            reranked = self._reranker.rerank_results(
                query, unique_bm25, all_dense_results, limit=limit
            )
            results = []
            for res in reranked:
                results.append({
                    "text": res["text"],
                    "metadata": res["metadata"],
                    "bm25_score": res.get("bm25_score", 0.0),
                    "dense_score": res.get("dense_score", 0.0),
                    "final_score": res.get("final_score", 0.0),
                })
            return results

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

    def context_search(self, selected_code: str, limit: int = 5) -> str:
        """Поиск похожего кода по выделенному фрагменту.

        Эмбеддит выделенный код и ищет семантически похожие чанки.
        Полезно для: поиска дубликатов, похожих реализаций, альтернативных подходов.

        Args:
            selected_code: Выделенный фрагмент кода
            limit: Максимальное число результатов
        """
        if not selected_code.strip():
            return "❌ Пустой фрагмент кода для поиска."

        try:
            query_vector = self.embedder.embed(selected_code)
            if not query_vector:
                return "❌ Эмбеддер недоступен. Невозможно векторизовать код."

            results = self.vector_search(query_vector, limit=limit)
            results = [r for r in results if "error" not in r]

            if not results:
                return "🔍 Похожий код не найден."

            # Фильтруем точные совпадения (тот же текст = дубликат)
            unique_results = []
            seen_texts = set()
            for r in results:
                text_key = r["text"].strip()[:200]
                if text_key not in seen_texts and r["text"].strip() != selected_code.strip():
                    seen_texts.add(text_key)
                    unique_results.append(r)

            if not unique_results:
                return "🔍 Точные совпадения найдены, но уникальных похожих фрагментов нет."

            output = [
                f"🔍 Найдено {len(unique_results)} похожих фрагментов кода:\n"
            ]
            for i, res in enumerate(unique_results, 1):
                output.append(
                    f"{i}. 📄 {res['metadata']['file']} [Чанк #{res['metadata']['chunk_index']}]\n"
                    f"```\n{res['text'][:500]}\n```\n"
                    f"{'-' * 60}\n"
                )
            return "".join(output)
        except Exception as e:
            logger.error(f"Ошибка context_search: {e}")
            return f"❌ Ошибка поиска по коду: {str(e)}"
