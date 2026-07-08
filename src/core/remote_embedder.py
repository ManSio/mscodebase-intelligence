"""
MSCodeBase Intelligence - Универсальный адаптивный Эмбеддер (RemoteEmbedder)
Размещается в src/core/remote_embedder.py
"""

import asyncio
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from src.core.config import get_config

logger = logging.getLogger("mscodebase.embedder")
logger = logging.getLogger("mscodebase_server.embedder")

# Интервал проверки доступности внешних API (секунды)
_PROVIDER_SCAN_INTERVAL = int(os.getenv("PROVIDER_SCAN_INTERVAL", "30"))


class RemoteEmbedder:
    def __init__(
        self,
        port: Optional[int] = None,
        host: Optional[str] = None,
        timeout: Optional[float] = None,
        breaker: Optional[Any] = None,
    ):
        """Универсальный клиент эмбеддингов с каскадным переключением (LM Studio -> ONNX -> Fallback).

        Автоматически сканирует доступность LM Studio / Ollama в фоновом потоке.
        Если внешний сервер появился — переключается на него без перезапуска Zed.

        Args:
            port: Порт LM Studio (по умолчанию из конфигурации)
            host: Хост LM Studio (по умолчанию из конфигурации)
            timeout: Таймаут запросов (по умолчанию из конфигурации)
            breaker: CircuitBreaker для защиты от каскадных сбоев LM Studio
        """
        config = get_config()

        # Используем конфигурацию по умолчанию, если не передано
        self.host = host or config.embedding.lm_studio_host
        self.port = port or config.embedding.lm_studio_port
        self.timeout = timeout or config.performance.embedding_timeout
        self.lm_studio_url = f"http://{self.host}:{self.port}/v1/embeddings"
        self.model_name = config.embedding.model_name

        # CircuitBreaker для LM Studio (предотвращает каскадные сбои)
        self._breaker = breaker
        self._breaker_fallback = {
            "status": "fallback",
            "message": "LM Studio breaker open",
        }
        # Размерность эмбеддинга (берётся из модели при инициализации)
        self.embedding_dim = config.embedding.embedding_dimension

        # Переменные для локального ONNX (ленивая инициализация, чтобы не жрать ОЗУ зря)
        self._onnx_session = None
        self._tokenizer = None
        self.ext_root = Path(__file__).resolve().parent.parent.parent
        # ONNX model: auto-detect directory from .codebase_models/onnx/
        # First available: bge-m3 (1024), bge-base (768), bge-small (384), etc.
        # ONNX model search paths (in priority order)
        self._onnx_search_paths = [
            self.ext_root / ".codebase_models" / "onnx",
            Path.home()
            / ".cache"
            / "mscodebase"
            / "models"
            / ".codebase_models"
            / "onnx",
        ]
        self.local_model_dir = self._onnx_search_paths[0]
        self._detect_model_dir()

    def _detect_model_dir(self):
        """Find the first available ONNX model in .codebase_models/onnx/*/model.onnx
        Checks multiple locations: ext_root, project_root, shared cache."""
        for base in self._onnx_search_paths:
            if not base.exists():
                continue
            for subdir in sorted(base.iterdir()):
                # Skip reranker subdirectories for embedder
                if subdir.name.startswith("reranker-") or subdir.name.startswith(
                    "rreranker"
                ):
                    continue
                model_file = subdir / "model.onnx"
                if model_file.exists():
                    self.local_model_dir = subdir
                    logger.debug(f"ONNX model detected: {subdir.name} in {base}")
                    # Read dimension from model
                    try:
                        import onnxruntime as ort

                        sess = ort.InferenceSession(
                            str(model_file), providers=["CPUExecutionProvider"]
                        )
                        dim = sess.get_outputs()[0].shape[-1]
                        self._model_name = subdir.name
                        logger.info(
                            f"ONNX model: {subdir.name} ({dim}dim, {model_file.stat().st_size / 1024 / 1024:.0f}MB)"
                        )
                    except:
                        pass
                    return  # use first valid model

        # Блокировка для потокобезопасного переключения режима
        self._mode_lock = threading.Lock()

        # КРИТИЧНО (INC-6BCB): НЕ БЛОКИРОВАТЬ __init__ HTTP-запросами.
        # На старте MCP-сервера блокирующий httpx.get может занять 2-5
        # секунд и привести к таймауту создания сервера в Zed.
        # Решение: mode = "unknown", фоновый сканер определит режим асинхронно.
        self.mode = "unknown"
        self._preferred_mode = "lm_studio"  # режим, к которому стремимся вернуться
        _lm_available = None  # async, см. _init_provider_async

        # Async HTTP client с connection pool (LM Studio)
        self._async_client: Optional[httpx.AsyncClient] = None
        self._async_client_lock = threading.Lock()

        # Sync HTTP client для фонового сканера (переиспользуется, без утечек)
        self._sync_client: Optional[httpx.Client] = None

        # Старт фонового инициализатора (НЕ блокирует __init__).
        self._init_thread = threading.Thread(
            target=self._init_provider_async,
            name="RemoteEmbedder-init",
            daemon=True,
        )
        self._init_thread.start()

        # Запуск фонового сканера доступности провайдера (LM Studio/Ollama).
        # Сканер работает ВСЕГДА: он либо подтверждает LM Studio
        # (если _init_provider_async его нашёл), либо ищет его, если
        # текущий режим != "lm_studio".
        self._scanner_stop = threading.Event()
        self._scanner_thread = threading.Thread(
            target=self._provider_scanner_loop,
            name="mscodebase-provider-scanner",
            daemon=True,
        )
        self._scanner_thread.start()

    def _check_lm_studio(self) -> bool:
        """Быстрая проверка доступности порта LM Studio (переиспользует клиент).

        Если подключен CircuitBreaker — проверка проходит через breaker.call()
        для защиты от каскадных сбоев при зависании LM Studio.
        """
        if self._breaker is not None:
            try:
                return bool(
                    self._breaker.call(self._check_lm_studio_raw, fallback=True)
                )
            except Exception:
                return False
        return self._check_lm_studio_raw()

    def _check_lm_studio_raw(self) -> bool:
        """Прямая проверка LM Studio без CircuitBreaker (используется breaker.call внутри)."""
        if self._sync_client is None:
            self._sync_client = httpx.Client(timeout=2.0)
        try:
            r = self._sync_client.get(f"http://{self.host}:{self.port}/v1/models")
            if r.status_code == 200:
                models = r.json().get("data", [])
                if models:
                    self._model_name = models[0].get(
                        "id", models[0].get("model", str(models[0]))
                    )
                    return True
            return False
        except Exception:
            return False

    def get_model_info(self) -> dict:
        """Возвращает информацию о текущей модели эмбеддера."""
        return {
            "provider": self.mode,
            "model": getattr(self, "_model_name", self.model_name),
            "configured_model": self.model_name,
        }

    def _init_provider_async(self):
        """Фоновая инициализация режима провайдера (НЕ блокирует __init__).

        Выполняет _check_lm_studio / _check_ollama в отдельном потоке.
        Если ни один не доступен — переходит в ONNX.

        (См. INC-6BCB: __init__ должен возвращать мгновенно, иначе
        create_mcp_server() зависает на старте, и Zed убивает процесс
        по таймауту.)
        """
        try:
            _lm_available = self._check_lm_studio()
            if _lm_available:
                with self._mode_lock:
                    self.mode = "lm_studio"
                    self._preferred_mode = "lm_studio"
                logger.info(
                    "✅ LM Studio доступен при старте. Фоновый сканер не запускается."
                )
                return
            if os.getenv("EMBEDDING_PROVIDER") == "ollama":
                if self._check_ollama():
                    with self._mode_lock:
                        self.mode = "ollama"
                        self._preferred_mode = "ollama"
                    logger.info(
                        "⚠️ LM Studio не отвечает. Переключаемся в режим OLLAMA."
                    )
                    return
            with self._mode_lock:
                self.mode = "onnx"
                self._preferred_mode = "lm_studio"
            logger.info(
                "⚠️ Внешние API не обнаружены. Будет задействован ЛОКАЛЬНЫЙ движок ONNX Runtime."
            )
        except Exception as e:
            logger.debug(f"_init_provider_async: {e}")
            with self._mode_lock:
                self.mode = "onnx"  # safe default

    def _check_ollama(self) -> bool:
        """Проверка доступности Ollama (переиспользует sync клиент)."""
        if self._sync_client is None:
            self._sync_client = httpx.Client(timeout=2.0)
        config = get_config()
        try:
            r = self._sync_client.get(config.embedding.ollama_tags_url)
            return r.status_code == 200
        except Exception:
            return False

    def _provider_scanner_loop(self):
        """Фоновый поток: периодически проверяет, появился ли внешний провайдер.

        Если LM Studio / Ollama запустились после старта Zed — автоматически
        переключается с ONNX на внешний API и завершает цикл (break).
        Повторный опрос после успешного подключения не производится.
        """
        while not self._scanner_stop.wait(_PROVIDER_SCAN_INTERVAL):
            try:
                # Если уже на LM Studio — проверяем что он ещё жив
                with self._mode_lock:
                    current = self.mode

                if current == "lm_studio":
                    if not self._check_lm_studio():
                        with self._mode_lock:
                            self.mode = "onnx"
                            self._preferred_mode = "lm_studio"
                        logger.warning(
                            "📡 LM Studio пропал. Переключаюсь на ONNX. "
                            "Сканер продолжит поиск."
                        )
                        continue
                    # LM Studio ещё жив — выходим из цикла, дальше проверять нечего
                    logger.debug("LM Studio стабилен. Сканер завершает работу.")
                    break

                if current == "ollama":
                    if not self._check_ollama():
                        with self._mode_lock:
                            self.mode = "onnx"
                            self._preferred_mode = "ollama"
                        logger.warning(
                            "📡 Ollama пропал. Переключаюсь на ONNX. "
                            "Сканер продолжит поиск."
                        )
                        continue
                    # Ollama ещё жив — выходим из цикла
                    logger.debug("Ollama стабилен. Сканер завершает работу.")
                    break

                # current == "onnx" или "fallback" — ищем внешний провайдер
                if self._check_lm_studio():
                    with self._mode_lock:
                        self.mode = "lm_studio"
                        self._preferred_mode = "lm_studio"
                    logger.info(
                        "🌐 LM Studio обнаружен! Переключаюсь с ONNX → LM Studio. "
                        "Сканер остановлен."
                    )
                    return  # Успешное подключение — завершаем поток
                elif self._check_ollama():
                    with self._mode_lock:
                        self.mode = "ollama"
                        self._preferred_mode = "ollama"
                    logger.info(
                        "🌐 Ollama обнаружен! Переключаюсь с ONNX → Ollama. "
                        "Сканер остановлен."
                    )
                    return  # Успешное подключение — завершаем поток

            except Exception as e:
                logger.debug(f"Сканер провайдера: ошибка проверки: {e}")

    def stop_scanner(self):
        """Останавливает фоновый сканер (вызывается при shutdown)."""
        self._scanner_stop.set()
        if self._scanner_thread is not None:
            self._scanner_thread.join(timeout=5.0)
            self._scanner_thread = None

    def _init_onnx(self):
        """Отложенная сборка тяжелого локального ONNX контекста только при реальной необходимости."""
        if self._onnx_session is not None:
            return
        try:
            import onnxruntime as ort
            from transformers import AutoTokenizer

            logger.info(
                f"⚙️ Инициализация локального ONNX ядра из папки: {self.local_model_dir}"
            )
            if not self.local_model_dir.exists():
                raise FileNotFoundError(
                    f"Локальные веса ONNX не найдены в {self.local_model_dir}. Запустите download_model.py"
                )

            self._tokenizer = AutoTokenizer.from_pretrained(str(self.local_model_dir))

            providers = ["CPUExecutionProvider"]
            if "DmlExecutionProvider" in ort.get_available_providers():
                providers.insert(0, "DmlExecutionProvider")

            self._onnx_session = ort.InferenceSession(
                str(self.local_model_dir / "model.onnx"),
                providers=providers,
            )
            logger.info("✅ Локальный ONNX движок успешно запущен и готов к расчетам.")
        except Exception as e:
            logger.error(f"❌ Ошибка сборки локального ONNX-детектора: {e}")
            self.mode = "fallback"

    def embed_batch(
        self, texts: List[str], is_query: bool = False
    ) -> List[List[float]]:
        """Пакетное получение векторов через активный провайдер."""
        if not texts:
            return []

        with self._mode_lock:
            current_mode = self.mode

        # Режим 1: LM Studio (Высокий приоритет)
        if current_mode == "lm_studio":
            try:
                payload = {"model": self.model_name, "input": texts}
                with httpx.Client(timeout=self.timeout) as client:
                    r = client.post(self.lm_studio_url, json=payload)
                    if r.status_code == 200:
                        data = r.json().get("data", [])
                        if not data:
                            logger.warning(
                                f"LM Studio вернул пустой список embeddings. "
                                f"Проверьте что модель '{self.model_name}' поддерживает embeddings. "
                                f"Падаем в ONNX."
                            )
                            with self._mode_lock:
                                self.mode = "onnx"
                                self._preferred_mode = "lm_studio"
                        else:
                            data = sorted(data, key=lambda x: x.get("index", 0))
                            return [item["embedding"] for item in data]
                    else:
                        logger.warning(
                            f"LM Studio отклонил запрос (HTTP {r.status_code}). Падаем в ONNX."
                        )
                        with self._mode_lock:
                            self.mode = "onnx"
                            self._preferred_mode = "lm_studio"
            except Exception as e:
                logger.warning(
                    f"Сбой связи с LM Studio: {e}. Переходим на локальный ONNX."
                )
                with self._mode_lock:
                    self.mode = "onnx"
                    self._preferred_mode = "lm_studio"

        # Режим 2: Локальный ONNX Runtime (Автономный режим без интернета)
        with self._mode_lock:
            current_mode = self.mode

        if current_mode == "onnx":
            self._init_onnx()
            if self._onnx_session:
                try:
                    import numpy as np

                    encoded = self._tokenizer(
                        texts,
                        padding=True,
                        truncation=True,
                        max_length=512,
                        return_tensors="np",
                    )
                    inputs = {
                        "input_ids": encoded["input_ids"].astype(np.int64),
                        "attention_mask": encoded["attention_mask"].astype(np.int64),
                    }
                    if "token_type_ids" in encoded:
                        inputs["token_type_ids"] = encoded["token_type_ids"].astype(
                            np.int64
                        )

                    outputs = self._onnx_session.run(None, inputs)
                    token_embeddings = outputs[0]
                    if len(token_embeddings) == 1 or token_embeddings.shape[0] == len(
                        texts
                    ):
                        pass  # single or batch works
                    else:
                        raise ValueError(
                            f"Expected {len(texts)} embeddings, got {token_embeddings.shape[0]}"
                        )
                except Exception as batch_err:
                    # Batch processing may fail for some ONNX exports (MatMul shape mismatch)
                    # Fallback: embed one by one (slower but reliable)
                    logger.debug(
                        f"ONNX batch failed ({batch_err}), falling back to single embeds"
                    )
                    embeddings = []
                    import numpy as np

                    for text in texts:
                        encoded = self._tokenizer(
                            [text],
                            padding=True,
                            truncation=True,
                            max_length=512,
                            return_tensors="np",
                        )
                        inp = {
                            "input_ids": encoded["input_ids"].astype(np.int64),
                            "attention_mask": encoded["attention_mask"].astype(
                                np.int64
                            ),
                        }
                        out = self._onnx_session.run(None, inp)
                        token_emb = out[0]
                        mask_exp = np.expand_dims(inp["attention_mask"], -1).astype(
                            float
                        )
                        sum_emb = np.sum(token_emb * mask_exp, 1)
                        sum_mask = np.clip(np.sum(mask_exp, 1), a_min=1e-9, a_max=None)
                        embeddings.append((sum_emb / sum_mask).tolist()[0])
                    return embeddings

                input_mask_expanded = np.expand_dims(
                    inputs["attention_mask"], -1
                ).astype(float)
                sum_embeddings = np.sum(token_embeddings * input_mask_expanded, 1)
                sum_mask = np.clip(
                    np.sum(input_mask_expanded, 1), a_min=1e-9, a_max=None
                )
                embeddings = (sum_embeddings / sum_mask).tolist()
                return embeddings

        # Режим 3: Fallback — пробуем переключиться на LM Studio
        if self._check_lm_studio():
            with self._mode_lock:
                self.mode = "lm_studio"
            logger.info("🌐 Fallback: LM Studio обнаружен, переключаюсь на него.")
            # Рекурсивный вызов с новым режимом
            return self.embed_batch(texts, is_query)

        # Режим 4: Честный заглушечный вектор (Защита сервера от падения)
        logger.critical(
            "⚠️ ВНИМАНИЕ: Все движки векторизации недоступны. Генерация пустых заглушек."
        )
        return [[0.0] * self.embedding_dim for _ in texts]

    def embed(self, text: str, is_query: bool = False) -> List[float]:
        """Получить вектор для одного текстового фрагмента."""
        res = self.embed_batch([text], is_query=is_query)
        return res[0] if res else []

    # ════════════════════════════════════════════════════════════
    # ASYNC HTTP CLIENT (Connection Pool)
    # ════════════════════════════════════════════════════════════

    def _get_async_client(self) -> httpx.AsyncClient:
        """Ленивое создание AsyncClient с connection pool."""
        if self._async_client is None:
            with self._async_client_lock:
                if self._async_client is None:
                    limits = httpx.Limits(
                        max_connections=20,
                        max_keepalive_connections=5,
                        keepalive_expiry=60.0,
                    )
                    self._async_client = httpx.AsyncClient(
                        limits=limits,
                        timeout=httpx.Timeout(self.timeout, connect=3.0),
                    )
        return self._async_client

    async def embed_batch_async(
        self, texts: List[str], is_query: bool = False
    ) -> List[List[float]]:
        """Асинхронный embed через connection pool (без httpx.Client на каждый вызов)."""
        if not texts:
            return []

        if self.mode != "lm_studio":
            return self.embed_batch(texts, is_query)

        try:
            client = self._get_async_client()
            payload = {"model": self.model_name, "input": texts}
            r = await client.post(self.lm_studio_url, json=payload)

            if r.status_code == 200:
                data = r.json().get("data", [])
                if data:
                    data = sorted(data, key=lambda x: x.get("index", 0))
                    return [item["embedding"] for item in data]

            logger.debug(
                f"LM Studio async error (HTTP {r.status_code}), fallback to sync"
            )
            return self.embed_batch(texts, is_query)

        except Exception as e:
            logger.debug(f"LM Studio async failed: {e}, fallback to sync")
            return self.embed_batch(texts, is_query)

    async def embed_async(self, text: str, is_query: bool = False) -> List[float]:
        """Асинхронный embed для одного текста."""
        res = await self.embed_batch_async([text], is_query=is_query)
        return res[0] if res else []

    async def warmup(self) -> bool:
        """Прогрев эмбеддера тестовым запросом (убивает cold start)."""
        if self.mode != "lm_studio":
            logger.info("⏳ Warmup: LM Studio не в режиме lm_studio, пропускаю")
            return False
        try:
            logger.info("⏳ Warmup: прогрев bge-m3...")
            t0 = time.perf_counter()
            await self.embed_async("warmup")
            elapsed = round((time.perf_counter() - t0) * 1000, 1)
            logger.info(f"✅ Warmup: модель прогрета за {elapsed}ms")
            return True
        except Exception as e:
            logger.warning(f"⚠️ Warmup: не удалось прогреть модель: {e}")
            return False

    async def close(self):
        """Корректное закрытие connection pool."""
        if self._async_client is not None:
            await self._async_client.aclose()
            self._async_client = None
            logger.info("Connection pool закрыт")
