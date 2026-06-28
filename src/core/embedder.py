"""
Модуль для загрузки и использования моделей embeddings.
Поддерживает ONNX Runtime с автовыбором ускорителя (CUDA/DirectML/CPU)
и внешние API (Ollama, LM Studio, OpenAI-compatible).

Автоматически подстраивается под любую модель:
- Определяет размерность векторов на летту
- Использует префиксы (query:/passage:) для E5, BGE, Instructor и других моделей
- Не требует хардкода под конкретную модель
"""

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Словарь правил для префиксов разных моделей.
# {подстрока в имени модели: (префикс_запроса, префикс_документа)}
# Регистр не важен — ищем через .lower()
MODEL_PREFIX_RULES: Dict[str, tuple] = {
    "e5": ("query: ", "passage: "),
    "bge-m3": ("Represent this sentence for searching relevant passages: ", ""),
    "bge-": ("Represent this sentence for searching relevant passages: ", ""),
    "instructor": ("", ""),  # Instructor требует отдельный вызов, пропускаем
    "gte-": ("query: ", "passage: "),
    "stella": ("query: ", ""),
    "jina-embeddings": ("", ""),  # Jina не требует префиксов
}


def _detect_prefixes(model_name: str) -> tuple:
    """Определяет префиксы для модели по её имени.

    Returns:
        (query_prefix, document_prefix) — строки, добавляемые к тексту.
    """
    name = model_name.lower()
    for key, (q_prefix, d_prefix) in MODEL_PREFIX_RULES.items():
        if key in name:
            logger.debug(
                f"🔍 Для модели '{model_name}' определены префиксы: query='{q_prefix}', doc='{d_prefix}'"
            )
            return q_prefix, d_prefix
    return "", ""


