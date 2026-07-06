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

import asyncio
import json
import logging
import re
import time
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

# Для эмбеддинга (Stages 1-2) — короче, быстрее
_EMBED_CHUNK_PREVIEW_LEN = 400

# Таймаут Stage 3 (LLM) — phi-4 на CPU ~7 tok/s, даём время на полную генерацию JSON
# Первый запрос: промпт ~5s + генерация ~6s = ~11s
# Повторный (LCP cache): генерация ~6s
_LLM_STAGE_TIMEOUT = 12.0

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
        self.lm_studio_model_name: Optional[str] = None
        self.lm_studio_embedding_model: Optional[str] = None
        self.lm_studio_reranker_model: Optional[str] = None
        self.ollama_model_name: Optional[str] = None

        # Кэш HTTP-клиента
        self._client: Optional[httpx.AsyncClient] = None
        # ─── Fix 1: фоновый перепинг каждые 30с ───
        self._scanner_task: Optional[asyncio.Task] = None
        self._scanner_interval: float = 30.0
        # ─── Fix 2: семафор на 1 запрос ───
        self._lm_sem = asyncio.Semaphore(1)
        self._ollama_sem = asyncio.Semaphore(1)
        # ─── Fix 4: кэш доступности LLM (сбрасывается перепингом) ───
        # Начинаем с отрицательного checked_at чтоб первый вызов не кэшировал False
        self._llm_available: bool = False
        self._llm_checked_at: float = -999.0
        self._llm_check_ttl: float = 15.0

    async def initialize(self) -> None:
        """Асинхронная инициализация: пинг обоих провайдеров + фоновый сканер."""
        self._client = httpx.AsyncClient(timeout=self.inference_timeout)

        results = await asyncio.gather(
            self._ping_lm_studio(),
            self._ping_ollama(),
            return_exceptions=True,
        )

        if isinstance(results[0], Exception):
            logger.debug(f"LM Studio недоступен: {results[0]}")
        elif results[0]:
            self.lm_studio_available = True

        if isinstance(results[1], Exception):
            logger.debug(f"Ollama недоступна: {results[1]}")
        elif results[1]:
            self.ollama_available = True

        if not self.lm_studio_available and not self.ollama_available:
            logger.info("ℹ️ Реранкер отключён. Запустите модель в LM Studio или Ollama.")
            return

        # Fix 1: фоновый перепинг каждые 30с
        self._scanner_task = asyncio.create_task(self._scanner_loop())

    async def _scanner_loop(self):
        """Фоновый перепинг провайдеров (подхватывает изменения в LM Studio)."""
        while True:
            await asyncio.sleep(self._scanner_interval)
            try:
                old_lm = self.lm_studio_available
                old_llm = self.lm_studio_model_name
                old_embed = self.lm_studio_embedding_model
                old_rerank = self.lm_studio_reranker_model

                lm_ok = await self._ping_lm_studio()
                if lm_ok:
                    self.lm_studio_available = True
                elif old_lm:
                    self.lm_studio_available = False
                    logger.warning("LM Studio стал недоступен — реранкинг отключён")

                # Сброс кэша LLM при смене любой модели
                if (
                    self.lm_studio_model_name != old_llm
                    or self.lm_studio_embedding_model != old_embed
                    or self.lm_studio_reranker_model != old_rerank
                ):
                    self._llm_available = False
                    self._llm_checked_at = 0.0
                    logger.info(
                        f"LM Studio модели изменились: "
                        f"emb→{self.lm_studio_embedding_model or '—'}, "
                        f"reranker→{self.lm_studio_reranker_model or '—'}, "
                        f"llm→{self.lm_studio_model_name or '—'}"
                    )
            except Exception as e:
                logger.debug(f"Scanner error: {e}")

    async def close(self) -> None:
        """Закрывает HTTP-клиент и останавливает фоновый сканер."""
        if self._scanner_task:
            self._scanner_task.cancel()
            try:
                await self._scanner_task
            except asyncio.CancelledError:
                pass
            self._scanner_task = None
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _ping_lm_studio(self) -> bool:
        """Пинг LM Studio. Детектит три типа моделей: embedding, reranker, LLM.

        1. Пробует расширенное API /api/v0/models (с type/state)
        2. Если неудача — OpenAI-compatible /v1/models (name-based)
        """
        v0_ok = False
        try:
            async with httpx.AsyncClient(timeout=self.ping_timeout) as client:
                resp = await client.get(
                    f"{self.lm_studio_url.replace('/v1', '')}/api/v0/models"
                )
                if resp.status_code == 200:
                    data = resp.json()
                    models = data.get("data", [])
                    if models and any("type" in m for m in models):
                        loaded_embed = []
                        loaded_rerank = []
                        for m in models:
                            if m.get("state") != "loaded":
                                continue
                            t = m.get("type", "")
                            mid = m.get("id", "").lower()
                            if t == "embeddings":
                                if "reranker" in mid:
                                    loaded_rerank.append(m["id"])
                                else:
                                    loaded_embed.append(m["id"])
                            elif t == "llm":
                                if not self.lm_studio_model_name:
                                    self.lm_studio_model_name = m["id"]

                        if loaded_embed and not self.lm_studio_embedding_model:
                            self.lm_studio_embedding_model = loaded_embed[0]
                        if loaded_rerank and not self.lm_studio_reranker_model:
                            self.lm_studio_reranker_model = loaded_rerank[0]

                        if self.lm_studio_model_name:
                            self._llm_available = True
                            self._llm_checked_at = time.time()

                        v0_ok = True
        except Exception as e:
            logger.debug(f"LM Studio /api/v0/models ping failed: {e}")

        if v0_ok:
            logger.info(
                f"LM Studio (v0): emb→{self.lm_studio_embedding_model or '—'}, "
                f"reranker→{self.lm_studio_reranker_model or '—'}, "
                f"llm→{self.lm_studio_model_name or '—'}"
            )
            return True

        # Fallback: OpenAI-compatible /v1/models (без type/state)
        try:
            async with httpx.AsyncClient(timeout=self.ping_timeout) as client:
                resp = await client.get(f"{self.lm_studio_url}/models")
                if resp.status_code != 200:
                    return False

                data = resp.json()
                models = data.get("data", [])
                if not models:
                    return False

                # Name-based детекция
                reranker_candidates = []
                embed_candidates = []
                llm_candidates = []

                for m in models:
                    mid = m.get("id", "").lower()
                    if "reranker" in mid:
                        reranker_candidates.append(m["id"])
                    elif "embed" in mid:
                        embed_candidates.append(m["id"])
                    elif "instruct" in mid or "llm" in mid:
                        llm_candidates.append(m["id"])

                if reranker_candidates and not self.lm_studio_reranker_model:
                    self.lm_studio_reranker_model = reranker_candidates[0]
                if embed_candidates and not self.lm_studio_embedding_model:
                    self.lm_studio_embedding_model = embed_candidates[0]
                if llm_candidates and not self.lm_studio_model_name:
                    self.lm_studio_model_name = llm_candidates[0]

                if self.lm_studio_model_name:
                    self._llm_available = True
                    self._llm_checked_at = time.time()

                # Ultimate fallback: first = embed, last = llm
                if not self.lm_studio_embedding_model:
                    self.lm_studio_embedding_model = models[0]["id"]
                if not self.lm_studio_model_name:
                    if len(models) > 1:
                        self.lm_studio_model_name = models[-1]["id"]
                    else:
                        self.lm_studio_model_name = models[0]["id"]

                logger.info(
                    f"LM Studio (v1): emb→{self.lm_studio_embedding_model}, "
                    f"reranker→{self.lm_studio_reranker_model or '—'}, "
                    f"llm→{self.lm_studio_model_name}"
                )
                return True

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

    @property
    def model_info(self) -> str:
        """Модели используемые для реранкинга (для телеметрии)."""
        parts = []
        if self.lm_studio_embedding_model:
            parts.append(f"emb={self.lm_studio_embedding_model}")
        if self.lm_studio_reranker_model:
            parts.append(f"rerank={self.lm_studio_reranker_model}")
        if self.lm_studio_model_name:
            parts.append(f"llm={self.lm_studio_model_name}")
        if self.ollama_model_name:
            parts.append(f"oll={self.ollama_model_name}")
        return " ".join(parts) if parts else "no-reranker"

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
        """Трёхстадийный реранкинг: embedding → cross-encoder → LLM.

        Стадии:
          1. Bi-encoder (text-embedding-bge-m3) — cosine similarity, быстрое прореживание
          2. Cross-encoder (bge-reranker-v2-m3-m3) — pairwise реранкинг
          3. LLM (phi-4-mini-instruct) — semantic scoring через chat completions

        Каждая стадия опциональна: если модель недоступна — пропускается.
        Timing доступен после вызова: self.last_timing
        """
        import time as _time

        t_start = _time.perf_counter()
        self.last_timing = {
            "stage1_ms": 0,
            "stage2_ms": 0,
            "stage3_ms": 0,
            "total_ms": 0,
            "stage1": "-",
            "stage2": "-",
            "stage3": "-",
        }

        if not chunks:
            return chunks

        provider = self._select_provider()
        if provider is None:
            self.last_timing["total_ms"] = (_time.perf_counter() - t_start) * 1000
            return chunks

        sem = self._lm_sem if provider == "lm_studio" else self._ollama_sem

        # ═══════════════════════════════════════════════
        # Стадия 1: Bi-encoder embedding rerank
        # ═══════════════════════════════════════════════
        if self.lm_studio_embedding_model:
            stage1_top = min(top_n * 3, len(chunks))
            t1 = _time.perf_counter()
            try:
                async with sem:
                    embed_scores = await self._embedding_rerank(
                        query,
                        chunks,
                        provider,
                        model_override=self.lm_studio_embedding_model,
                    )
                if embed_scores:
                    chunks = self._apply_scores(chunks, embed_scores, stage1_top)
                    self.last_timing["stage1_ms"] = (_time.perf_counter() - t1) * 1000
                    self.last_timing["stage1"] = self.lm_studio_embedding_model
            except Exception as e:
                self.last_timing["stage1_ms"] = (_time.perf_counter() - t1) * 1000
                self.last_timing["stage1"] = f"failed: {e}"

        if not chunks:
            return chunks

        # ═══════════════════════════════════════════════
        # Стадия 2: Cross-encoder rerank (bge-reranker)
        # ═══════════════════════════════════════════════
        if self.lm_studio_reranker_model:
            stage2_top = min(top_n * 2, len(chunks))
            t2 = _time.perf_counter()
            try:
                async with sem:
                    reranker_scores = await self._cross_encoder_rerank(
                        query,
                        chunks,
                        provider,
                        model_override=self.lm_studio_reranker_model,
                    )
                if reranker_scores:
                    chunks = self._apply_scores(chunks, reranker_scores, stage2_top)
                    self.last_timing["stage2_ms"] = (_time.perf_counter() - t2) * 1000
                    self.last_timing["stage2"] = self.lm_studio_reranker_model
            except Exception as e:
                self.last_timing["stage2_ms"] = (_time.perf_counter() - t2) * 1000
                self.last_timing["stage2"] = f"failed: {e}"

        if not chunks:
            return chunks

        # ═══════════════════════════════════════════════
        # Стадия 3: LLM-реранкинг (phi-4-mini-instruct)
        # ═══════════════════════════════════════════════
        if self.lm_studio_model_name and await self._check_llm_available(provider):
            t3 = _time.perf_counter()
            try:
                truncated = [
                    {
                        "index": i,
                        "text": c.get("text", "")[:_MAX_CHUNK_PREVIEW_LEN].strip(),
                    }
                    for i, c in enumerate(chunks)
                ]
                prompt = self._build_batch_prompt(query, truncated)

                async with sem:
                    coro = (
                        self._query_ollama(prompt)
                        if provider == "ollama"
                        else self._query_lm_studio(prompt)
                    )
                    scores = await asyncio.wait_for(coro, timeout=_LLM_STAGE_TIMEOUT)
                if scores:
                    chunks = self._apply_scores(chunks, scores, top_n)
                    self.last_timing["stage3_ms"] = (_time.perf_counter() - t3) * 1000
                    self.last_timing["stage3"] = self.lm_studio_model_name
            except asyncio.TimeoutError:
                self.last_timing["stage3_ms"] = (_time.perf_counter() - t3) * 1000
                self.last_timing["stage3"] = "timeout"
            except Exception as e:
                self.last_timing["stage3_ms"] = (_time.perf_counter() - t3) * 1000
                self.last_timing["stage3"] = f"failed: {e}"

        self.last_timing["total_ms"] = (_time.perf_counter() - t_start) * 1000
        return chunks[:top_n]

    async def _check_llm_available(self, provider: str) -> bool:
        """Проверяет доступность LLM-модели с кэшем.

        Для LM Studio: просто проверяет что `lm_studio_model_name` установлен
        (детектится при `_ping_lm_studio` и обновляется сканером раз в 30с).
        """
        now = time.time()
        if now - self._llm_checked_at < self._llm_check_ttl:
            return self._llm_available

        self._llm_checked_at = now

        if provider == "ollama":
            self._llm_available = bool(self.ollama_model_name)
            return self._llm_available

        # Для LM Studio полагаемся на _ping_lm_studio (выполняется при initialize
        # и в _scanner_loop раз в 30с). Если имя модели установлено — LLM доступна.
        self._llm_available = bool(self.lm_studio_model_name)
        return self._llm_available

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
                "max_tokens": 256,
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
            "max_tokens": 256,
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

    async def _cross_encoder_rerank(
        self,
        query: str,
        chunks: List[Dict[str, Any]],
        provider: str,
        model_override: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Cross-encoder реранкинг через embedding API + cosine similarity.

        Stage 2: использует bge-reranker-v2-m3-m3.
        В LM Studio реранкер работает через /v1/embeddings — отправляем
        query+passages отдельными строками, получаем эмбеддинги и считаем
        cosine similarity. Cross-encoder с cross-attention даёт лучшее
        качество эмбеддингов, чем bi-encoder.

        Args:
            query: Поисковый запрос
            chunks: Список чанков для реранкинга
            provider: 'lm_studio' или 'ollama'
            model_override: Конкретная модель (bge-reranker-v2-m3-m3)

        Returns:
            Список score'ов [{"index": int, "score": float}, ...]
        """
        if not self._client:
            self._client = httpx.AsyncClient(timeout=self.inference_timeout)

        if provider == "lm_studio":
            url = f"{self.lm_studio_url}/embeddings"
            model = model_override or self.lm_studio_reranker_model
        else:
            url = f"{self.ollama_url}/api/embeddings"
            model = model_override or self.ollama_model_name

        if not model:
            logger.debug("Cross-encoder: нет модели для реранкинга")
            return []

        # Энкодим query и passage отдельно (короткие для скорости)
        texts = [f"query: {query}"]
        for chunk in chunks:
            text = chunk.get("text", "")[:_EMBED_CHUNK_PREVIEW_LEN].strip()
            texts.append(f"passage: {text}")

        payload = {
            "model": model,
            "input": texts,
        }

        try:
            resp = await self._client.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
        except Exception as e:
            logger.warning(f"Cross-encoder rerank ({model}) failed: {e}")
            return []

        data = resp.json()
        embeddings = data.get("data", [])
        if len(embeddings) < 2:
            return []

        query_vec = embeddings[0].get("embedding", [])
        chunk_vecs = [e.get("embedding", []) for e in embeddings[1:]]

        scores = []
        for i, vec in enumerate(chunk_vecs):
            score = self._cosine_similarity(query_vec, vec)
            scores.append({"index": i, "score": score})

        return scores

    async def _embedding_rerank(
        self,
        query: str,
        chunks: List[Dict[str, Any]],
        provider: str,
        model_override: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Bi-encoder реранкинг через embedding API + cosine similarity.

        Stage 1: использует text-embedding-bge-m3 для быстрого прореживания.

        Args:
            query: Поисковый запрос
            chunks: Список чанков для реранкинга
            provider: 'lm_studio' или 'ollama'
            model_override: Конкретная модель (если не указана — авто-выбор)

        Returns:
            Список score'ов [{"index": int, "score": float}, ...]
        """
        if not self._client:
            self._client = httpx.AsyncClient(timeout=self.inference_timeout)

        # Подготавливаем тексты: query + все чанки (короткие для скорости)
        texts = [f"query: {query}"]
        for chunk in chunks:
            text = chunk.get("text", "")[:_EMBED_CHUNK_PREVIEW_LEN].strip()
            texts.append(f"passage: {text}")

        if provider == "lm_studio":
            url = f"{self.lm_studio_url}/embeddings"
            model = (
                model_override
                or self.lm_studio_embedding_model
                or "text-embedding-bge-m3"
            )
        else:
            url = f"{self.ollama_url}/api/embeddings"
            model = model_override or self.ollama_model_name or "bge-m3"

        # Отправляем batch запрос
        payload = {
            "model": model,
            "input": texts,
        }

        try:
            resp = await self._client.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
        except Exception as e:
            logger.warning(f"Embedding rerank ({model}) failed: {e}")
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
