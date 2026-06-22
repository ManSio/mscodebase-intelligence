"""
MSCodeBase Intelligence - Универсальный адаптивный Эмбеддер (RemoteEmbedder)
Размещается в src/core/remote_embedder.py
"""

import logging
import os
from pathlib import Path
from typing import List

import httpx

logger = logging.getLogger("mscodebase_server.embedder")


class RemoteEmbedder:
    def __init__(
        self, port: int = 1234, host: str = "127.0.0.1", timeout: float = 30.0
    ):
        """Универсальный клиент эмбеддингов с каскадным переключением (LM Studio -> ONNX -> Fallback)."""
        self.host = host
        self.port = port
        self.timeout = timeout
        self.lm_studio_url = f"http://{host}:{port}/v1/embeddings"
        self.model_name = os.getenv("MODEL_NAME", "text-embedding-bge-m3")

        # Переменные для локального ONNX (ленивая инициализация, чтобы не жрать ОЗУ зря)
        self._onnx_session = None
        self._tokenizer = None
        self.ext_root = Path(__file__).resolve().parent.parent.parent
        self.local_model_dir = self.ext_root / ".codebase_models" / "all-MiniLM-L6-v2"

        # Первичный тест доступности инфраструктуры
        self.mode = "lm_studio"
        if not self._check_lm_studio():
            if os.getenv("EMBEDDING_PROVIDER") == "ollama":
                self.mode = "ollama"
                logger.info("⚠️ LM Studio не отвечает. Переключаемся в режим OLLAMA.")
            else:
                self.mode = "onnx"
                logger.info(
                    "⚠️ Внешние API не обнаружены. Будет задействован ЛОКАЛЬНЫЙ движок ONNX Runtime."
                )

    def _check_lm_studio(self) -> bool:
        """Быстрая проверка доступности порта LM Studio."""
        try:
            with httpx.Client(timeout=1.0) as client:
                r = client.get(f"http://{self.host}:{self.port}/v1/models")
                return r.status_code == 200
        except Exception:
            return False

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

        # Режим 1: LM Studio (Высокий приоритет)
        if self.mode == "lm_studio":
            try:
                payload = {"model": self.model_name, "input": texts}
                with httpx.Client(timeout=self.timeout) as client:
                    r = client.post(self.lm_studio_url, json=payload)
                    if r.status_code == 200:
                        data = r.json().get("data", [])
                        data = sorted(data, key=lambda x: x.get("index", 0))
                        return [item["embedding"] for item in data]
                    else:
                        logger.warning(
                            f"LM Studio отклонил запрос (HTTP {r.status_code}). Падаем в ONNX."
                        )
                        self.mode = "onnx"
            except Exception as e:
                logger.warning(
                    f"Сбой связи с LM Studio: {e}. Переходим на локальный ONNX."
                )
                self.mode = "onnx"

        # Режим 2: Локальный ONNX Runtime (Автономный режим без интернета)
        if self.mode == "onnx":
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
                    input_mask_expanded = np.expand_dims(
                        inputs["attention_mask"], -1
                    ).astype(float)
                    sum_embeddings = np.sum(token_embeddings * input_mask_expanded, 1)
                    sum_mask = np.clip(
                        np.sum(input_mask_expanded, 1), a_min=1e-9, a_max=None
                    )
                    embeddings = (sum_embeddings / sum_mask).tolist()
                    return embeddings
                except Exception as e:
                    logger.error(f"Ошибка вычислений внутри ONNX Runtime: {e}")

        # Режим 3: Честный заглушечный вектор (Защита сервера от падения)
        logger.critical(
            "⚠️ ВНИМАНИЕ: Все движки векторизации недоступны. Генерация пустых заглушек."
        )
        return [[0.0] * 384 for _ in texts]

    def embed(self, text: str, is_query: bool = False) -> List[float]:
        """Получить вектор для одного текстового фрагмента."""
        res = self.embed_batch([text], is_query=is_query)
        return res[0] if res else []
