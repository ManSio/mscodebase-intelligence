"""
MSCodeBase Intelligence - Модуль удаленного эмбеддера (RemoteEmbedder)
"""

import logging
from typing import List

import httpx

logger = logging.getLogger("mscodebase_server.embedder")


class RemoteEmbedder:
    def __init__(
        self, port: int = 1234, host: str = "127.0.0.1", timeout: float = 60.0
    ):
        """Инициализация эмбеддера под LM Studio."""
        self.host = host
        self.port = port
        self.timeout = timeout
        self.base_url = f"http://{host}:{port}"
        self.model_name = "text-embedding-bge-m3"
        logger.info(f"🔌 Эмбеддер инициализирован на целевой адрес: {self.base_url}")

    def embed(self, text: str, is_query: bool = False) -> List[float]:
        """Получить вектор для одного фрагмента текста."""
        if not text:
            return []
        try:
            with httpx.Client(timeout=self.timeout) as client:
                r = client.post(
                    f"{self.base_url}/v1/embeddings",
                    json={"model": self.model_name, "input": text},
                )
                if r.status_code == 200:
                    return r.json().get("data", [{}])[0].get("embedding", [])
                else:
                    logger.error(
                        f"❌ LM Studio вернул ошибку HTTP {r.status_code}: {r.text}"
                    )
        except Exception as e:
            logger.error(f"❌ Ошибка сети при обращении к LM Studio: {e}")
        return []

    def embed_batch(
        self, texts: List[str], is_query: bool = False
    ) -> List[List[float]]:
        """Прямая батч-отправка чанков кода в LM Studio."""
        if not texts:
            return []

        try:
            url = f"{self.base_url}/v1/embeddings"
            payload = {"model": self.model_name, "input": texts}
            with httpx.Client(timeout=60.0) as client:
                r = client.post(url, json=payload)
                if r.status_code == 200:
                    data = r.json().get("data", [])
                    data = sorted(data, key=lambda x: x.get("index", 0))
                    return [item["embedding"] for item in data]
                else:
                    logger.error(
                        f"❌ LM Studio отклонил батч-запрос: {r.status_code} - {r.text}"
                    )
        except Exception as e:
            logger.error(f"❌ Ошибка физической батч-отправки пакета в LM Studio: {e}")

        return [[] for _ in texts]
