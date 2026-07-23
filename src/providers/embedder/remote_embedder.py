"""
MSCodeBase Intelligence - Универсальный адаптивный Эмбеддер (RemoteEmbedder)
Размещается в src/core/remote_embedder.py
"""

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, List, Optional

import httpx
import numpy as np

from src.config.settings import get_config
from src.core.interfaces import IEmbedder
from src.core.platform_utils import get_extension_dir

__all__ = [
    "RemoteEmbedder",
]
logger = logging.getLogger("mscodebase_server.embedder")

# Интервал проверки доступности внешних API (секунды)
_PROVIDER_SCAN_INTERVAL = int(os.getenv("PROVIDER_SCAN_INTERVAL", "30"))


class RemoteEmbedder(IEmbedder):
    def __init__(
        self,
        port: Optional[int] = None,
        host: Optional[str] = None,
        timeout: Optional[float] = None,
        breaker: Optional[Any] = None,
    ):
        config = get_config()

        self.host = host or config.embedding.lm_studio_host
        self.port = port or config.embedding.lm_studio_port
        self.timeout = timeout or config.performance.embedding_timeout
        self.lm_studio_url = f"http://{self.host}:{self.port}/v1/embeddings"
        self.model_name = config.embedding.model_name

        self._breaker = breaker
        self.embedding_dim = config.embedding.embedding_dimension

        # ONNX Server (общий для всех проектов, через HTTP)
        perf_cfg = config.performance
        self.onnx_server_host = perf_cfg.onnx_server_host
        self.onnx_server_port = perf_cfg.onnx_server_port
        self.onnx_server_url = (
            f"http://{self.onnx_server_host}:{self.onnx_server_port}/v1/embeddings"
        )
        # llama.cpp (Zed 1.10.0 native provider)
        self.llama_cpp_host = os.getenv("LLAMA_CPP_HOST", "127.0.0.1")
        self.llama_cpp_port = int(os.getenv("LLAMA_CPP_PORT", "8080"))
        self.llama_cpp_url = (
            f"http://{self.llama_cpp_host}:{self.llama_cpp_port}/v1/embeddings"
        )

        # ONNX session (ленивая инициализация, fallback если сервер недоступен)
        self._onnx_session = None
        self._tokenizer = None
        # ONNX idle timeout: выгружать модель через N секунд бездействия
        self._onnx_idle_timeout = 300  # 5 минут
        self._onnx_last_used = 0.0
        self._onnx_cleanup_task: Optional[threading.Thread] = None
        self._onnx_cleanup_stop = threading.Event()
        # Запускаем фоновый cleanup (проверка каждые 60 сек)
        self._start_onnx_cleanup()
        self.ext_root = get_extension_dir("mscodebase-intelligence")
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

        # ── Shadow Canary: эталонные пары запрос→чанк ──────────
        self._canary_pairs: List[dict] = []
        self._load_canary_set()

    def _load_canary_set(self):
        """Загружает canary-набор из canary_set.json."""
        import json

        paths = [
            Path(__file__).resolve().parent / "canary_set.json",
            self.ext_root / "src" / "providers" / "embedder" / "canary_set.json",
        ]
        for cp in paths:
            if cp.exists():
                try:
                    data = json.loads(cp.read_text(encoding="utf-8"))
                    self._canary_pairs = data.get("pairs", [])
                    logger.info(f"🐦 Shadow Canary: {len(self._canary_pairs)} pairs loaded from {cp.name}")
                except Exception as e:
                    logger.warning(f"🐦 Canary load failed: {e}")
                return
        logger.info("🐦 Shadow Canary: no canary_set.json found (disabled)")

    def _shadow_compare(self, new_embed_fn, new_name: str) -> bool:
        """Shadow Canary: сравнивает качество эмбеддинга до и после смены провайдера.

        Args:
            new_embed_fn: callable(texts) -> List[List[float]] — эмбеддер нового провайдера.
            new_name: имя нового провайдера (для лога).

        Returns:
            True если новый провайдер не хуже старого (можно переключать).
            False если качество упало (отказ от переключения).
        """
        if not self._canary_pairs:
            return True  # нет canary — доверяем


        def _cos_sim(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            na = sum(x * x for x in a) ** 0.5
            nb = sum(x * x for x in b) ** 0.5
            return dot / (na * nb) if na and nb else 0.0

        # Прогоняем через текущий провайдер (базлайн)
        old_queries = [p["query"] for p in self._canary_pairs]
        old_chunks = [p["expected_chunk"] for p in self._canary_pairs]

        try:
            old_q_vecs = self.embed_batch(old_queries, is_query=True)
            old_c_vecs = self.embed_batch(old_chunks, is_query=False)
        except Exception as e:
            logger.warning(f"🐦 Shadow baseline failed: {e}")
            return True

        if not old_q_vecs or not old_c_vecs:
            return True

        old_sims = [_cos_sim(q, c) for q, c in zip(old_q_vecs, old_c_vecs)]
        old_mean = sum(old_sims) / len(old_sims) if old_sims else 0.0

        # Прогоняем через новый провайдер
        try:
            new_q_vecs = new_embed_fn(old_queries)
            new_c_vecs = new_embed_fn(old_chunks)
        except Exception as e:
            logger.warning(f"🐦 Shadow {new_name} failed: {e}")
            return False

        if not new_q_vecs or not new_c_vecs:
            logger.warning(f"🐦 Shadow {new_name}: empty response")
            return False

        new_sims = [_cos_sim(q, c) for q, c in zip(new_q_vecs, new_c_vecs)]
        new_mean = sum(new_sims) / len(new_sims) if new_sims else 0.0

        # Сравнение с tolerance 10%
        threshold = old_mean * 0.9
        degraded = sum(1 for n in new_sims if n < threshold)
        degraded_ratio = degraded / len(new_sims) if new_sims else 1.0

        logger.info(
            f"🐦 Shadow Canary: {new_name} vs baseline | "
            f"old_mean={old_mean:.4f} new_mean={new_mean:.4f} "
            f"degraded={degraded}/{len(new_sims)} ({degraded_ratio:.0%})"
        )

        if degraded_ratio > 0.3:
            logger.warning(
                f"🐦 Shadow Canary: ❌ {new_name} quality degraded "
                f"({degraded_ratio:.0%} pairs worse than baseline). "
                f"Switch BLOCKED."
            )
            return False

        logger.info(f"🐦 Shadow Canary: ✅ {new_name} passed (degraded {degraded_ratio:.0%})")
        return True

    def _detect_model_dir(self):
        """Find the first available ONNX model in .codebase_models/onnx/*/model.onnx
        Checks multiple locations: ext_root, project_root, shared cache.

        Memory-safe: uses onnx.shape_inference (lightweight) instead of
        creating a full InferenceSession which loads 500+ MB unnecessarily.
        """
        for base in self._onnx_search_paths:
            if not base.exists():
                logger.debug(f"[detect] Base NOT EXISTS: {base}")
                continue
            logger.debug(f"[detect] Checking base: {base}")
            # Только INT8 (model_quantized.onnx). FP32 не используется.
            _subdirs = sorted(base.iterdir(), key=lambda d: (
                0 if '-int8' in d.name else 1,  # INT8 first
                d.name
            ))
            for subdir in _subdirs:
                # Skip reranker subdirectories for embedder
                if subdir.name.startswith("reranker-") or subdir.name.startswith(
                    "rreranker"
                ):
                    continue
                # Только INT8 (model_quantized.onnx)
                int8_file = subdir / "model_quantized.onnx"
                if not int8_file.exists():
                    continue
                model_file = int8_file
                self.local_model_dir = subdir
                self._model_name = subdir.name
                sz = model_file.stat().st_size / (1024 * 1024)
                # Lightweight dimension detection: onnx protobuf metadata,
                # NOT full InferenceSession (saves ~544 MB peak).
                dim = self._lightweight_onnx_dim(model_file)
                if dim:
                    self.embedding_dim = dim
                dim_str = f"{dim}dim" if dim else "dim?"
                logger.info(
                    f"ONNX model: {subdir.name} ({dim_str}, {sz:.0f}MB) — embedding_dim={self.embedding_dim}"
                )
                break  # model found, exit inner loop
            else:
                continue  # inner loop didn't break → no model in this base
            break  # model found, exit outer loop

        # Блокировка для потокобезопасного переключения режима
        self._mode_lock = threading.Lock()

        # КРИТИЧНО (INC-6BCB): НЕ БЛОКИРОВАТЬ __init__ HTTP-запросами.
        # На старте MCP-сервера блокирующий httpx.get может занять 2-5
        # секунд и привести к таймауту создания сервера в Zed.
        # Решение: mode = "unknown", фоновый сканер определит режим асинхронно.
        self.mode = "unknown"
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

        # Фоновая предзагрузка ONNX через 15 сек после старта.
        # К этому моменту MCP сервер уже инициализирован, а модель
        # будет готова к первому запросу пользователя (без 11 сек задержки).
        self._preload_thread = threading.Thread(
            target=self._preload_onnx_delayed,
            name="mscodebase-onnx-preload",
            daemon=True,
        )
        self._preload_thread.start()

    @staticmethod
    def _lightweight_onnx_dim(model_file: Path) -> Optional[int]:
        """Читает размерность эмбеддинга из ONNX-файла без загрузки весов.

        Использует onnx.shape_inference (только граф, ~5MB пик RSS)
        вместо ort.InferenceSession (весь модель ~544MB пик RSS).
        """
        try:
            import onnx

            onnx_model = onnx.load(str(model_file), load_external_data=False)
            # Берём output графа — последний узел, его размерность
            graph = onnx_model.graph
            if graph.output:
                shape = graph.output[0].type.tensor_type.shape
                if shape and shape.dim:
                    return shape.dim[-1].dim_value
        except Exception as _e:
            # fallback to known model dimensions by name
            try:
                name = model_file.parent.name
                KNOWN = {
                    "bge-m3": 1024,
                    "bge-base": 768,
                    "bge-small": 384,
                    "bge-large": 1024,
                    "text-embedding-ada": 1536,
                    "gte-small": 384,
                    "gte-base": 768,
                    "gte-large": 1024,
                    "e5-base": 768,
                    "e5-small": 384,
                    "e5-large": 1024,
                }
                for key, val in KNOWN.items():
                    if key in name:
                        return val
            except Exception:
                logger.debug(f"Could not infer dimension for {model_file.name}", exc_info=True)
        return None

    def _preload_onnx_delayed(self):
        """Фоновая предзагрузка ONNX модели через 15 сек после старта MCP.

        Отключает себя, если llama.cpp работает — ONNX не нужен in-process.
        """
        import time as _time

        # Ждём до 60 секунд пока llama.cpp запустится (он стартует через _warmup_embedder)
        # Проверяем каждые 5 секунд — если появился, отменяем ONNX загрузку
        with self._mode_lock:
            if self.mode != "onnx":
                logger.debug("Preload пропущен: режим не ONNX")
                return

        # DISABLE_ONNX_FALLBACK=true — полное отключение ONNX
        if os.getenv("DISABLE_ONNX_FALLBACK", "").lower() in ("true", "1", "yes"):
            logger.info("🔌 ONNX fallback отключён через DISABLE_ONNX_FALLBACK=true")
            with self._mode_lock:
                self.mode = "fallback"
            return

        for attempt in range(12):  # 12 * 5 = 60 секунд
            if self._check_llama_cpp():
                with self._mode_lock:
                    self.mode = "llama_cpp"
                    logger.info("🦙 Preload: найден llama.cpp, ONNX предзагрузка отменена")
                # Запускаем реранкер (BGE-M3 на порту 8081)
                try:
                    import asyncio

                    from src.providers.reranker.llama_runner import get_global_runner
                    runner = get_global_runner()
                    asyncio.run(runner.start_reranker())
                except Exception as e:
                    logger.warning(f"Reranker autostart failed: {e}")
                return
            _time.sleep(5)

        logger.info("⏳ Фоновая предзагрузка ONNX модели (llama.cpp не найден за 60с)...")
        self._init_onnx()
        if self._onnx_session:
            logger.info("✅ ONNX модель предзагружена и готова к работе")

    def _check_lm_studio(self) -> bool:
        """Быстрая проверка доступности порта LM Studio (переиспользует клиент).

        Если подключен CircuitBreaker — проверка проходит через breaker.call()
        для защиты от каскадных сбоев при зависании LM Studio.
        """
        if self._breaker is not None:
            try:
                return bool(
                    self._breaker.call(self._check_lm_studio_raw, fallback=False)
                )
            except Exception:
                return False
        return self._check_lm_studio_raw()

    def _check_lm_studio_raw(self) -> bool:
        """Прямая проверка LM Studio без CircuitBreaker (используется breaker.call внутри)."""
        if self._sync_client is None:
            self._sync_client = httpx.Client(
                timeout=2.0,
                limits=httpx.Limits(max_keepalive_connections=2, keepalive_expiry=30.0),
            )
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
        except Exception as _elx:
            logger.debug(f"[check_lm_studio_raw] {type(_elx).__name__}: {_elx}")
            return False

    def _check_onnx_server(self) -> bool:
        """Проверяет доступность ONNX-сервера."""
        if self._sync_client is None:
            self._sync_client = httpx.Client(
                timeout=2.0,
                limits=httpx.Limits(max_keepalive_connections=2, keepalive_expiry=30.0),
            )
        try:
            r = self._sync_client.get(
                f"http://{self.onnx_server_host}:{self.onnx_server_port}/health"
            )
            return r.status_code == 200
        except Exception:
            return False

    def _find_reranker_dir(self) -> Optional[str]:
        """Ищет директорию reranker модели для передачи в ONNX сервер."""
        for base in self._onnx_search_paths:
            if not base.exists():
                continue
            for slug in ["reranker-bge-reranker-v2-m3", "bge-reranker-v2-m3"]:
                candidate = base / slug
                if candidate.exists() and (candidate / "model.onnx").exists():
                    return str(candidate)
        return None

    def get_model_info(self) -> dict:
        """Возвращает информацию о текущей модели эмбеддера."""
        # Если ONNX загружен — показываем реальную модель
        if self._onnx_session is not None:
            model_name = getattr(self, "_model_name", "e5-base-v2")
        else:
            model_name = getattr(self, "_model_name", self.model_name)
        return {
            "provider": self.mode,
            "model": model_name,
            "configured_model": self.model_name,
            "dimension": self.embedding_dim,
        }

    def _init_provider_async(self):
        """Фоновая инициализация режима провайдера."""
        try:
            # ═══ E5-base ONNX Runtime/OpenVINO (in-process) ═══
            _provider = os.getenv("ONNX_PROVIDERS", "cpu").lower()

            # ═══════════════════════════════════════════════════════════════
            # ONNX Runtime CPU (рекомендуемый режим для AMD Ryzen)
            # BASIC + i6 + inter=1 — лучшая конфигурация (17 ch/s)
            # ═══════════════════════════════════════════════════════════════
            if _provider in ("cpu", ""):
                self._init_onnx()
                if self._onnx_session:
                    with self._mode_lock:
                        self.mode = "onnx"
                        self._preferred_mode = "onnx"
                    logger.info("✅ ONNX Runtime CPU запущен!")
                    return

            # OpenVINO (по запросу, если ONNX_PROVIDERS=openvino)
            if _provider == "openvino":
                self._init_openvino()
                if getattr(self, '_ov_compiled', None) is not None:
                    with self._mode_lock:
                        self.mode = "onnx"
                        self._preferred_mode = "onnx"
                    logger.info("✅ OpenVINO INT8 запущен!")
                return

            # ═══ LM Studio (fallback) ═══
            if self._check_lm_studio_raw():
                with self._mode_lock:
                    self.mode = "lm_studio"
                logger.info("✅ LM Studio доступен (fallback).")
                return

            # ═══ Ollama (fallback) ═══
            if os.getenv("EMBEDDING_PROVIDER") == "ollama":
                if self._check_ollama():
                    with self._mode_lock:
                        self.mode = "ollama"
                    logger.info("⚠️ Переключаюсь на Ollama.")
                    return

            # ═══ ONNX — последняя попытка ═══
            self._init_onnx()
            if self._onnx_session:
                with self._mode_lock:
                    self.mode = "onnx"
                logger.info("✅ E5-base ONNX (повторная попытка) — успех.")
                return

            with self._mode_lock:
                self.mode = "fallback"
            logger.error("❌ НЕ УДАЛОСЬ загрузить E5-base ONNX. Режим fallback.")
        except Exception as e:
            logger.warning(f"_init_provider_async failed, using safe default: {e}")
            with self._mode_lock:
                self.mode = "onnx"  # safe default

    def _check_ollama(self) -> bool:
        """Проверка доступности Ollama (переиспользует sync клиент)."""
        if self._sync_client is None:
            self._sync_client = httpx.Client(
                timeout=2.0,
                limits=httpx.Limits(max_keepalive_connections=2, keepalive_expiry=30.0),
            )
        config = get_config()
        try:
            r = self._sync_client.get(config.embedding.ollama_tags_url)
            return r.status_code == 200
        except Exception:
            return False

    def _check_llama_cpp(self) -> bool:
        """Проверка доступности llama.cpp (Zed 1.10.0 native)."""
        if self._sync_client is None:
            self._sync_client = httpx.Client(
                timeout=2.0,
                limits=httpx.Limits(max_keepalive_connections=2, keepalive_expiry=30.0),
            )
        try:
            r = self._sync_client.get(
                f"http://{self.llama_cpp_host}:{self.llama_cpp_port}/v1/models",
            )
            return r.status_code == 200
        except Exception:
            return False

    # ── Shadow Canary: API-вызовы для нового провайдера (до смены mode) ──

    def _call_lm_studio_api(self, texts):
        """Временный эмбеддинг через LM Studio (для shadow canary)."""
        try:
            r = self._sync_client.post(
                self.lm_studio_url,
                json={"input": texts, "model": self._model_name},
                timeout=10.0,
            )
            if r.status_code == 200:
                data = r.json()
                return [d["embedding"] for d in data["data"]]
        except Exception:
            pass
        return []

    def _call_ollama_api(self, texts):
        """Временный эмбеддинг через Ollama (для shadow canary)."""
        config = get_config()
        try:
            results = []
            for t in texts:
                r = self._sync_client.post(
                    config.embedding.ollama_embeddings_url,
                    json={"model": config.embedding.ollama_model, "prompt": t},
                    timeout=10.0,
                )
                if r.status_code == 200:
                    results.append(r.json().get("embedding", []))
                else:
                    return []
            return results
        except Exception:
            return []

    def _call_llama_cpp_api(self, texts):
        """Временный эмбеддинг через llama.cpp (для shadow canary)."""
        try:
            r = self._sync_client.post(
                self.llama_cpp_url,
                json={"input": texts},
                timeout=10.0,
            )
            if r.status_code == 200:
                data = r.json()
                return [d["embedding"] for d in data["data"]]
        except Exception:
            return []

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
                        logger.warning(
                            "📡 Ollama пропал. Переключаюсь на ONNX. "
                            "Сканер продолжит поиск."
                        )
                        continue
                    # Ollama ещё жив — выходим из цикла
                    logger.debug("Ollama стабилен. Сканер завершает работу.")
                    break

                # llama.cpp — стабилен, не трогаем
                if current == "llama_cpp":
                    logger.debug("llama.cpp стабилен. Сканер завершает работу.")
                    break

                # current == "onnx" или "fallback" — ищем внешний провайдер
                # Используем _raw, чтобы CircuitBreaker не кэшировал недоступный сервер
                if self._check_lm_studio_raw():
                    if not self._shadow_compare(
                        lambda texts: self._call_lm_studio_api(texts),
                        "lm_studio",
                    ):
                        logger.warning("🐦 Shadow Canary: LM Studio rejected. Continue scanning.")
                        continue
                    with self._mode_lock:
                        self.mode = "lm_studio"
                    logger.info(
                        "🌐 LM Studio обнаружен! Переключаюсь с ONNX → LM Studio. "
                        "Сканер остановлен."
                    )
                    return  # Успешное подключение — завершаем поток
                elif self._check_ollama():
                    if not self._shadow_compare(
                        lambda texts: self._call_ollama_api(texts),
                        "ollama",
                    ):
                        logger.warning("🐦 Shadow Canary: Ollama rejected. Continue scanning.")
                        continue
                    with self._mode_lock:
                        self.mode = "ollama"
                    logger.info(
                        "🌐 Ollama обнаружен! Переключаюсь с ONNX → Ollama. "
                        "Сканер остановлен."
                    )
                    return
                elif self._check_llama_cpp():
                    if not self._shadow_compare(
                        lambda texts: self._call_llama_cpp_api(texts),
                        "llama_cpp",
                    ):
                        logger.warning("🐦 Shadow Canary: llama.cpp rejected. Continue scanning.")
                        continue
                    with self._mode_lock:
                        self.mode = "llama_cpp"
                    logger.info(
                        "🦙 llama.cpp обнаружен! Переключаюсь с ONNX → llama.cpp."
                    )
                    # Запускаем реранкер (BGE-M3 на порту 8081)
                    try:
                        import asyncio

                        from src.providers.reranker.llama_runner import get_global_runner
                        runner = get_global_runner()
                        asyncio.run(runner.start_reranker())
                    except Exception as e:
                        logger.warning(f"Reranker autostart failed: {e}")
                    return

            except Exception as e:
                logger.debug(f"Сканер провайдера: ошибка проверки: {e}")

    def stop_scanner(self):
        """Останавливает фоновый сканер (вызывается при shutdown)."""
        self._scanner_stop.set()
        if self._scanner_thread is not None:
            self._scanner_thread.join(timeout=5.0)
            self._scanner_thread = None

    def _init_onnx(self):
        """Отложенная сборка ONNX/OpenVINO сессии с оптимизациями."""
        # DISABLE_ONNX_FALLBACK=true — полное отключение ONNX
        if os.getenv("DISABLE_ONNX_FALLBACK", "").lower() in ("true", "1", "yes"):
            logger.debug("ONNX fallback отключён через DISABLE_ONNX_FALLBACK")
            return
        if self._onnx_session is not None:
            self._onnx_last_used = time.time()
            return

        _provider = os.getenv("ONNX_PROVIDERS", "").lower()

        # ═══════════════════════════════════════════════════════════════
        # OpenVINO INT8 (рекомендуемый режим для Windows)
        # Даёт 37-52 ch/s на multilingual-e5-small INT8 (против 7-8 ch/s у ONNX)
        # ═══════════════════════════════════════════════════════════════
        # Загружаем OpenVINO только если явно указан провайдер.
        # Если _ov_compiled уже есть — не перезагружаем (re-entry guard).
        if _provider == "openvino":
            if getattr(self, '_ov_compiled', None) is None:
                self._init_openvino()
            else:
                self._onnx_last_used = time.time()
            # OpenVINO — штатный путь; ONNX Runtime fallback не нужен.
            return

        # ═══════════════════════════════════════════════════════════════
        # ONNX Runtime (INT8, backup)
        # Загружается ДАЖЕ если _ov_compiled уже есть (нужен как backup
        # при "Infer Request is busy" race condition).
        # ═══════════════════════════════════════════════════════════════
        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer

            logger.info(
                f"⚙️ Инициализация локального ONNX ядра из папки: {self.local_model_dir}"
            )
            if not self.local_model_dir.exists():
                raise FileNotFoundError(
                    f"Локальные веса ONNX не найдены в {self.local_model_dir}. Запустите download_model.py"
                )

            tokenizer_file = self.local_model_dir / "tokenizer.json"
            if not tokenizer_file.exists():
                raise FileNotFoundError(f"tokenizer.json не найден в {self.local_model_dir}")
            self._tokenizer = Tokenizer.from_file(str(tokenizer_file))
            self._max_embed_tokens = int(os.getenv("ONNX_MAX_LENGTH", "128"))
            self._tokenizer.enable_padding(pad_token="<pad>", pad_id=1, length=self._max_embed_tokens)
            self._tokenizer.enable_truncation(max_length=self._max_embed_tokens)

            # Определяем провайдеры ONNX:
            if _provider == "cpu":
                providers = ["CPUExecutionProvider"]
            elif _provider == "dml":
                providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
            else:
                providers = ["CPUExecutionProvider"]
                if "DmlExecutionProvider" in ort.get_available_providers():
                    providers.insert(0, "DmlExecutionProvider")

            # Ищем INT8 модель (model_quantized.onnx) или FP32 (model.onnx).
            # INT8 — штатный путь (~52 ch/s), FP32 — fallback.
            # Синхронно с _init_openvino.
            _model_dir_path = Path(self.local_model_dir)
            _int8_path = _model_dir_path / "model_quantized.onnx"
            _fp32_path = _model_dir_path / "model.onnx"
            if _int8_path.exists():
                _onnx_model_file = _int8_path
                logger.info(f"🔧 ONNX: загружаю INT8 модель {_int8_path}")
            elif _fp32_path.exists():
                _onnx_model_file = _fp32_path
                logger.info(f"🔧 ONNX: загружаю FP32 модель {_fp32_path}")
            else:
                raise FileNotFoundError(f"Модель не найдена: INT8={_int8_path}, FP32={_fp32_path}")

            import onnxruntime as _ort
            opts = _ort.SessionOptions()
            opts.enable_cpu_mem_arena = False
            opts.enable_mem_pattern = False
            opts.enable_mem_reuse = True
            # BASIC — не фузит граф, сохраняет parallelism (см. эксперементы)
            opts.graph_optimization_level = _ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            # 8 потоков — оптимум для Ryzen 5600 (18 ch/s, batch=4)
            opts.intra_op_num_threads = int(os.getenv("ONNX_INTRA_THREADS", "8"))
            opts.inter_op_num_threads = int(os.getenv("ONNX_INTER_THREADS", "1"))
            opts.execution_mode = _ort.ExecutionMode.ORT_SEQUENTIAL

            self._onnx_session = ort.InferenceSession(
                str(_onnx_model_file),
                sess_options=opts,
                providers=providers,
            )
            self._onnx_infer_lock = threading.Lock()
            self._onnx_input_names: List[str] = [
                inp.name for inp in self._onnx_session.get_inputs()
            ]
            self._onnx_last_used = time.time()
            logger.info(
                f"✅ ONNX движок запущен. Входы модели: {self._onnx_input_names}"
            )
        except Exception as e:
            logger.error(f"❌ Ошибка сборки ONNX: {e}", exc_info=True)
            with self._mode_lock:
                self.mode = "fallback"

    def _init_openvino(self):
        """Инициализация OpenVINO с INT8 моделью.

        Даёт 37-52 ch/s на multilingual-e5-small INT8 (Windows CPU).
        Ключевые оптимизации:
        - max_length=128 (Padding Trap fix)
        - dynamic batch shape
        - token_type_ids pre-bound нулями (для INT8 моделей с 3 входами)
        """
        # Re-entry guard: уже загружено
        if getattr(self, '_ov_compiled', None) is not None:
            self._onnx_last_used = time.time()
            return
        try:
            import openvino as ov
            from tokenizers import Tokenizer

            # Ищем INT8 модель (model_quantized.onnx) или FP32 (model.onnx).
            # INT8 — штатный путь (~52 ch/s), FP32 — fallback.
            # ORIGINAL from commit 0665a4b (Restore INT8).
            model_dir_path = Path(self.local_model_dir)
            int8_path = model_dir_path / "model_quantized.onnx"
            fp32_path = model_dir_path / "model.onnx"

            if int8_path.exists():
                model_file = int8_path
                logger.info(f"🔧 OpenVINO: загружаю INT8 модель {int8_path}")
            elif fp32_path.exists():
                model_file = fp32_path
                logger.info(f"🔧 OpenVINO: FP32 fallback {fp32_path}")
            else:
                raise FileNotFoundError(f"Модель не найдена в {model_dir_path}")

            tokenizer_file = model_dir_path / "tokenizer.json"
            if not tokenizer_file.exists():
                raise FileNotFoundError(f"tokenizer.json не найден в {model_dir_path}")

            # Токенизатор
            self._tokenizer = Tokenizer.from_file(str(tokenizer_file))
            self._max_embed_tokens = int(os.getenv("ONNX_MAX_LENGTH", "128"))
            self._tokenizer.enable_padding(pad_token="<pad>", pad_id=1, length=self._max_embed_tokens)
            self._tokenizer.enable_truncation(max_length=self._max_embed_tokens)

            # OpenVINO Core
            core = ov.Core()
            model = core.read_model(str(model_file))

            # Static reshape [1, 128] — для batch=1 (индивидуальные чанки)
            # Dynamic shapes вызывают kernel cache miss на Ryzen.
            for inp in model.inputs:
                model.reshape({inp.any_name: [1, 128]})

            # LATENCY — оптимально для batch=1 (12 ch/s на Ryzen 5600).
            # THROUGHPUT + streams создаёт overhead без выгоды для batch=1.
            compiled = core.compile_model(model, "CPU", config={
                "PERFORMANCE_HINT": "LATENCY",
                "INFERENCE_NUM_THREADS": "0",
            })
            self._ov_compiled = compiled

            # AsyncInferQueue — пул из N параллельных InferRequest.
            # Убирает bottleneck single-lock (см. P0-3 architecture review).
            # Увеличено с 4 до 8: при >2 concurrent embed_batch() старый pool_size=4
            # создавал очередь, где wait_all() ждёт чужие задачи. 8 — компромисс
            # между параллелизмом и footprint (8 InferRequest × 500MB ≈ стабильно).
            _ov_pool_size = int(os.getenv("OV_INFER_POOL_SIZE", "8"))
            self._ov_async_queue = ov.AsyncInferQueue(compiled, jobs=_ov_pool_size)

            # Variant B fix (P0-3): Lock сериализует конкурентные embed_batch()
            # на уровне start_async+wait_all+сбора результатов.
            # Причина: AsyncInferQueue.wait_all() ждёт ВСЕ задачи в очереди,
            # включая чужие — два потока с одним queue блокируют друг друга.
            # Параллелизм внутри одного вызова сохранён (jobs=4).
            self._ov_call_lock = threading.Lock()

            # Pre-bind token_type_ids = zeros в памяти C++ для ВСЕХ request в пуле.
            # INT8 модель имеет 3 входа, но tt всегда нули (код не использует —
            # Token Type Embeddings = 0 для всех токенов).
            # Это устраняет overhead на передачу tt из Python и Dynamic Shapes.
            self._ov_has_tt_bound = False
            try:
                tt_tensor = ov.Tensor(np.zeros((1, 128), dtype=np.int64))
                for _req in self._ov_async_queue:
                    _req.set_tensor("token_type_ids", tt_tensor)
                self._ov_has_tt_bound = True
            except Exception:
                pass  # FP32 модель без tt входа — ок

            # Callback для AsyncInferQueue: сохраняет результат в ЛОКАЛЬНЫЙ dict вызова.
            # Вызывается из потока OpenVINO (с GIL).
            # userdata = (original_index, local_results_dict) — полная изоляция вызовов,
            # никакого shared mutable state между конкурентными embed_batch().
            # (Fix: race condition audit 2026-07-18 — self._ov_results был общим на процесс,
            # concurrent вызовы с одинаковыми userdata=0..N перезаписывали друг друга.)
            def _ov_callback(request, userdata):
                idx, local_results = userdata
                out_tensor = request.get_output_tensor(0)
                local_results[idx] = out_tensor.data[0].copy()

            self._ov_async_queue.set_callback(_ov_callback)

            # Auto-detect: INT8 (model_quantized.onnx) имеет 3 входа и требует
            # token_type_ids. FP32 (model.onnx) имеет 2 входа и не требует.
            # Подача tt для INT8 даёт 11-15 ch/s, без tt → batch=0 → нули.
            # См. commit 0665a4b (Restore INT8), ЭКСПЕРИМЕНТ 2026-07-17.
            self._ov_has_token_type_ids = any(
                "token_type_ids" in inp.get_names()
                for inp in model.inputs
            )
            self._onnx_input_names = [
                inp.any_name for inp in model.inputs
                if inp.any_name != "token_type_ids"
            ]
            self._onnx_last_used = time.time()

            sz_mb = model_file.stat().st_size / (1024 * 1024)
            logger.info(
                f"✅ OpenVINO INT8 запущен! ({sz_mb:.0f}MB, "
                f"{self._max_embed_tokens}tok, "
                f"token_type_ids={self._ov_has_token_type_ids})"
            )

        except Exception as e:
            logger.error(f"❌ Ошибка инициализации OpenVINO: {e}", exc_info=True)
            with self._mode_lock:
                self.mode = "fallback"

    def _unload_onnx(self):
        """Выгружает ONNX модель из памяти для экономии RAM."""
        if self._onnx_session is not None:
            logger.info("🧹 Выгрузка ONNX модели (idle timeout)")
            self._onnx_session = None
            self._tokenizer = None
            import gc

            gc.collect()

    def _start_onnx_cleanup(self):
        """Фоновый поток: выгружает ONNX при долгом бездействии."""

        def _cleanup_loop():
            while not self._onnx_cleanup_stop.wait(60):
                if self._onnx_session is not None:
                    idle = time.time() - self._onnx_last_used
                    if idle > self._onnx_idle_timeout:
                        self._unload_onnx()

        self._onnx_cleanup_task = threading.Thread(
            target=_cleanup_loop,
            name="mscodebase-onnx-cleanup",
            daemon=True,
        )
        self._onnx_cleanup_task.start()

    def embed_batch(
        self, texts: List[str], is_query: bool = False
    ) -> List[List[float]]:
        """Пакетное получение векторов через активный провайдер.

        НИКОГДА не меняет mode. Если провайдер недоступен —
        возвращает нулевые векторы (режим не сбрасывается).
        """
        if not texts:
            return []

        with self._mode_lock:
            current_mode = self.mode

        # ═══ llama.cpp ═══
        if current_mode in ("llama_cpp", "unknown"):
            try:
                payload = {"input": texts}
                with httpx.Client(timeout=self.timeout) as client:
                    r = client.post(self.llama_cpp_url, json=payload)
                    if r.status_code == 200:
                        data = r.json().get("data", [])
                        if data:
                            data = sorted(data, key=lambda x: x.get("index", 0))
                            return [item["embedding"] for item in data]
                        else:
                            logger.warning(f"llama.cpp: 200 OK but пустой data, url={self.llama_cpp_url}")
                    else:
                        logger.warning(f"llama.cpp: HTTP {r.status_code}, url={self.llama_cpp_url}")
            except Exception as _exc:
                logger.warning(f"llama.cpp embed error for {self.llama_cpp_url}: {_exc}")
            # Если unknown — падаем дальше, если llama_cpp — заглушка
            if current_mode == "llama_cpp":
                logger.warning("llama.cpp не отвечает, возвращаю заглушки")
                return [[0.0] * self.embedding_dim for _ in texts]

        # ═══ LM Studio ═══
        if current_mode == "lm_studio":
            try:
                payload = {"model": self.model_name, "input": texts}
                with httpx.Client(timeout=self.timeout) as client:
                    r = client.post(self.lm_studio_url, json=payload)
                    if r.status_code == 200:
                        data = r.json().get("data", [])
                        if data:
                            data = sorted(data, key=lambda x: x.get("index", 0))
                            return [item["embedding"] for item in data]
            except Exception as _e:
                logger.warning(f"LM Studio embed error: {_e}")
            logger.warning("LM Studio не отвечает, возвращаю заглушки")
            return [[0.0] * self.embedding_dim for _ in texts]

        # ═══ ONNX-сервер ═══
        if current_mode == "onnx_server":
            try:
                payload = {"model": "bge-m3", "input": texts}
                with httpx.Client(timeout=self.timeout) as client:
                    r = client.post(self.onnx_server_url, json=payload)
                    if r.status_code == 200:
                        data = r.json().get("data", [])
                        if data:
                            data = sorted(data, key=lambda x: x.get("index", 0))
                            return [item["embedding"] for item in data]
            except Exception as _e:
                logger.warning(f"ONNX server embed error: {_e}")
            logger.warning("ONNX-сервер не отвечает, возвращаю заглушки")
            return [[0.0] * self.embedding_dim for _ in texts]

        # ═══ OpenVINO (INT8, ~350 ch/s) ═══
        if current_mode in ("unknown", "onnx") and getattr(self, '_ov_compiled', None) is not None:
            try:
                self._onnx_last_used = time.time()
                import numpy as np


                def _ensure_prefix(text: str, is_query: bool) -> str:
                    for prefix in ("query: ", "passage: "):
                        if text.startswith(prefix):
                            text = text[len(prefix):]
                            break
                    return f"{'query' if is_query else 'passage'}: {text}"

                prefixed = [_ensure_prefix(t, is_query) for t in texts]
                enc = self._tokenizer.encode_batch(prefixed, add_special_tokens=True)

                _dim = self.embedding_dim or 768
                _zero_vec = [0.0] * _dim
                results = [_zero_vec] * len(texts)

                # Валидные токенизированные тексты
                valid_indices = [i for i, e in enumerate(enc) if e and len(e.ids) > 0]
                if not valid_indices:
                    logger.warning(f"Токенизация вернула 0 результатов (batch={len(texts)})")
                    return results

                ids_all = np.array([enc[i].ids for i in valid_indices], dtype=np.int64)
                mask_all = np.array([enc[i].attention_mask for i in valid_indices], dtype=np.int64)
                # INT8 model_quantized.onnx подаёт token_type_ids только если
                # модель реально имеет этот вход.
                _ov_has_tt = getattr(self, "_ov_has_token_type_ids", False)
                if _ov_has_tt:
                    pass  # token_type_ids pre-bound нулями в _init_openvino (строки 695-703)

                # Variant B fix (P0-3): Lock вокруг submit+wait_all+collect.
                # Сериализует МЕЖДУ конкурентными embed_batch() вызовами,
                # сохраняя параллелизм ВНУТРИ одного вызова (jobs=4).
                # Локальный dict для результатов этого вызова — изоляция от concurrent вызовов.
                # userdata = (index, local_results) — callback пишет только сюда.
                with self._ov_call_lock:
                    local_results: dict[int, np.ndarray] = {}
                    for idx_in, i in enumerate(valid_indices):
                        feed = {"input_ids": ids_all[idx_in:idx_in+1], "attention_mask": mask_all[idx_in:idx_in+1]}
                        self._ov_async_queue.start_async(feed, (i, local_results))
                    self._ov_async_queue.wait_all()

                    # Собираем результаты и mean-pool
                    for idx_in, i in enumerate(valid_indices):
                        if i not in local_results:
                            logger.warning(
                                "OpenVINO async: чанк %d (index %d) не вернулся — "
                                "вектор будет нулевым.", idx_in, i
                            )
                            continue
                        token_emb = local_results[i]
                        mask_exp = np.expand_dims(mask_all[idx_in], -1).astype(float)
                        sum_emb = np.sum(token_emb * mask_exp, 0)
                        sum_mask = np.clip(np.sum(mask_exp, 0), a_min=1e-9, a_max=None)
                        results[i] = (sum_emb / sum_mask).tolist()

                return results

            except Exception as ov_err:
                logger.warning(f"OpenVINO infer error: {ov_err}, fallback to ONNX")
                # _ov_compiled и _ov_async_queue НЕ сбрасываем —
                # перезагрузка только усугубит при временном сбое.
                # fall through to ONNX Runtime

        # ═══ Локальный ONNX (E5-base, fallback) ═══
        # Если _init_onnx загрузила OpenVINO — перезапускаем embed
        if current_mode in ("unknown", "onnx"):
            self._init_onnx()
            # После _init_onnx мог загрузиться OpenVINO (через _init_openvino)
            # Перезапускаем embed с обновлённым current_mode
            if getattr(self, '_ov_compiled', None) is not None and self._ov_async_queue is not None:
                with self._mode_lock:
                    self.mode = "onnx"
                return self.embed_batch(texts, is_query=is_query)
            if self._onnx_session:
                # ─── Восстанавливаем mode (был сброшен recovery) ───
                with self._mode_lock:
                    if self.mode == "unknown":
                        self.mode = "onnx"
                self._onnx_last_used = time.time()
                import numpy as np

                def _ensure_prefix(text: str, is_query: bool) -> str:
                    for prefix in ("query: ", "passage: "):
                        if text.startswith(prefix):
                            text = text[len(prefix):]
                            break
                    return f"{'query' if is_query else 'passage'}: {text}"
                prefixed = [_ensure_prefix(t, is_query) for t in texts]
                enc = self._tokenizer.encode_batch(prefixed, add_special_tokens=True)
                ids = np.array([e.ids for e in enc], dtype=np.int64)
                mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
                inputs = {"input_ids": ids, "attention_mask": mask}
                onnx_inputs = self._onnx_input_names if hasattr(self, '_onnx_input_names') else []
                if "token_type_ids" in onnx_inputs:
                    _type_ids = np.array(
                        [getattr(e, "type_ids", None) or [0]*len(e.ids) for e in enc],
                        dtype=np.int64,
                    )
                    inputs["token_type_ids"] = _type_ids
                with self._onnx_infer_lock:
                    outputs = self._onnx_session.run(None, inputs)
                token_embeddings = outputs[0]
                del outputs
                if token_embeddings.shape[0] != len(texts):
                    raise ValueError(f"Expected {len(texts)} embeddings, got {token_embeddings.shape[0]}")
                input_mask_expanded = np.expand_dims(inputs["attention_mask"], -1).astype(float)
                sum_embeddings = np.sum(token_embeddings * input_mask_expanded, 1)
                sum_mask = np.clip(np.sum(input_mask_expanded, 1), a_min=1e-9, a_max=None)
                _emb = (sum_embeddings / sum_mask)
                _norm = np.linalg.norm(_emb, axis=1, keepdims=True)
                _norm = np.where(_norm == 0, 1e-12, _norm)
                return (_emb / _norm).tolist()

        # ═══ Ни один провайдер не сработал — критическая ошибка ═══
        raise RuntimeError(
            f"Embedder failed: mode={current_mode}, "
            f"ov_compiled={getattr(self, '_ov_compiled', None) is not None}, "
            f"onnx_session={self._onnx_session is not None}"
        )

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
                        max_keepalive_connections=2,
                        keepalive_expiry=30.0,
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

    def is_ready(self) -> bool:
        """Проверка готовности эмбеддера к работе.

        Ленивая: если ONNX-режим и сессия выгружена по idle-timeout,
        пытается перезагрузить модель (embed_batch всё равно это делает,
        но index_project_runner проверяет is_ready() до старта).
        """
        with self._mode_lock:
            if self.mode in ("unknown", "fallback"):
                return False
            if self.mode == "onnx":
                # Если ONNX_PROVIDERS=openvino — ждём именно OpenVINO
                if os.getenv("ONNX_PROVIDERS", "").lower() == "openvino":
                    if getattr(self, '_ov_compiled', None) is None:
                        try:
                            self._init_onnx()
                        except Exception as _e:
                            logger.debug(f"is_ready: ONNX reload failed: {_e}")
                            return False
                    return getattr(self, '_ov_compiled', None) is not None
                # Ленивая перезагрузка при idle-timeout выгрузке
                if self._onnx_session is None:
                    try:
                        self._init_onnx()
                    except Exception as _e:
                        logger.debug(f"is_ready: ONNX reload failed: {_e}")
                        return False
                return self._onnx_session is not None
            return self.mode in ("lm_studio", "llama_cpp", "ollama")

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

