"""
MSCodeBase Intelligence - Универсальный адаптивный Эмбеддер (RemoteEmbedder)
Размещается в src/core/remote_embedder.py
"""

import logging
import os
import threading
import time
from pathlib import Path
from typing import List

import httpx

logger = logging.getLogger("mscodebase_server.embedder")

# Интервал проверки доступности внешних API (секунды)
_PROVIDER_SCAN_INTERVAL = int(os.getenv("PROVIDER_SCAN_INTERVAL", "30"))


class RemoteEmbedder:
    def __init__(
        self, port: int = 1234, host: str = "127.0.0.1", timeout: float = 30.0
    ):
        """Универсальный клиент эмбеддингов с каскадным переключением (LM Studio -> ONNX -> Fallback).

        Автоматически сканирует доступность LM Studio / Ollama в фоновом потоке.
        Если внешний сервер появился — переключается на него без перезапуска Zed.
        """
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

        # Блокировка для потокобезопасного переключения режима
        self._mode_lock = threading.Lock()

        # Первичный тест доступности инфраструктуры
        self.mode = "lm_studio"
        self._preferred_mode = "lm_studio"  # режим, к которому стремимся вернуться
        _lm_available = self._check_lm_studio()
        if not _lm_available:
            if os.getenv("EMBEDDING_PROVIDER") == "ollama":
                self.mode = "ollama"
                self._preferred_mode = "ollama"
                logger.info("⚠️ LM Studio не отвечает. Переключаемся в режим OLLAMA.")
            else:
                self.mode = "onnx"
                self._preferred_mode = "lm_studio"
                logger.info(
                    "⚠️ Внешние API не обнаружены. Будет задействован ЛОКАЛЬНЫЙ движок ONNX Runtime."
                )

        # Запуск фонового сканера доступности провайдера (только если LM Studio ещё не доступен)
        self._scanner_stop = threading.Event()
        if not _lm_available:
            logger.info(
                f"🔄 Фоновый сканер будет проверять LM Studio каждые {_PROVIDER_SCAN_INTERVAL}с."
            )
            self._scanner_thread = threading.Thread(
                target=self._provider_scanner_loop,
                name="mscodebase-provider-scanner",
                daemon=True,
            )
            self._scanner_thread.start()
        else:
            logger.info("✅ LM Studio доступен при старте. Фоновый сканер не запускается.")
            self._scanner_thread = None

    def _check_lm_studio(self) -> bool:
        """Быстрая проверка доступности порта LM Studio."""
        try:
            with httpx.Client(timeout=2.0) as client:
                r = client.get(f"http://{self.host}:{self.port}/v1/models")
                if r.status_code == 200:
                    models = r.json().get("data", [])
                    if models:
                        return True
            return False
        except Exception:
            return False

    def _check_ollama(self) -> bool:
        """Быстрая проверка доступности Ollama."""
        try:
            with httpx.Client(timeout=2.0) as client:
                r = client.get("http://localhost:11434/api/tags")
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
                        "� Ollama обнаружен! Переключаюсь с ONNX → Ollama. "
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
        return [[0.0] * 1024 for _ in texts]

    def embed(self, text: str, is_query: bool = False) -> List[float]:
        """Получить вектор для одного текстового фрагмента."""
        res = self.embed_batch([text], is_query=is_query)
        return res[0] if res else []
