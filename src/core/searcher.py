import json
import logging
import math
import re
import threading
from typing import Dict, List, Optional, Tuple

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

    def _extract_key_terms(self, results: List[dict], max_terms: int = 5) -> List[str]:
        """Извлекает ключевые термины из результатов поиска для уточнения запроса.

        Анализирует текст топ-результатов, выделяя редкие, но значимые термины,
        которые могут улучшить поиск на следующей итерации.

        Args:
            results: Результаты поиска
            max_terms: Максимальное число терминов для извлечения

        Returns:
            Список ключевых терминов
        """
        if not results:
            return []

        # Собираем частотность терминов в результатах
        term_freq: Dict[str, int] = {}
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
            "have", "has", "had", "do", "does", "did", "will", "would", "could",
            "should", "may", "might", "shall", "can", "need", "dare", "ought",
            "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
            "as", "into", "through", "during", "before", "after", "above", "below",
            "between", "out", "off", "over", "under", "again", "further", "then",
            "once", "here", "there", "when", "where", "why", "how", "all", "each",
            "every", "both", "few", "more", "most", "other", "some", "such", "no",
            "nor", "not", "only", "own", "same", "so", "than", "too", "very",
            "just", "because", "but", "and", "or", "if", "while", "return", "def",
            "class", "import", "from", "self", "none", "true", "false", "pass",
            "that", "this", "it", "its", "what", "which", "who", "whom",
        }

        for r in results[:5]:
            text = r.get("text", "").lower()
            # Извлекаем идентификаторы (CamelCase, snake_case)
            tokens = re.findall(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", text)
            for token in tokens:
                if len(token) >= 4 and token not in stop_words:
                    term_freq[token] = term_freq.get(token, 0) + 1

        # Сортируем по частотности, берём топ-N самых редких (но встречающихся)
        sorted_terms = sorted(term_freq.items(), key=lambda x: x[1], reverse=True)
        # Предпочитаем термины, которые встречаются в 2+ документах (значимые)
        significant = [t for t, f in sorted_terms if f >= 2][:max_terms]
        # Если нет значимых, берём топ-N по частотности
        if not significant:
            significant = [t for t, _ in sorted_terms[:max_terms]]

        return significant

    def _generate_refined_query(
        self, original_query: str, key_terms: List[str], iteration: int
    ) -> str:
        """Генерирует уточнённый запрос на основе ключевых терминов.

        Стратегия:
        - Итерация 1: оригинальный запрос + топ-3 ключевых термина
        - Итерация 2: только ключевые термины (если первый поиск дал мало)

        Args:
            original_query: Оригинальный запрос
            key_terms: Извлечённые ключевые термины
            iteration: Номер итерации (1 или 2)

        Returns:
            Уточнённый запрос
        """
        if not key_terms:
            return original_query

        if iteration == 1:
            # Добавляем ключевые термины к оригинальному запросу
            top_terms = key_terms[:3]
            return f"{original_query} {' '.join(top_terms)}"
        else:
            # Вторая итерация: фокусируемся на ключевых терминах
            return " ".join(key_terms[:5])

    def agentic_deep_search(
        self,
        query: str,
        max_iterations: int = 3,
        limit_per_iteration: int = 5,
        max_total_results: int = 8,
    ) -> Tuple[List[dict], Dict[str, any]]:
        """Итеративный поиск с уточнением запроса (Agentic Deep Search).

        Алгоритм:
        1. Выполняет гибридный поиск с оригинальным запросом
        2. Анализирует результаты, извлекает ключевые термины
        3. Генерирует уточнённый запрос
        4. Повторяет поиск с уточнённым запросом
        5. Объединяет все результаты через RRF
        6. Останавливается при достижении max_iterations или достаточном числе результатов

        Args:
            query: Поисковый запрос
            max_iterations: Максимальное число итераций (по умолчанию 3)
            limit_per_iteration: Число результатов на итерацию
            max_total_results: Максимальное итоговое число результатов

        Returns:
            Tuple из (results, metadata) где metadata содержит информацию о поиске
        """
        all_results: List[dict] = []
        seen_keys: set = set()
        search_metadata = {
            "iterations": 0,
            "queries_used": [],
            "terms_extracted": [],
            "total_unique": 0,
            "early_stop": False,
        }

        current_query = query

        for iteration in range(1, max_iterations + 1):
            logger.debug(
                f"🔄 Agentic Deep Search: итерация {iteration}/{max_iterations}, "
                f"запрос: '{current_query[:60]}...'"
            )

            # Выполняем гибридный поиск
            results = self.hybrid_search(
                current_query,
                limit=limit_per_iteration,
                use_rrf=True,
                expand=(iteration == 1),  # Только первая итерация с query expansion
            )

            # Дедупликация
            new_results = []
            for r in results:
                key = f"{r['metadata']['file']}:{r['metadata']['chunk_index']}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    new_results.append(r)

            all_results.extend(new_results)
            search_metadata["iterations"] = iteration
            search_metadata["queries_used"].append(current_query[:80])

            logger.debug(
                f"  Итерация {iteration}: найдено {len(new_results)} новых, "
                f"всего {len(all_results)} уникальных"
            )

            # Проверка условия остановки: достаточно результатов
            if len(all_results) >= max_total_results:
                search_metadata["early_stop"] = True
                search_metadata["early_stop_reason"] = "enough_results"
                break

            # Если это не последняя итерация — уточняем запрос
            if iteration < max_iterations:
                if not results or len(new_results) == 0:
                    # Нет результатов — пробуем query expansion с другими синонимами
                    expanded = expand_query(query, max_expansions=5)
                    if len(expanded) > 1:
                        current_query = expanded[min(iteration, len(expanded) - 1)]
                        search_metadata["queries_used"].append(
                            f"[expansion] {current_query[:80]}"
                        )
                        continue
                    else:
                        # Нечего расширять — стоп
                        search_metadata["early_stop"] = True
                        search_metadata["early_stop_reason"] = "no_new_results"
                        break

                # Извлекаем ключевые термины из новых результатов
                key_terms = self._extract_key_terms(new_results, max_terms=5)
                search_metadata["terms_extracted"].extend(key_terms[:3])

                if not key_terms:
                    # Нет терминов для уточнения — стоп
                    search_metadata["early_stop"] = True
                    search_metadata["early_stop_reason"] = "no_key_terms"
                    break

                # Генерируем уточнённый запрос
                current_query = self._generate_refined_query(
                    query, key_terms, iteration
                )

        # Финальная дедупликация через RRF (объединяем все итерации)
        if not all_results:
            return [], search_metadata

        # Ранжируем по final_score (уже вычислен в hybrid_search)
        all_results.sort(key=lambda r: r.get("final_score", 0.0), reverse=True)

        # Ограничиваем итоговый список
        final_results = all_results[:max_total_results]
        search_metadata["total_unique"] = len(seen_keys)

        return final_results, search_metadata

    def _decompose_query_with_llm(self, query: str) -> List[str]:
        """Декомпозирует сложный запрос на подзапросы через LLM.

        Использует правила декомпозиции (без LLM-вызова) для разбиения
        сложных вопросов на независимые подзапросы.

        Стратегии декомпозиции:
        1. Разделение по союзам: "и", "а", "также", "плюс", "&", ","
        2. Разделение по вопросам: "как", "где", "когда", "что"
        3. Извлечение ключевых существительных и глаголов

        Args:
            query: Сложный запрос

        Returns:
            Список подзапросов (2-4 штуки)
        """
        import re

        # Стратегия 1: разделение по ключевым союзам и знакам
        separators = r'(?:\s+(?:и|а|также|плюс|а также|и также)\s+|\s*[,;]\s+(?:и |а |также |плюс )?)'
        parts = re.split(separators, query, flags=re.IGNORECASE)
        parts = [p.strip() for p in parts if p and len(p.strip()) > 3]

        if len(parts) >= 2:
            return parts[:4]

        # Стратегия 2: анализ структуры запроса
        # "Как работает X и где проверяется Y" -> ["как работает X", "где проверяется Y"]
        question_patterns = [
            (r'как\s+(?:работает|обрабатывается|вызывается|используется)\s+(.+?)(?:\s+(?:и|а|также|где)\s+|$)', 'как работает'),
            (r'где\s+(?:проверяется|находится|вызывается|используется|обрабатывается)\s+(.+?)(?:\s+(?:и|а|также|как)\s+|$)', 'где находится'),
            (r'что\s+(?:делает|происходит|содержит)\s+(.+?)(?:\s+(?:и|а|также|где|как)\s+|$)', 'что делает'),
            (r'когда\s+(?:вызывается|происходит|срабатывает)\s+(.+?)(?:\s+(?:и|а|также|где|как)\s+|$)', 'когда вызывается'),
        ]

        subqueries = []
        remaining = query.lower()

        for pattern, _ in question_patterns:
            match = re.search(pattern, remaining)
            if match:
                subquery = match.group(0).strip()
                if len(subquery) > 5:
                    subqueries.append(subquery)
                    # Удаляем найденную часть из оставшегося
                    remaining = remaining[:match.start()] + remaining[match.end():]
                    remaining = remaining.strip()

        if subqueries:
            # Добавляем оставшуюся часть если есть
            if remaining and len(remaining) > 5:
                subqueries.append(remaining)
            return subqueries[:4]

        # Стратегия 3: извлечение ключевых терминов и построение подзапросов
        # Извлекаем существительные (слово после "как", "где", "что")
        key_terms = re.findall(r'(?:как|где|что|когда|почему)\s+(\w+(?:\s+\w+){0,2})', query.lower())
        if key_terms:
            return [f"{term} {query.split()[0]}" for term in key_terms[:3]]

        # Фоллбэк: возвращаем оригинальный запрос
        return [query]

    def _analyze_subquery_relations(
        self, subqueries: List[str], subquery_results: Dict[str, List[dict]]
    ) -> Dict[str, any]:
        """Анализирует связи между результатами подзапросов.

        Ищет общие файлы, символы и зависимости между результатами
        разных подзапросов для формирования связного ответа.

        Args:
            subqueries: Список подзапросов
            subquery_results: {subquery: [results]}

        Returns:
            Словарь с анализом связей
        """
        analysis = {
            "common_files": [],
            "related_symbols": [],
            "flow_description": "",
            "coverage_score": 0.0,
        }

        # Собираем все файлы из результатов
        all_files: Dict[str, List[str]] = {}  # file -> [subqueries]
        for sq, results in subquery_results.items():
            for r in results:
                fp = r["metadata"]["file"]
                if fp not in all_files:
                    all_files[fp] = []
                all_files[fp].append(sq[:30])

        # Находим файлы, которые появились в результатах нескольких подзапросов
        common = [f for f, sqs in all_files.items() if len(set(sqs)) > 1]
        analysis["common_files"] = common[:10]

        # Вычисляем coverage score
        total_results = sum(len(r) for r in subquery_results.values())
        unique_files = len(all_files)
        if total_results > 0:
            # Чем больше уникальных файлов покрыто, тем выше score
            analysis["coverage_score"] = min(1.0, unique_files / max(len(subqueries), 1))

        # Формируем описание потока
        if len(subqueries) > 1:
            analysis["flow_description"] = (
                f"Запрос разбит на {len(subqueries)} подзапросов. "
                f"Найдено {total_results} результатов в {unique_files} файлах. "
            )
            if common:
                analysis["flow_description"] += (
                    f"{len(common)} файлов пересекаются между подзапросами."
                )

        return analysis

    def agentic_code_search(
        self,
        query: str,
        symbol_index=None,
        max_subqueries: int = 4,
        limit_per_subquery: int = 5,
        max_total_results: int = 10,
    ) -> Tuple[List[dict], Dict[str, any]]:
        """Agentic Code Search с LLM-декомпозицией запроса.

        Алгоритм (на основе arxiv.org/abs/2505.14321):
        1. Декомпозиция запроса на подзапросы (LLM/правила)
        2. Параллельный поиск каждого подзапроса через hybrid_search
        3. Анализ связей между результатами (общие файлы, символы)
        4. Агрегация через RRF + get_context
        5. Формирование итогового ответа с Call Graph

        Args:
            query: Сложный запрос
            symbol_index: SymbolIndex для Call Graph (опционально)
            max_subqueries: Максимальное число подзапросов
            limit_per_subquery: Число результатов на подзапрос
            max_total_results: Максимальное итоговое число результатов

        Returns:
            Tuple из (results, metadata)
        """
        # Шаг 1: Декомпозиция запроса
        subqueries = self._decompose_query_with_llm(query)[:max_subqueries]

        search_metadata = {
            "original_query": query,
            "subqueries": subqueries,
            "subquery_results_count": {},
            "relations": None,
            "total_unique": 0,
        }

        if len(subqueries) <= 1:
            # Простой запрос — используем обычный гибридный поиск
            results = self.hybrid_search(query, limit=max_total_results)
            search_metadata["subquery_results_count"][query] = len(results)
            return results, search_metadata

        # Шаг 2: Параллельный поиск каждого подзапроса
        all_results: List[dict] = []
        seen_keys: set = set()
        subquery_results: Dict[str, List[dict]] = {}

        for sq in subqueries:
            sq_results = self.hybrid_search(
                sq, limit=limit_per_subquery, use_rrf=True, expand=True
            )
            subquery_results[sq] = sq_results
            search_metadata["subquery_results_count"][sq[:40]] = len(sq_results)

            for r in sq_results:
                key = f"{r['metadata']['file']}:{r['metadata']['chunk_index']}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    all_results.append(r)

        # Шаг 3: Анализ связей между результатами
        relations = self._analyze_subquery_relations(subqueries, subquery_results)
        search_metadata["relations"] = relations

        # Шаг 4: Ранжирование через RRF scores
        all_results.sort(key=lambda r: r.get("final_score", 0.0), reverse=True)
        final_results = all_results[:max_total_results]
        search_metadata["total_unique"] = len(seen_keys)

        return final_results, search_metadata

    def deep_search(self, query: str, limit: int = 8) -> str:
        """Agentic Deep Search для MCP-инструмента.

        Итеративный поиск с уточнением запроса на основе найденных результатов.
        Возвращает форматированную строку для MCP.

        Args:
            query: Поисковый запрос
            limit: Максимальное число результатов
        """
        try:
            results, metadata = self.agentic_deep_search(
                query,
                max_iterations=3,
                limit_per_iteration=max(5, limit),
                max_total_results=limit,
            )

            if not results:
                return "🔍 По запросу ничего не найдено (база пуста или эмбеддер недоступен)."

            output_lines = [
                f"🧠 Agentic Deep Search: найдено {len(results)} результатов "
                f"({metadata['iterations']} итераций, {metadata['total_unique']} уникальных)\n"
            ]

            # Показываем использованные запросы для прозрачности
            if len(metadata["queries_used"]) > 1:
                output_lines.append("📝 Использованные запросы:")
                for i, q in enumerate(metadata["queries_used"], 1):
                    output_lines.append(f"   {i}. {q}")
                output_lines.append("")

            for i, res in enumerate(results, 1):
                score = res.get("final_score", 0.0)
                output_lines.append(
                    f"{i}. 📄 {res['metadata']['file']} [Чанк #{res['metadata']['chunk_index']}] "
                    f"(score={score:.4f})\n"
                    f"```\n{res['text']}\n```\n"
                    f"{'-' * 60}\n"
                )

            return "".join(output_lines)
        except Exception as e:
            logger.error(f"Ошибка agentic_deep_search: {e}", exc_info=True)
            return f"❌ Ошибка глубокого поиска: {str(e)}"
