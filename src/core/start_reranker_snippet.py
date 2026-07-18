import asyncio
import logging
import subprocess
import sys
import time

import httpx

logger = logging.getLogger("mscodebase_server.reranker")

async def start_reranker(self) -> bool:
        """Запускает llama-server с --reranking (BGE-M3 на порту RERANK_PORT)."""
        if self._reranker_process is not None:
            poll = self._reranker_process.poll()
            if poll is None:
                return True  # уже работает

        gguf_path = _gguf_path(DEFAULT_RERANKER_MODEL)
        if not gguf_path.exists():
            logger.error(f"Reranker GGUF не найден: {gguf_path}")
            return False

        self._ensure_port_free(self.RERANK_PORT)

        try:
            self._reranker_process = subprocess.Popen(
                [
                    str(_llama_bin()),
                    "--host", self._host,
                    "--port", str(self.RERANK_PORT),
                    "-m", str(gguf_path),
                    "-c", str(LLAMA_CTX_SIZE),     # 🔒 1024 = 573 MB для BGE-M3
                    "--batch-size", "256",
                    "--ubatch-size", "64",
                    "--cache-type-k", str(LLAMA_CACHE_TYPE), # 🧹 сжатие KV кэша
                    "--cache-type-v", str(LLAMA_CACHE_TYPE), # 🧹 сжатие KV кэша
                    "--no-webui",
                    "-ngl", "0",
                    "--reranking",
                ],
                stdout=subprocess.DEVNULL,
                stderr=open(self._reranker_log_path(), 'a'),
                creationflags=subprocess.CREATE_NO_WINDOW
                if sys.platform == "win32" else 0,
            )



            # Ждём /health
            t0 = time.time()
            async with httpx.AsyncClient(timeout=2.0) as client:
                for i in range(self._startup_timeout):
                    await asyncio.sleep(1)
                    try:
                        r = await client.get(f"http://{self._host}:{self.RERANK_PORT}/health")
                        if r.status_code == 200:
                            dt = time.time() - t0
                            logger.info(f"🚀 Reranker (BGE-M3) готов за {dt:.1f}s")
                            return True
                    except Exception as _e:
                        logger.warning("exception", exc_info=True)
                        pass
            logger.error(f"Reranker не стартовал за {self._startup_timeout}s")
            await self.stop_reranker()
            return False

        except Exception as e:
            logger.error(f"Ошибка запуска reranker: {e}")
            return False