class Embedder:
    """Загружает модель и создаёт векторные представления текста."""

    def __init__(
        self, model_dir: Optional[Path] = None, model_name: Optional[str] = None
    ):
        self.provider = os.getenv("EMBEDDING_PROVIDER", "onnx").lower()

        # Умные дефолты портов в зависимости от выбранного провайдера
        default_url = (
            "http://localhost:11434"
            if self.provider == "ollama"
            else "http://localhost:1234/v1"
        )
        self.api_url = os.getenv("API_BASE_URL", default_url).rstrip("/")
        self.api_key = os.getenv("API_KEY", "sk-local")

        project_path = Path(os.getenv("PROJECT_PATH", ".")).resolve()
        self.model_dir = model_dir or (
            project_path / os.getenv("MODEL_DIR", ".codebase_models")
        )
        self.model_name = model_name or os.getenv("MODEL_NAME", "BAAI/bge-m3")
        self.model = None
        self.session = None
        self.tokenizer = None
        self.active_provider = "none"
        self.is_available = False
        self._dimension: Optional[int] = None  # Размерность, определяется при load()

        # Автоопределение префиксов по имени модели
        query_prefix, doc_prefix = _detect_prefixes(self.model_name)
        self._query_prefix = query_prefix
        self._doc_prefix = doc_prefix

        # КРИТИЧЕСКИЙ ОФФЛОАД: Больше не вызываем скачивание и загрузку в конструкторе!
        # Это предотвращает зависание при создании объекта. Всё управление передано методу load().

    def _try_lm_studio(self) -> bool:
        """Проверяет, запущен ли LM Studio на localhost:1234.
        Если да — переключается на него вместо локальной модели.
        """
        try:
            import httpx

            r = httpx.get("http://localhost:1234/v1/models", timeout=2.0)
            if r.status_code == 200:
                models = r.json().get("data", [])
                if models:
                    model_id = models[0].get("id", "unknown")
                    self.provider = "openai"
                    self.api_url = "http://localhost:1234/v1"
                    self.model_name = model_id
                    self.active_provider = "lm-studio"
                    self.is_available = True
                    logger.info(f"🌐 Автоопределён LM Studio: модель {model_id}")
                    return True
        except Exception:
            pass
        return False

    @property
    def dimension(self) -> int:
        """Размерность эмбеддингов (определяется при загрузке модели)."""
        if self._dimension is not None:
            return self._dimension
        return 1024  # fallback если модель ещё не загружена

    def _ensure_model_downloaded(self) -> bool:
        """Проверяет наличие локальных файлов модели.

        Если модели нет — скачивает и экспортирует в ONNX автоматически.
        Это единственная точка, где происходит сетевое скачивание.
        """
        required_files = ["onnx/model.onnx", "tokenizer.json", "config.json"]
        missing_files = [
            name for name in required_files if not (self.model_dir / name).exists()
        ]

        if not missing_files:
            logger.info(f"✅ Модель уже на диске: {self.model_dir}")
            return True

        # Модели нет — качаем прямо сейчас
        logger.info(
            f"📥 Модель не найдена. Скачиваю {self.model_name} в {self.model_dir}..."
        )
        try:
            from scripts.download_model import download_onnx_model

            self.model_dir.mkdir(parents=True, exist_ok=True)
            download_onnx_model(self.model_name, self.model_dir)
            logger.info(f"✅ Модель успешно скачана: {self.model_dir}")
            return True
        except Exception as e:
            logger.error(f"❌ Не удалось скачать модель: {e}", exc_info=True)
            self.model = None
            self.session = None
            self.tokenizer = None
            self.active_provider = "none"
            return False

    def load(self) -> bool:
        """Загружает локальную модель или проверяет конфигурацию внешнего API.

        Реализует graceful degradation:
        1. Пробуем LM Studio (если доступен)
        2. Пробуем внешний API (Ollama/OpenAI)
        3. Пробуем локальный ONNX Runtime
        4. Если ничего не доступно — переключаемся на fallback с предупреждением

        Returns:
            True если загрузка успешна (даже в fallback-режиме),
            False если произошла критическая ошибка.
        """
        # Автоопределение: если LM Studio запущен — используем его
        if self.provider == "onnx":
            if self._try_lm_studio():
                return True

        if self.provider != "onnx":
            self.active_provider = self.provider
            self.is_available = True
            logger.info(
                f"🌐 Активирован внешний API-провайдер: {self.provider} ({self.api_url})"
            )
            return True

        # Пробуем загрузить локальную ONNX модель
        try:
            if not self._ensure_model_downloaded():
                logger.warning(
                    "⚠️ Модель embeddings не найдена. "
                    "Выполните: python download_model.py --model " + self.model_name
                )
                self.is_available = False
                self.active_provider = "fallback"
                return True  # Не критическая ошибка — работаем без embeddings

            import onnxruntime as ort
            from transformers import AutoTokenizer

            model_path = self.model_dir / "onnx" / "model.onnx"
            if not model_path.exists():
                logger.error(
                    f"❌ Файл модели не найден по пути: {model_path}. "
                    f"Удалите папку {self.model_dir} и запустите download_model.py заново."
                )
                self.is_available = False
                self.active_provider = "fallback"
                return True

            # Автовыбор лучшего доступного бэкенда: CUDA → DirectML → CPU
            providers = []
            available = ort.get_available_providers()

            if "CUDAExecutionProvider" in available:
                providers.append("CUDAExecutionProvider")
            if "DmlExecutionProvider" in available:
                providers.append("DmlExecutionProvider")
            if "DirectMLExecutionProvider" in available:
                providers.append("DirectMLExecutionProvider")
            if "CoreMLExecutionProvider" in available:
                providers.append("CoreMLExecutionProvider")
            if "OpenVINOExecutionProvider" in available:
                providers.append("OpenVINOExecutionProvider")
            providers.append("CPUExecutionProvider")

            self.session = ort.InferenceSession(str(model_path), providers=providers)
            self.tokenizer = AutoTokenizer.from_pretrained(str(self.model_dir))

            # Определяем размерность: прогоняем один тестовый токен
            import numpy as np

            test_input = self.tokenizer(
                "test", return_tensors="np", padding=True, truncation=True
            )
            test_output = self.session.run(None, dict(test_input))
            self._dimension = test_output[0].shape[-1]

            logger.info(
                f"📐 Размерность модели: {self._dimension} "
                f"(префиксы: query='{self._query_prefix}', doc='{self._doc_prefix}')"
            )

            self.active_provider = self.session.get_providers()[0]
            self.is_available = True
            logger.info(
                f"🚀 Локальный Embedder успешно запущен. Аппаратный движок: {self.active_provider}"
            )
            return True

        except ImportError as e:
            logger.error(
                f"❌ Не установлены зависимости ONNX: {e}. "
                f"Выполните: pip install onnxruntime transformers"
            )
            self.is_available = False
            self.active_provider = "fallback"
            return True  # Graceful degradation

        except Exception as e:
            logger.error(
                f"❌ Ошибка загрузки ONNX Runtime: {e}. "
                f"Embedder переключён в fallback-режим.",
                exc_info=True,
            )
            self.is_available = False
            self.active_provider = "fallback"
            return True  # Graceful degradation — не падаем

    def embed(self, text: str, is_query: bool = False) -> List[float]:
        """Создаёт векторное представление одного фрагмента текста."""
        res = self.embed_batch([text], is_query=is_query)
        if not res:
            return []
        return res[0]

    def embed_batch(
        self, texts: List[str], is_query: bool = False
    ) -> List[List[float]]:
        """Создаёт векторные представления для списка (батча) текстов."""
        if not texts:
            return []

        # Добавляем префиксы, если модель их требует (E5, BGE, GTE и т.д.)
        prefix = self._query_prefix if is_query else self._doc_prefix
        if prefix:
            texts = [prefix + t for t in texts]
            logger.debug(
                f"🔄 Добавлен префикс '{prefix.strip()}' для {len(texts)} текстов"
            )

        if self.provider == "onnx":
            if not self.is_available:
                logger.warning("⚠️ Embedder недоступен: возвращаю пустые embeddings.")
                return [[] for _ in texts]
            return self._embed_batch_onnx(texts)
        else:
            return self._embed_batch_api(texts)

    def _embed_batch_onnx(self, texts: List[str]) -> List[List[float]]:
        """Пакетный эмбеддинг через локальную ONNX модель с защитой от перегрузки памяти (OOM)."""
        if not self.session or not self.tokenizer:
            raise RuntimeError(
                "Движок ONNX не инициализирован. Сначала вызовите load()."
            )

        import numpy as np

        all_embeddings = []
        mini_batch_size = 32

        for i in range(0, len(texts), mini_batch_size):
            sub_batch = texts[i : i + mini_batch_size]

            inputs = self.tokenizer(
                sub_batch,
                return_tensors="np",
                padding=True,
                truncation=True,
                max_length=512,
            )

            outputs = self.session.run(None, dict(inputs))
            token_embeddings = outputs[0]

            # Mean Pooling с честным учетом маски токенов
            input_mask_expanded = np.expand_dims(inputs["attention_mask"], -1)
            sum_embeddings = np.sum(token_embeddings * input_mask_expanded, 1)
            sum_mask = np.clip(input_mask_expanded.sum(1), a_min=1e-9, a_max=None)
            embeddings = sum_embeddings / sum_mask

            # L2 Нормализация
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
            norms = np.where(norms == 0, 1, norms)
            embeddings = embeddings / norms

            all_embeddings.extend(embeddings.tolist())

        return all_embeddings

    def _embed_batch_api(self, texts: List[str]) -> List[List[float]]:
        """Высокопроизводительный пакетный запрос к внешним API (Ollama / OpenAI / LM Studio).

        Синхронная обёртка для обратной совместимости.
        Используйте _embed_batch_api_async() для async контекста.
        """
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # Уже внутри event loop — запускаем в отдельном потоке
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    asyncio.run, self._embed_batch_api_async(texts)
                )
                return future.result(timeout=65)
        else:
            return asyncio.run(self._embed_batch_api_async(texts))

    async def _embed_batch_api_async(self, texts: List[str]) -> List[List[float]]:
        """Асинверсия пакетного запроса к внешним API (Ollama / OpenAI / LM Studio)."""
        import httpx

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        all_embeddings = []
        api_batch_size = 32

        async with httpx.AsyncClient(timeout=60.0) as client:
            for i in range(0, len(texts), api_batch_size):
                sub_batch = texts[i : i + api_batch_size]

                if self.provider == "ollama":
                    url = f"{self.api_url}/api/embed"
                    payload = {"model": self.model_name, "input": sub_batch}
                else:
                    url = f"{self.api_url}/embeddings"
                    payload = {"model": self.model_name, "input": sub_batch}

                try:
                    response = await client.post(url, json=payload, headers=headers)
                    response.raise_for_status()
                    res_json = response.json()

                    if self.provider == "ollama":
                        if "embeddings" in res_json:
                            all_embeddings.extend(res_json["embeddings"])
                        elif "embedding" in res_json and len(sub_batch) == 1:
                            all_embeddings.append(res_json["embedding"])
                        else:
                            raise KeyError(
                                "Нетипичный формат ответа Ollama API. Проверьте имя модели."
                            )
                    else:
                        data = res_json.get("data", [])
                        if data and "index" in data[0]:
                            data = sorted(data, key=lambda x: x["index"])
                        batch_embs = [item["embedding"] for item in data]
                        all_embeddings.extend(batch_embs)

                except Exception as e:
                    logger.error(
                        f"❌ Ошибка сетевого API эмбеддингов ({self.provider}): {e}"
                    )
                    raise RuntimeError(
                        f"Сбой внешнего API Эмбеддингов ({self.provider}): {e}"
                    )

        return all_embeddings

    async def embed_batch_async(
        self, texts: List[str], is_query: bool = False
    ) -> List[List[float]]:
        """Асинхронная версия embed_batch()."""
        if not texts:
            return []

        # Добавляем префиксы, если модель их требует (E5, BGE, GTE и т.д.)
        prefix = self._query_prefix if is_query else self._doc_prefix
        if prefix:
            texts = [prefix + t for t in texts]

        if self.provider == "onnx":
            if not self.is_available:
                return [[] for _ in texts]
            # ONNX — синхронный, запускаем в thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._embed_batch_onnx, texts)
        else:
            return await self._embed_batch_api_async(texts)
