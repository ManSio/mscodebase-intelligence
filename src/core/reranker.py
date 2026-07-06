"""
Мульти-провайдерный реранкер результатов поиска.

Полностью заменяет локальный ONNX-инференс на внешние локальные движки:
  • LM Studio  (OpenAI-совместимый API, порт 1234)
  • Ollama     (нативный API, порт 11434)

Архитектура:
  1. При инициализации выполняется быстрый асинхронный пинг обоих провайдеров.
  2. Приоритет выбора: Ollama (если есть специализированный реранкер) → LM Studio.
  3. Все чанки отправляются одним пакетом (batch) в рамках единого запроса.
  4. Строгий JSON-ответ через response_format + надёжный fallback-парсер.
  5. При недоступности обоих провайдеров — прозрачный fallback к RRF-порядку.

Зависимости: только httpx (async). Никакого onnxruntime / torch / transformers.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

import httpx

from src.core.config import get_config

logger = logging.getLogger(__name__)

# Загружаем конфигурацию при импорте
_config = get_config()

# Эндпоинты провайдеров (из конфигурации)
_LM_STUDIO_MODELS_URL = _config.embedding.lm_studio_models_url
_LM_STUDIO_CHAT_URL = _config.embedding.lm_studio_chat_url
_LM_STUDIO_EMBEDDINGS_URL = _config.embedding.lm_studio_embeddings_url
_OLLAMA_TAGS_URL = _config.embedding.ollama_tags_url
_OLLAMA_CHAT_URL = _config.embedding.ollama_chat_url
_OLLAMA_EMBEDDINGS_URL = _config.embedding.ollama_embeddings_url

# Таймауты (сек) - из конфигурации
_PROVIDER_PING_TIMEOUT = _config.performance.provider_ping_timeout
_INFERENCE_TIMEOUT = _config.performance.reranker_timeout

# Максимальная длина текста чанка для промпта (символы)
_MAX_CHUNK_PREVIEW_LEN = _config.search.max_chunk_preview_len

# Регулярка для извлечения JSON-массива scores из ответа
_SCORES_JSON_RE = re.compile(r'\{\s*"scores"\s*:\s*\[.*?\]\s*\}', re.DOTALL)
# Извлечение отдельных объектов {"index": N, "score": F}
_SCORE_ITEM_RE = re.compile(
    r'\{\s*"index"\s*:\s*(\d+)\s*,\s*"score"\s*:\s*([+-]?\d*\.?\d+(?:[eE][+-]?\d+)?)\s*\}'
)


class MultiProviderReranker:
    """Реранкер на основе внешних LLM-провайдеров (Ollama / LM Studio).

    Автоматически сканирует доступные провайдеры при инициализации
    и выбирает лучший из доступных для выполнения реранкинга.
    """

    def __init__(
        self,
        lm_studio_url: Optional[str] = None,
        ollama_url: Optional[str] = None,
        ping_timeout: float = _PROVIDER_PING_TIMEOUT,
        inference_timeout: float = _INFERENCE_TIMEOUT,
    ):
        """
        Args:
            lm_studio_url: Базовый URL LM Studio (по умолчанию из конфигурации)
            ollama_url: Базовый URL Ollama (по умолчанию из конфигурации)
            ping_timeout: Таймаут проверки доступности провайдера (сек)
            inference_timeout: Таймаут инференса (сек)
        """
        self.lm_studio_url = (
            lm_studio_url or _config.embedding.get_lm_studio_base_url() + "/v1"
        ).rstrip("/")
        self.ollama_url = (
            ollama_url or _config.embedding.get_ollama_base_url()
        ).rstrip("/")
        self.ping_timeout = ping_timeout
        self.inference_timeout = inference_timeout

        # Статус провайдеров (заполняется при initialize())
        self.lm_studio_available: bool = False
        self.ollama_available: bool = False
        self.lm_studio_model_name: Optional[str] = None  # instruct model for LLM-rerank
        self.lm_studio_embedding_model: Optional[str] = (
            None  # embedding model for embed-rerank
        )
        self.ollama_model_name: Optional[str] = None

        # Кэш HTTP-клиента
        self._client: Optional[httpx.AsyncClient] = None

    async def initialize(self) -> None:
        """Асинхронная инициализация: пинг обоих провайдеров."""
        self._client = httpx.AsyncClient(timeout=self.inference_timeout)

        # Параллельный пинг обоих провайдеров
        import asyncio

        results = await asyncio.gather(
            self._ping_lm_studio(),
            self._ping_ollama(),
            return_exceptions=True,
        )

        if isinstance(results[0], Exception):
            logger.debug(f"LM Studio недоступен: {results[0]}")
        elif results[0]:
            self.lm_studio_available = True
            logger.info(
                f"✅ LM Studio доступен: {self.lm_studio_url} (модель: {self.lm_studio_model_name})"
            )

        if isinstance(results[1], Exception):
            logger.debug(f"Ollama недоступна: {results[1]}")
        elif results[1]:
            self.ollama_available = True
            logger.info(
                f"✅ Ollama доступна: {self.ollama_url} (модель: {self.ollama_model_name})"
            )

        if not self.lm_studio_available and not self.ollama_available:
            logger.info(
                "ℹ️ Реранкер отключён. Запустите модель в LM Studio "
                "или выполните 'ollama run bge-reranker-v2-m3' для включения LLM-реранкинга."
            )

    async def close(self) -> None:
        """Закрывает HTTP-клиент."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _ping_lm_studio(self) -> bool:
        """Быстрый пинг LM Studio. Возвращает True если сервер отвечает.

        Выбирает модели:
        - lm_studio_model_name: для LLM-реранкинга (chat/completions).
          Приоритет: instruct > reranker > любая non-embedding
        - lm_studio_embedding_model: для embedding-реранкинга (/v1/embeddings).
          Приоритет: reranker > embedding
        """
        try:
            resp = await httpx.AsyncClient(timeout=self.ping_timeout).get(
                f"{self.lm_studio_url}/models"
            )
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("data", [])
                if models:
                    embed_model = None
                    reranker_model = None
                    instruct_model = None

                    for m in models:
                        mid = m.get("id", "").lower()
                        # Reranker / embedding для /v1/embeddings — приоритет reranker
                        if "rerank" in mid:
                            if reranker_model is None:
                                reranker_model = m.get("id")
                        elif "embed" in mid:
                            if embed_model is None:
                                embed_model = m.get("id")
                        # Instruct для /v1/chat/completions
                        elif "instruct" in mid:
                            if instruct_model is None:
                                instruct_model = m.get("id")

                    # LLM-реранкинг: instruct > любая первая
                    self.lm_studio_model_name = (
                        instruct_model or reranker_model or models[0].get("id")
                    )
                    # Embedding-реранкинг: reranker > embedding > первая
                    self.lm_studio_embedding_model = (
                        reranker_model or embed_model or models[0].get("id")
                    )

                    logger.info(
                        f"LM Studio: LLM-rerank→{self.lm_studio_model_name}, "
                        f"embed-rerank→{self.lm_studio_embedding_model}"
                    )
                return True
            return False
        except Exception as e:
            logger.debug(f"LM Studio ping failed: {e}")
            return False

    async def _ping_ollama(self) -> bool:
        """Быстрый пинг Ollama. Возвращает True если сервер отвечает."""
        try:
            resp = await httpx.AsyncClient(timeout=self.ping_timeout).get(
                f"{self.ollama_url}/api/tags"
            )
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("models", [])
                if models:
                    self.ollama_model_name = models[0].get("name", "").split(":")[0]
                return True
            return False
        except Exception:
            return False

    @property
    def is_available(self) -> bool:
        """True если хотя бы один провайдер доступен."""
        return self.lm_studio_available or self.ollama_available

    def _select_provider(self) -> Optional[str]:
        """Выбирает лучший доступный провайдер.

        Приоритет:
        1. Ollama — если доступна (специализированные реранкеры типа bge-reranker)
        2. LM Studio — как альтернатива (Instruct-модели)

        Returns:
            'ollama', 'lm_studio' или None
        """
        if self.ollama_available:
            return "ollama"
        if self.lm_studio_available:
            return "lm_studio"
        return None

    async def rerank(
        self,
        query: str,
        chunks: List[Dict[str, Any]],
        top_n: int = 5,
    ) -> List[Dict[str, Any]]:
        """Выполняет пакетный реранкинг чанков через внешний провайдер.

        Поддерживает два режима:
        1. **LLM-реранкинг** (chat/completions) — если есть Instruct-модель
        2. **Embedding-реранкинг** (cosine similarity) — fallback для embedding-моделей

        Args:
            query: Исходный поисковый запрос
            chunks: Список чанков (каждый содержит 'text', 'metadata', 'final_score')
            top_n: Максимальное число результатов для возврата

        Returns:
            Отсортированный список чанков (top_n штук).
            При недоступности провайдеров или ошибке — исходные chunks[:top_n].
        """
        # Защита от пустого входа
        if not chunks:
            return chunks

        # Если чанков уже меньше top_n — реранкинг не нужен
        if len(chunks) <= 1:
            return chunks[:top_n]

        # Выбор провайдера
        provider = self._select_provider()
        if provider is None:
            logger.info(
                "ℹ️ Реранкер отключён. Запустите модель в LM Studio "
                "или выполните 'ollama run bge-reranker-v2-m3' для включения LLM-реранкинга."
            )
            return chunks[:top_n]

        try:
            # Пробуем LLM-реранкинг (chat/completions) если есть Instruct-модель
            llm_available = await self._check_llm_available(provider)

            if llm_available:
                # LLM-реранкинг через chat
                truncated_chunks = []
                for i, chunk in enumerate(chunks):
                    text = chunk.get("text", "")
                    truncated = text[:_MAX_CHUNK_PREVIEW_LEN].strip()
                    truncated_chunks.append({"index": i, "text": truncated})

                prompt = self._build_batch_prompt(query, truncated_chunks)

                if provider == "ollama":
                    scores = await self._query_ollama(prompt)
                else:
                    scores = await self._query_lm_studio(prompt)

                if scores:
                    return self._apply_scores(chunks, scores, top_n)

            # Fallback: embedding-реранкинг (cosine similarity)
            # Работает с BGE-M3 и другими embedding-моделями
            scores = await self._embedding_rerank(query, chunks, provider)
            if scores:
                logger.debug(f"Embedding rerank: {len(scores)} scores computed")
                return self._apply_scores(chunks, scores, top_n)

            # Если ничего не сработало — возвращаем исходный порядок
            return chunks[:top_n]

        except httpx.TimeoutException:
            logger.warning("⏱️ Таймаут реранкера. Fallback к RRF-порядку.")
            return chunks[:top_n]
        except httpx.ConnectError as e:
            logger.warning(
                f"🔌 Ошибка подключения к провайдеру реранкинга: {e}. Fallback к RRF-порядку."
            )
            return chunks[:top_n]
        except Exception as e:
            logger.warning(f"⚠️ Ошибка реранкинга: {e}. Fallback к RRF-порядку.")
            return chunks[:top_n]

    async def _check_llm_available(self, provider: str) -> bool:
        """Проверяет есть ли Instruct-модель для LLM-реранкинга.

        LM Studio: проверяет наличие моделей с type != 'embeddings'.
        Ollama: всегда True (может загрузить любую модель).
        """
        if provider == "ollama":
            return True  # Ollama может загрузить любую модель

        # LM Studio: проверяем наличие LLM (не embedding)
        try:
            if not self._client:
                self._client = httpx.AsyncClient(timeout=2)
            resp = await self._client.get(f"{self.lm_studio_url}/models")
            if resp.status_code == 200:
                models = resp.json().get("data", [])
                # Проверяем есть ли модель с capabilities.chat или type != 'embeddings'
                for m in models:
                    # В LM Studio v1 API нет поля type, проверяем по имени
                    model_id = m.get("id", "").lower()
                    if "embed" not in model_id and "rerank" not in model_id:
                        return True
            return False
        except Exception:
            return False

    def _build_batch_prompt(self, query: str, chunks: List[Dict[str, Any]]) -> str:
        """Формирует пакетный промпт для LLM-реранкинга.

        Промпт содержит запрос и список чанков с индексами.
        Требует от модели вернуть JSON со скорами для каждого индекса.
        """
        chunks_text = "\n".join(f"[{c['index']}] {c['text']}" for c in chunks)

        return (
            f"You are a code search relevance scorer.\n"
            f"Query: {query}\n\n"
            f"Rate the relevance of each code chunk to the query.\n"
            f"Return ONLY a JSON object with this exact structure:\n"
            f'{{"scores": [{{"index": 0, "score": 0.95}}, {{"index": 1, "score": 0.12}}]}}\n\n'
            f"Score range: 0.0 (completely irrelevant) to 1.0 (perfect match).\n"
            f"Be strict: most chunks should score below 0.5 unless they directly address the query.\n\n"
            f"Code chunks:\n{chunks_text}"
        )

    async def _query_lm_studio(self, prompt: str) -> List[Dict[str, Any]]:
        """Отправляет запрос к LM Studio с авто-выбором эндпоинта.

        Универсальный: пробует /v1/chat/completions (instruct модели),
        если модель не поддерживает chat — падает на /v1/completions (base модели).
        """
        if not self._client:
            self._client = httpx.AsyncClient(timeout=self.inference_timeout)

        model_name = self.lm_studio_model_name or "local-model"

        # Пробуем chat/completions (instruct модели)
        try:
            payload = {
                "model": model_name,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a precise code relevance scorer. "
                            "Return ONLY valid JSON with the scores array. No explanations. "
                            'Example: {"scores": [0.9, 0.7, 0.5, 0.3, 0.1]}'
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.0,
                "max_tokens": 1024,
            }

            resp = await self._client.post(
                f"{self.lm_studio_url}/chat/completions",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return self._parse_scores_json(content)

            # Если модель не поддерживает chat (400/404) — падаем на completions
            if resp.status_code in (400, 404):
                logger.debug(
                    f"Chat endpoint failed for {model_name} (HTTP {resp.status_code}), "
                    f"fallback to /v1/completions"
                )
            else:
                resp.raise_for_status()

        except Exception as e:
            logger.debug(
                f"Chat endpoint error for {model_name}: {e}, fallback to completions"
            )

        # Fallback: /v1/completions (base модели, реранкеры)
        payload = {
            "model": model_name,
            "prompt": (
                "You are a precise code relevance scorer. "
                "Return ONLY valid JSON with the scores array. No explanations.\n"
                f"{prompt}"
            ),
            "temperature": 0.0,
            "max_tokens": 1024,
        }

        resp = await self._client.post(
            f"{self.lm_studio_url}/completions",
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()

        data = resp.json()
        content = data["choices"][0]["text"]
        return self._parse_scores_json(content)

    async def _query_ollama(self, prompt: str) -> List[Dict[str, Any]]:
        """Отправляет пакетный запрос к Ollama (нативный API)."""
        if not self._client:
            self._client = httpx.AsyncClient(timeout=self.inference_timeout)

        payload = {
            "model": self.ollama_model_name or "bge-reranker-v2-m3",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a precise code relevance scorer. "
                        "Return ONLY valid JSON with the scores array. No explanations."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.0,
                "num_predict": 1024,
            },
        }

        resp = await self._client.post(
            f"{self.ollama_url}/api/chat",
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()

        data = resp.json()
        content = data.get("message", {}).get("content", "")
        return self._parse_scores_json(content)

    async def _embedding_rerank(
        self,
        query: str,
        chunks: List[Dict[str, Any]],
        provider: str,
    ) -> List[Dict[str, Any]]:
        """Реранкинг через embedding API + cosine similarity.

        Используется когда в LM Studio/Ollama нет LLM (Instruct) моделей,
        но есть embedding модели (BGE-M3, Nomic и т.д.).

        Args:
            query: Поисковый запрос
            chunks: Список чанков для реранкинга
            provider: 'lm_studio' или 'ollama'

        Returns:
            Список score'ов [{"index": int, "score": float}, ...]
        """
        if not self._client:
            self._client = httpx.AsyncClient(timeout=self.inference_timeout)

        # Подготавливаем тексты: query + все чанки
        texts = [f"query: {query}"]  # [0] = query
        for chunk in chunks:
            text = chunk.get("text", "")[:_MAX_CHUNK_PREVIEW_LEN].strip()
            texts.append(f"passage: {text}")  # [1..n] = chunks

        # Выбираем URL и модель
        if provider == "lm_studio":
            url = f"{self.lm_studio_url}/embeddings"
            # Используем embedding модель, не instruct!
            model = self.lm_studio_embedding_model or "text-embedding-bge-m3"
        else:
            url = f"{self.ollama_url}/api/embeddings"
            model = self.ollama_model_name or "bge-m3"

        # Отправляем batch запрос
        # Важно: input должен быть массивом строк (не объектом!)
        payload = {
            "model": model,
            "input": texts,  # list[str] — строго массив!
        }

        try:
            resp = await self._client.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
        except Exception as e:
            logger.warning(f"Embedding rerank failed: {e}")
            return []

        # Парсим ответ
        data = resp.json()
        embeddings = data.get("data", [])
        if len(embeddings) < 2:
            return []

        # Извлекаем векторы
        query_vec = embeddings[0].get("embedding", [])
        chunk_vecs = [e.get("embedding", []) for e in embeddings[1:]]

        # Считаем cosine similarity
        scores = []
        for i, vec in enumerate(chunk_vecs):
            score = self._cosine_similarity(query_vec, vec)
            scores.append({"index": i, "score": score})

        return scores

    @staticmethod
    def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
        """Вычисляет cosine similarity между двумя векторами."""
        if not vec_a or not vec_b or len(vec_a) != len(vec_b):
            return 0.0

        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = sum(a * a for a in vec_a) ** 0.5
        norm_b = sum(b * b for b in vec_b) ** 0.5

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot / (norm_a * norm_b)

    def _parse_scores_json(self, raw: str) -> List[Dict[str, Any]]:
        """Парсит JSON со скорами из ответа LLM.

        Поддерживает:
        1. Чистый JSON: {"scores": [{"index": 0, "score": 0.95}, ...]}
        2. JSON в markdown-блоке: ```json\n{...}\n```
        3. JSON с окружающим текстом (поиск через regex)

        Returns:
            Список dict'ов [{"index": int, "score": float}, ...]
        """
        if not raw:
            return []

        # Попытка 1: прямой JSON-парсинг
        try:
            data = json.loads(raw)
            scores = data.get("scores", [])
            if isinstance(scores, list) and scores:
                return self._validate_scores(scores)
        except (json.JSONDecodeError, TypeError):
            pass

        # Попытка 2: извлечение из markdown-блока
        md_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
        if md_match:
            try:
                data = json.loads(md_match.group(1))
                scores = data.get("scores", [])
                if isinstance(scores, list) and scores:
                    return self._validate_scores(scores)
            except (json.JSONDecodeError, TypeError):
                pass

        # Попытка 3: поиск JSON-объекта через regex
        json_match = _SCORES_JSON_RE.search(raw)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                scores = data.get("scores", [])
                if isinstance(scores, list) and scores:
                    return self._validate_scores(scores)
            except (json.JSONDecodeError, TypeError):
                pass

        # Попытка 4: извлечение отдельных объектов score
        items = _SCORE_ITEM_RE.findall(raw)
        if items:
            return [{"index": int(idx), "score": float(score)} for idx, score in items]

        logger.warning(
            f"⚠️ Не удалось извлечь scores из ответа реранкера: {raw[:200]}..."
        )
        return []

    @staticmethod
    def _validate_scores(scores: List[Any]) -> List[Dict[str, Any]]:
        """Валидирует и нормализует список скоров."""
        validated = []
        for item in scores:
            if isinstance(item, dict):
                idx = item.get("index")
                score = item.get("score")
                if isinstance(idx, (int, float)) and isinstance(score, (int, float)):
                    validated.append(
                        {
                            "index": int(idx),
                            "score": max(0.0, min(1.0, float(score))),
                        }
                    )
        return validated

    @staticmethod
    def _apply_scores(
        chunks: List[Dict[str, Any]],
        scores: List[Dict[str, Any]],
        top_n: int,
    ) -> List[Dict[str, Any]]:
        """Применяет скоры реранкера к чанкам и сортирует.

        Args:
            chunks: Исходные чанки
            scores: Список [{"index": int, "score": float}]
            top_n: Максимальное число результатов

        Returns:
            Отсортированный список чанков
        """
        if not scores:
            return chunks[:top_n]

        # Карта индекс → score
        score_map = {s["index"]: s["score"] for s in scores}

        # Обновляем скоры в чанках
        for i, chunk in enumerate(chunks):
            chunk["reranker_score"] = score_map.get(i, 0.0)

        # Сортируем по reranker_score (убывание)
        sorted_chunks = sorted(
            chunks,
            key=lambda c: c.get("reranker_score", 0.0),
            reverse=True,
        )

        return sorted_chunks[:top_n]


# Обратная совместимость: SearchResultReranker остаётся как тонкая обёртка
class SearchResultReranker:
    """Устаревший реранкер (BM25 + dense комбинация).

    Сохранён для обратной совместимости.
    Для нового функционала используйте MultiProviderReranker.
    """

    def __init__(self, bm25_weight: float = 0.3, dense_weight: float = 0.7):
        self.bm25_weight = bm25_weight
        self.dense_weight = dense_weight
        self._is_initialized = False

    def rerank_results(
        self,
        query: str,
        bm25_results: List[Dict[str, Any]],
        dense_results: List[Dict[str, Any]],
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Переранжирует результаты поиска, комбинируя BM25 и векторные скоры."""
        if not bm25_results and not dense_results:
            return []

        results_map = self._create_results_map(bm25_results, dense_results)
        combined_results = self._combine_scores(results_map, query)
        sorted_results = sorted(
            combined_results.items(), key=lambda x: x[1]["final_score"], reverse=True
        )[:limit]

        return [result for _, result in sorted_results]

    def _create_results_map(
        self, bm25_results: List[Dict[str, Any]], dense_results: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        results_map = {}
        for i, result in enumerate(bm25_results):
            key = self._create_result_key(result)
            results_map[key] = {
                "text": result["text"],
                "metadata": result["metadata"],
                "bm25_score": 1.0 - (i / len(bm25_results)) if bm25_results else 0,
                "dense_score": 0.0,
                "source": "bm25",
            }
        for i, result in enumerate(dense_results):
            if "error" in result:
                continue
            key = self._create_result_key(result)
            if key in results_map:
                results_map[key]["dense_score"] = 1.0 - (i / len(dense_results))
            else:
                results_map[key] = {
                    "text": result["text"],
                    "metadata": result["metadata"],
                    "bm25_score": 0.0,
                    "dense_score": 1.0 - (i / len(dense_results)),
                    "source": "dense",
                }
        return results_map

    @staticmethod
    def _create_result_key(result: Dict[str, Any]) -> str:
        file_path = result["metadata"]["file"]
        chunk_index = result["metadata"]["chunk_index"]
        return f"{file_path}:{chunk_index}"

    def _combine_scores(
        self, results_map: Dict[str, Dict[str, Any]], query: str
    ) -> Dict[str, Dict[str, Any]]:
        combined = {}
        for key, result in results_map.items():
            final_score = (
                result["bm25_score"] * self.bm25_weight
                + result["dense_score"] * self.dense_weight
            )
            relevance_factor = self._calculate_relevance_factor(query, result)
            final_score *= relevance_factor
            result["final_score"] = final_score
            result["query_relevance"] = relevance_factor
            combined[key] = result
        return combined

    @staticmethod
    def _calculate_relevance_factor(query: str, result: Dict[str, Any]) -> float:
        query_words = set(query.lower().split())
        result_text = result["text"].lower()
        exact_matches = sum(1 for word in query_words if word in result_text)
        if exact_matches > 0:
            return 1.5
        long_words = [w for w in query_words if len(w) >= 3]
        long_matches = sum(1 for word in long_words if word in result_text)
        if long_matches > 0:
            return 1.2
        return 1.0

    def update_weights(self, bm25_weight: float, dense_weight: float):
        total_weight = bm25_weight + dense_weight
        if total_weight > 0:
            self.bm25_weight = bm25_weight / total_weight
            self.dense_weight = dense_weight / total_weight
        else:
            self.bm25_weight = 0.5
            self.dense_weight = 0.5
        logger.info(
            f"Обновлены веса реранкера: BM25={self.bm25_weight:.2f}, Dense={self.dense_weight:.2f}"
        )

    def get_stats(self) -> Dict[str, Any]:
        return {
            "bm25_weight": self.bm25_weight,
            "dense_weight": self.dense_weight,
            "is_initialized": self._is_initialized,
        }
