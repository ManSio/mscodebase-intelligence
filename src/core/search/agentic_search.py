"""Agentic search mixin — декомпозиция запросов, итеративный поиск, анализ связей.

Extracted from engine.py for separation of concerns.
"""

import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx

from src.config.settings import get_config
from src.utils.i18n import _

from .utils import _expand_query, _extract_key_terms, _extract_symbol_name

logger = logging.getLogger(__name__)


class AgenticSearchMixin:
    """Mixin with agentic search methods: query decomposition, iterative refinement, relation analysis.

    Designed to be mixed into Searcher (which provides hybrid_search,
    hybrid_search_async, _ensure_multi_reranker_async, etc.).
    """

    # ─────────────────────────────────────────────────────────
    # Iterative Deep Search
    # ─────────────────────────────────────────────────────────

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
                    expanded = _expand_query(query, max_expansions=5)
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
                key_terms = _extract_key_terms(new_results, max_terms=5)
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

    # ─────────────────────────────────────────────────────────
    # LLM Query Decomposition
    # ─────────────────────────────────────────────────────────

    def _decompose_query_with_llm(self, query: str) -> List[str]:
        """Декомпозирует сложный запрос на подзапросы через LLM.

        Пытается использовать LM Studio API для семантической декомпозиции.
        При недоступности LLM — fallback на правило-базированные эвристики.

        Стратегии (в порядке приоритета):
        1. Разделение по союзам: "и", "а", "также", "плюс", "&", ","
        2. Разделение по вопросам: "как", "где", "когда", "что"
        3. Извлечение ключевых существительных и глаголов
        4. LLM-декомпозиция через LM Studio API (опциональный fallback)

        Args:
            query: Сложный запрос

        Returns:
            Список подзапросов (2-4 штуки)
        """
        # Пустой или однословный запрос не требует декомпозиции
        if not query or not query.strip():
            return [query]
        if len(query.split()) <= 1:
            return [query]

        # Попытка 1: детерминированная правило-базированная декомпозиция
        # (быстрая, не требует сети и предсказуема в тестах/проде).

        # Стратегия 1: разделение по ключевым союзам и знакам
        separators = r"(?:\s+(?:и|а|также|плюс|а также|и также)\s+|\s*[,;]\s+(?:и |а |также |плюс )?)"
        parts = re.split(separators, query, flags=re.IGNORECASE)
        parts = [p.strip() for p in parts if p and len(p.strip()) > 3]

        if len(parts) >= 2:
            return parts[:4]

        # Стратегия 2: анализ структуры запроса
        question_patterns = [
            (
                r"как\s+(?:работает|обрабатывается|вызывается|используется)\s+(.+?)(?:\s+(?:и|а|также|где)\s+|$)",
                "как работает",
            ),
            (
                r"где\s+(?:проверяется|находится|вызывается|используется|обрабатывается)\s+(.+?)(?:\s+(?:и|а|также|как)\s+|$)",
                "где находится",
            ),
            (
                r"что\s+(?:делает|происходит|содержит)\s+(.+?)(?:\s+(?:и|а|также|где|как)\s+|$)",
                "что делает",
            ),
            (
                r"когда\s+(?:вызывается|происходит|срабатывает)\s+(.+?)(?:\s+(?:и|а|также|где|как)\s+|$)",
                "когда вызывается",
            ),
        ]

        subqueries = []
        remaining = query.lower()

        for pattern, _prefix in question_patterns:
            match = re.search(pattern, remaining)
            if match:
                subquery = match.group(0).strip()
                if len(subquery) > 5:
                    subqueries.append(subquery)
                    # Удаляем найденную часть из оставшегося
                    remaining = remaining[: match.start()] + remaining[match.end() :]
                    remaining = remaining.strip()

        if subqueries:
            # Добавляем оставшуюся часть если есть
            if remaining and len(remaining) > 5:
                subqueries.append(remaining)
            return subqueries[:4]

        # Стратегия 3: извлечение ключевых терминов и построение подзапросов
        key_terms = re.findall(
            r"(?:как|где|что|когда|почему)\s+(\w+(?:\s+\w+){0,2})", query.lower()
        )
        if key_terms:
            return [f"{term} {query.split()[0]}" for term in key_terms[:3]]

        # ЛЛМ-декомпозиция только для достаточно сложных запросов (>= 4 слов или >= 25 символов)
        if len(query.split()) < 4 and len(query) < 25:
            return [query]

        # Фоллбэк: LLM-декомпозиция только если правила ничего не дали
        llm_subqueries = self._try_llm_decompose(query)
        if llm_subqueries and len(llm_subqueries) >= 2:
            logger.debug(f"🧠 LLM декомпозиция: {len(llm_subqueries)} подзапросов")
            return llm_subqueries[:4]

        # Крайний фоллбэк: возвращаем оригинальный запрос
        return [query]

    async def _decompose_query_with_llm_async(self, query: str) -> List[str]:
        """Async-версия: не блокирует event loop при LLM-вызове."""
        return await asyncio.to_thread(self._decompose_query_with_llm, query)

    def _try_llm_decompose(self, query: str) -> Optional[List[str]]:
        """Пытается декомпозировать запрос через LM Studio API.

        Использует локальный LM Studio (конфигурируемый URL) для разбиения
        сложного запроса на семантически независимые подзапросы.

        Args:
            query: Сложный запрос для декомпозиции

        Returns:
            Список подзапросов или None при ошибке
        """
        try:
            # Проверяем доступность LM Studio
            config = get_config()
            lm_url = os.getenv(
                "LM_STUDIO_URL", config.embedding.get_lm_studio_base_url() + "/v1"
            )

            # Быстрая проверка живости (1 секунда)
            httpx.get(lm_url.replace("/v1", ""), timeout=1.0)

            # Запрос на декомпозицию
            system_prompt = (
                "You are a code search query decomposer. Given a complex query about code, "
                "split it into 2-4 independent sub-queries that can be searched separately.\n\n"
                "Rules:\n"
                "- Each sub-query should focus on ONE concept\n"
                "- Sub-queries must be independent (no shared context needed)\n"
                "- Use natural language, keep sub-queries under 15 words each\n"
                "- Return ONLY a JSON array of strings, no explanation\n\n"
                "Example:\n"
                'Input: "How does authentication work and where are permissions checked?"\n'
                'Output: ["authentication flow implementation", "permission checking locations"]\n'
            )

            response = httpx.post(
                f"{lm_url}/chat/completions",
                json={
                    "model": "local-model",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": query},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 200,
                },
                timeout=5.0,
            )

            if response.status_code != 200:
                logger.debug(f"LM Studio вернул статус {response.status_code}")
                return None

            # Парсим ответ
            result = response.json()
            content = (
                result.get("choices", [{}])[0].get("message", {}).get("content", "")
            )

            # Извлекаем JSON массив из ответа
            json_match = re.search(r"\[.*\]", content, re.DOTALL)
            if json_match:
                import json as json_module

                subqueries = json_module.loads(json_match.group())
                # Валидация: каждый подзапрос должен быть строкой 5-100 символов
                valid = [
                    sq.strip()
                    for sq in subqueries
                    if isinstance(sq, str) and 5 <= len(sq.strip()) <= 100
                ]
                if len(valid) >= 2:
                    return valid

            logger.debug(f"Не удалось распарсить ответ LLM: {content[:100]}")
            return None

        except ImportError:
            logger.debug("httpx не установлен, LLM-декомпозиция недоступна")
            return None
        except Exception as e:
            logger.debug(f"LLM-декомпозиция недоступна: {e}")
            return None

    # ─────────────────────────────────────────────────────────
    # Sub-query Relation Analysis
    # ─────────────────────────────────────────────────────────

    def _analyze_subquery_relations(
        self,
        subqueries: List[str],
        subquery_results: Dict[str, List[dict]],
        symbol_index=None,
    ) -> Dict[str, any]:
        """Анализирует связи между результатами подзапросов.

        Ищет общие файлы, символы и зависимости между результатами
        разных подзапросов для формирования связного ответа.

        Если передан symbol_index — использует Call Graph для поиска
        связанных символов (определения, вызовы) в общих файлах.

        Args:
            subqueries: Список подзапросов
            subquery_results: {subquery: [results]}
            symbol_index: SymbolIndex для Call Graph (опционально)

        Returns:
            Словарь с анализом связей
        """
        analysis = {
            "common_files": [],
            "related_symbols": [],
            "call_graph_hints": [],
            "flow_description": "",
            "coverage_score": 0.0,
            "call_graph_depth": 0,
            "call_graph_nodes_count": 0,
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
            analysis["coverage_score"] = min(
                1.0, unique_files / max(len(subqueries), 1)
            )

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

        # Call Graph анализ через build_call_graph
        if symbol_index and hasattr(symbol_index, "build_call_graph"):
            try:
                nodes_count = 0
                max_depth = 0
                for file_path in common[:5]:  # Топ-5 общих файлов
                    # Получаем символы, определённые в этом файле
                    sym_names = symbol_index.get_symbols_in_file(file_path)
                    if not sym_names:
                        continue

                    for sym_name in sym_names[:3]:  # Топ-3 символа на файл
                        call_graph = symbol_index.build_call_graph(sym_name, depth=2)

                        # Собираем информацию об определении
                        if call_graph.get("definition"):
                            for defn in call_graph["definition"]:
                                analysis["related_symbols"].append(
                                    {
                                        "name": call_graph["symbol"],
                                        "file": defn.get("file", file_path),
                                        "line": defn.get("line", 0),
                                        "kind": defn.get("kind", "unknown"),
                                    }
                                )

                        # Собираем информацию о вызовах (callers + callees)
                        callers = call_graph.get("callers", [])
                        callees = call_graph.get("callees", [])
                        impact_files = call_graph.get("impact_files", [])

                        if callers or callees:
                            analysis["call_graph_hints"].append(
                                {
                                    "symbol": call_graph["symbol"],
                                    "callers_count": len(callers),
                                    "callees_count": len(callees),
                                    "impact_files_count": len(impact_files),
                                    "called_from": [
                                        c.get("file", "") for c in callers[:3]
                                    ],
                                    "calls_to": [
                                        c.get("symbol", "") for c in callees[:3]
                                    ],
                                }
                            )

                        # Подсчёт узлов графа
                        graph_nodes = (
                            len(call_graph.get("definition", []))
                            + len(callers)
                            + len(callees)
                        )
                        nodes_count += graph_nodes
                        # Определяем глубину: если есть indirect_caller — depth=2
                        has_indirect = any(
                            c.get("kind") == "indirect_caller" for c in callers
                        )
                        depth = 2 if has_indirect else 1
                        max_depth = max(max_depth, depth)

                analysis["call_graph_depth"] = max_depth
                analysis["call_graph_nodes_count"] = nodes_count
            except Exception as e:
                logger.debug(f"Call Graph анализ недоступен, fallback: {e}")
                # Fallback на упрощённый подход
                try:
                    for file_path in common[:5]:
                        sym_names = symbol_index.get_symbols_in_file(file_path)
                        for sym_name in sym_names[:2]:
                            refs = symbol_index.find_references(sym_name)
                            if refs:
                                analysis["call_graph_hints"].append(
                                    {
                                        "symbol": sym_name,
                                        "reference_count": len(refs),
                                        "referenced_in": [
                                            r.file_path for r in refs[:3]
                                        ],
                                    }
                                )
                except Exception as e2:
                    logger.debug(f"Fallback анализ тоже недоступен: {e2}")

        return analysis

    # ─────────────────────────────────────────────────────────
    # Agentic Code Search (LLM decomposition + parallel search)
    # ─────────────────────────────────────────────────────────

    def agentic_code_search(
        self,
        query: str,
        symbol_index=None,
        max_subqueries: int = 4,
        limit_per_subquery: int = 5,
        max_total_results: int = 10,
    ) -> Tuple[List[dict], Dict[str, any]]:
        """Agentic Code Search с LLM-декомпозицией запроса.

        Синхронная обёртка для обратной совместимости.
        Используйте agentic_code_search_async() для async контекста.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    asyncio.run,
                    self.agentic_code_search_async(
                        query,
                        symbol_index,
                        max_subqueries,
                        limit_per_subquery,
                        max_total_results,
                    ),
                )
                return future.result(timeout=60)
        else:
            return asyncio.run(
                self.agentic_code_search_async(
                    query,
                    symbol_index,
                    max_subqueries,
                    limit_per_subquery,
                    max_total_results,
                )
            )

    async def agentic_code_search_async(
        self,
        query: str,
        symbol_index=None,
        max_subqueries: int = 4,
        limit_per_subquery: int = 5,
        max_total_results: int = 10,
    ) -> Tuple[List[dict], Dict[str, any]]:
        """Асинхронный Agentic Code Search с LLM-декомпозицией запроса.

        Алгоритм (на основе arxiv.org/abs/2505.14321):
        1. Декомпозиция запроса на подзапросы (LLM с fallback на правила)
        2. **Параллельный поиск через asyncio.gather** (без ThreadPoolExecutor)
        3. Анализ связей между результатами (общие файлы, символы)
        4. Агрегация через RRF
        5. Fallback к обычному поиску при плохой декомпозиции

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
        subqueries = (await self._decompose_query_with_llm_async(query))[
            :max_subqueries
        ]

        search_metadata = {
            "original_query": query,
            "subqueries": subqueries,
            "decomposition_method": "llm"
            if len(subqueries) >= 2 and subqueries != [query]
            else "rules",
            "subquery_results_count": {},
            "relations": None,
            "total_unique": 0,
            "fallback_used": False,
        }

        if len(subqueries) <= 1:
            # Простой запрос — используем обычный гибридный поиск
            results = await self.hybrid_search_async(query, limit=max_total_results)
            search_metadata["subquery_results_count"][query] = len(results)
            search_metadata["decomposition_method"] = "none"
            return results, search_metadata

        # Шаг 2: Параллельный поиск через asyncio.gather (без потоков!)
        subquery_results: Dict[str, List[dict]] = {}

        try:
            # Создаём задачи для параллельного выполнения
            tasks = [
                self.hybrid_search_async(
                    sq, limit=limit_per_subquery, use_rrf=True, expand=True
                )
                for sq in subqueries
            ]

            # Запускаем все задачи параллельно
            results_list = await asyncio.gather(*tasks, return_exceptions=True)

            # Обрабатываем результаты
            for sq, sq_results in zip(subqueries, results_list):
                if isinstance(sq_results, Exception):
                    logger.warning(
                        f"Поиск подзапроса '{sq[:30]}' дал ошибку: {sq_results}"
                    )
                    subquery_results[sq] = []
                    search_metadata["subquery_results_count"][sq[:40]] = 0
                else:
                    subquery_results[sq] = sq_results
                    search_metadata["subquery_results_count"][sq[:40]] = len(sq_results)

        except Exception as e:
            # Fallback: последовательный поиск при ошибке
            logger.warning(
                f"asyncio.gather ошибка ({e}), fallback на последовательный поиск"
            )
            for sq in subqueries:
                sq_results = await self.hybrid_search_async(
                    sq, limit=limit_per_subquery, use_rrf=True, expand=True
                )
                subquery_results[sq] = sq_results
                search_metadata["subquery_results_count"][sq[:40]] = len(sq_results)

        # Шаг 2.5: Fallback при плохой декомпозиции
        total_subquery_results = sum(len(r) for r in subquery_results.values())
        if total_subquery_results == 0:
            logger.info("⚠️ Декомпозиция не дала результатов, fallback на обычный поиск")
            search_metadata["fallback_used"] = True
            results = await self.hybrid_search_async(query, limit=max_total_results)
            search_metadata["subquery_results_count"][f"[fallback] {query[:40]}"] = len(
                results
            )
            return results, search_metadata

        # Шаг 3: Дедупликация и сборка результатов
        all_results: List[dict] = []
        seen_keys: set = set()

        for sq in subqueries:
            for r in subquery_results.get(sq, []):
                key = f"{r['metadata']['file']}:{r['metadata']['chunk_index']}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    all_results.append(r)

        # Шаг 4: Анализ связей между результатами (с Call Graph если доступен)
        relations = self._analyze_subquery_relations(
            subqueries, subquery_results, symbol_index=symbol_index
        )
        search_metadata["relations"] = relations

        # Шаг 5: Ранжирование через RRF scores
        all_results.sort(key=lambda r: r.get("final_score", 0.0), reverse=True)
        final_results = all_results[:max_total_results]
        search_metadata["total_unique"] = len(seen_keys)

        # Шаг 6: Мульти-провайдерный реранкинг (опциональный, async)
        try:
            reranker = await self._ensure_multi_reranker_async()
            if reranker is not None and reranker.is_available and final_results:
                final_results = await reranker.rerank(
                    query, final_results, top_n=max_total_results
                )
                search_metadata["reranker_used"] = True
            else:
                search_metadata["reranker_used"] = False
        except Exception as e:
            logger.warning(f"Реранкинг в agentic_code_search_async пропущен: {e}")
            search_metadata["reranker_used"] = False

        return final_results, search_metadata

    # ─────────────────────────────────────────────────────────
    # MCP-facing Deep Search
    # ─────────────────────────────────────────────────────────

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
                return _(
                    "🔍 По запросу ничего не найдено (база пуста или эмбеддер недоступен)."
                )

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
                # Используем text_full если есть (полный код функции), иначе text
                code_text = res.get("text_full") or res["text"]
                output_lines.append(
                    f"{i}. 📄 {res['metadata']['file']} [Чанк #{res['metadata']['chunk_index']}] "
                    f"(score={score:.4f})\n"
                    f"```\n{code_text}\n```\n"
                    f"{'-' * 60}\n"
                )

            return "".join(output_lines)
        except Exception as e:
            logger.error(f"Ошибка agentic_deep_search: {e}", exc_info=True)
            return _("❌ Deep search error: {error}", error=str(e))
