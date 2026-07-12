"""
MSCodeBase Intelligence - Универсальный адаптивный Эмбеддер (RemoteEmbedder)
Размещается в src/core/remote_embedder.py
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from src.core.config import get_config

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
        config = get_config()

        self.host = host or config.embedding.lm_studio_host
        self.port = port or config.embedding.lm_studio_port
        self.timeout = timeout or config.performance.embedding_timeout
        self.lm_studio_url = f"http://{self.host}:{self.port}/v1/embeddings"
        self.model_name = config.embedding.model_name

        self._breaker = breaker
        self._breaker_fallback = {
            "status": "fallback",
            "message": "LM Studio breaker open",
        }
        self.embedding_dim = config.embedding.embedding_dimension

        # ONNX Server (общий для всех проектов, через HTTP)
        self.onnx_server_port = int(os.getenv("ONNX_SERVER_PORT", "1235"))
        self.onnx_server_host = os.getenv("ONNX_SERVER_HOST", "127.0.0.1")
        self.onnx_server_url = (
            f"http://{self.onnx_server_host}:{self.onnx_server_port}/v1/embeddings"
        )
        self._onnx_server_process: Optional[subprocess.Popen] = None

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
        Checks multiple locations: ext_root, project_root, shared cache.

        Memory-safe: uses onnx.shape_inference (lightweight) instead of
        creating a full InferenceSession which loads 500+ MB unnecessarily.
        """
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
                    self._model_name = subdir.name
                    sz = model_file.stat().st_size / (1024 * 1024)
                    # Lightweight dimension detection: onnx protobuf metadata,
                    # NOT full InferenceSession (saves ~544 MB peak).
                    dim = self._lightweight_onnx_dim(model_file)
                    dim_str = f"{dim}dim" if dim else "dim?"
                    logger.info(
                        f"ONNX model: {subdir.name} ({dim_str}, {sz:.0f}MB) — no InferenceSession created"
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
        except Exception:
            try:
                # Известные модели: infer by name
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
                pass
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
                    self._preferred_mode = "llama_cpp"
                logger.info("🦙 Preload: найден llama.cpp, ONNX предзагрузка отменена")
                # Запускаем реранкер (BGE-M3 на порту 8081)
                try:
                    import asyncio
                    from src.core.llama_runner import get_global_runner
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

    def _start_onnx_server_subprocess(self) -> bool:
        """Запускает ONNX-сервер как отдельный процесс.

        Embedder (bge-m3) + reranker (bge-reranker-v2-m3) оба в подпроцессе.
        MCP-процесс НЕ загружает ONNX-модели (INC-6BCB-MEM).
        """
        try:
            server_script = Path(__file__).resolve().parent / "onnx_server.py"
            if not server_script.exists():
                logger.error(f"ONNX сервер не найден: {server_script}")
                return False

            cmd = [
                sys.executable,
                str(server_script),
                f"--port={self.onnx_server_port}",
                f"--host={self.onnx_server_host}",
                f"--model-dir={self.local_model_dir}",
            ]

            # Добавляем reranker dir, если модель найдена
            reranker_dir = self._find_reranker_dir()
            if reranker_dir:
                cmd.append(f"--reranker-dir={reranker_dir}")
                logger.info(f"📎 Reranker модель в подпроцесс: {reranker_dir}")

            self._onnx_server_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW
                if sys.platform == "win32"
                else 0,
            )
            logger.info(f"🚀 ONNX сервер запущен (PID {self._onnx_server_process.pid})")
            return True
        except Exception as e:
            logger.error(f"Не удалось запустить ONNX сервер: {e}")
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
            # ═══ E5-base ONNX (in-process, без внешних процессов) ═══
                # Пытаемся сразу загрузить ONNX. Не ждём llama.cpp — он упразднён.
                _provider = os.getenv("EMBEDDING_PROVIDER", "e5_onnx")
                if _provider in ("e5_onnx", "auto", ""):
                    logger.info("🔌 E5-base ONNX: инициализация локального эмбеддера...")
                    self._init_onnx()
                    if self._onnx_session:
                        with self._mode_lock:
                            self.mode = "onnx"
                            self._preferred_mode = "onnx"
                        logger.info("✅ E5-base ONNX запущен! (265MB, 768dim, CPU)")
                        return
                    else:
                        logger.warning("E5-base ONNX не загрузился, пробую другие провайдеры...")

                # ═══ LM Studio (fallback) ═══
                if self._check_lm_studio_raw():
                    with self._mode_lock:
                        self.mode = "lm_studio"
                        self._preferred_mode = "lm_studio"
                    logger.info("✅ LM Studio доступен (fallback).")
                    return

                # ═══ Ollama (fallback) ═══
                if os.getenv("EMBEDDING_PROVIDER") == "ollama":
                    if self._check_ollama():
                        with self._mode_lock:
                            self.mode = "ollama"
                            self._preferred_mode = "ollama"
                        logger.info("⚠️ Переключаюсь на Ollama.")
                        return

                # ═══ ONNX — последняя попытка ═══
                self._init_onnx()
                if self._onnx_session:
                    with self._mode_lock:
                        self.mode = "onnx"
                        self._preferred_mode = "onnx"
                    logger.info("✅ E5-base ONNX (повторная попытка) — успех.")
                    return

                with self._mode_lock:
                    self.mode = "fallback"
                logger.error("❌ НЕ УДАЛОСЬ загрузить E5-base ONNX. Режим fallback.")
        except Exception as e:
            logger.debug(f"_init_provider_async: {e}")
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

                # llama.cpp — стабилен, не трогаем
                if current == "llama_cpp":
                    logger.debug("llama.cpp стабилен. Сканер завершает работу.")
                    break

                # current == "onnx" или "fallback" — ищем внешний провайдер
                # Используем _raw, чтобы CircuitBreaker не кэшировал недоступный сервер
                if self._check_lm_studio_raw():
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
                    return
                elif self._check_llama_cpp():
                    with self._mode_lock:
                        self.mode = "llama_cpp"
                        self._preferred_mode = "llama_cpp"
                    logger.info(
                        "🦙 llama.cpp обнаружен! Переключаюсь с ONNX → llama.cpp."
                    )
                    # Запускаем реранкер (BGE-M3 на порту 8081)
                    try:
                        import asyncio
                        from src.core.llama_runner import get_global_runner
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
        """Отложенная сборка ONNX сессии с оптимизациями памяти."""
        # DISABLE_ONNX_FALLBACK=true — полное отключение ONNX
        if os.getenv("DISABLE_ONNX_FALLBACK", "").lower() in ("true", "1", "yes"):
            logger.debug("ONNX fallback отключён через DISABLE_ONNX_FALLBACK")
            return
        if self._onnx_session is not None:
            self._onnx_last_used = time.time()
            return
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
            self._tokenizer.enable_padding(pad_token="<pad>", pad_id=1)
            self._tokenizer.enable_truncation(max_length=512)

            providers = ["CPUExecutionProvider"]
            if "DmlExecutionProvider" in ort.get_available_providers():
                providers.insert(0, "DmlExecutionProvider")

            # Оптимизации памяти и потоков
            import onnxruntime as _ort

            opts = _ort.SessionOptions()
            opts.enable_cpu_mem_arena = False
            opts.enable_mem_pattern = False
            opts.enable_mem_reuse = True
            opts.intra_op_num_threads = 2
            opts.inter_op_num_threads = 1
            opts.graph_optimization_level = _ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            opts.execution_mode = _ort.ExecutionMode.ORT_SEQUENTIAL

            self._onnx_session = ort.InferenceSession(
                str(self.local_model_dir / "model.onnx"),
                sess_options=opts,
                providers=providers,
            )
            self._onnx_last_used = time.time()
            logger.info("✅ Локальный ONNX движок успешно запущен и готов к расчетам.")
        except Exception as e:
            logger.error(f"❌ Ошибка сборки локального ONNX-детектора: {e}")
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
            except Exception:
                pass
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
            except Exception:
                pass
            logger.warning("ONNX-сервер не отвечает, возвращаю заглушки")
            return [[0.0] * self.embedding_dim for _ in texts]

        # ═══ Локальный ONNX (E5-base, in-process) ═══
        if current_mode in ("unknown", "onnx"):
            self._init_onnx()
            if self._onnx_session:
                try:
                    self._onnx_last_used = time.time()
                    import numpy as np
                    
                    # E5-base требует префиксы: query: / passage:
                    prefixed = []
                    for t in texts:
                        if is_query and not t.startswith("query: "):
                            prefixed.append(f"query: {t}")
                        elif not is_query and not t.startswith("passage: "):
                            prefixed.append(f"passage: {t}")
                        else:
                            prefixed.append(t)
                    
                    enc = self._tokenizer.encode_batch(prefixed, add_special_tokens=True)
                    ids = np.array([e.ids for e in enc], dtype=np.int64)
                    mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
                    inputs = {"input_ids": ids, "attention_mask": mask}
                    if enc and hasattr(enc[0], "type_ids") and any(e.type_ids for e in enc):
                        inputs["token_type_ids"] = np.array(
                            [e.type_ids for e in enc], dtype=np.int64
                        )
                    outputs = self._onnx_session.run(None, inputs)
                    token_embeddings = outputs[0]
                    if len(token_embeddings) != 1 and token_embeddings.shape[0] != len(texts):
                        raise ValueError(f"Expected {len(texts)} embeddings, got {token_embeddings.shape[0]}")
                    input_mask_expanded = np.expand_dims(inputs["attention_mask"], -1).astype(float)
                    sum_embeddings = np.sum(token_embeddings * input_mask_expanded, 1)
                    sum_mask = np.clip(np.sum(input_mask_expanded, 1), a_min=1e-9, a_max=None)
                    return (sum_embeddings / sum_mask).tolist()
                except Exception as batch_err:
                    logger.debug(f"ONNX batch failed ({batch_err}), пробую по одному")
                    try:
                        import numpy as np
                        embeddings = []
                        for text in texts:
                            t = text
                            if is_query and not t.startswith("query: "):
                                t = f"query: {t}"
                            elif not is_query and not t.startswith("passage: "):
                                t = f"passage: {t}"
                            enc_single = self._tokenizer.encode_batch([t], add_special_tokens=True)
                            inp = {
                                "input_ids": np.array([enc_single[0].ids], dtype=np.int64),
                                "attention_mask": np.array([enc_single[0].attention_mask], dtype=np.int64),
                            }
                            out = self._onnx_session.run(None, inp)
                            token_emb = out[0]
                            mask_exp = np.expand_dims(inp["attention_mask"], -1).astype(float)
                            sum_emb = np.sum(token_emb * mask_exp, 1)
                            sum_mask = np.clip(np.sum(mask_exp, 1), a_min=1e-9, a_max=None)
                            embeddings.append((sum_emb / sum_mask).tolist()[0])
                        return embeddings
                    except Exception:
                        pass
            logger.warning("ONNX Runtime недоступен, возвращаю заглушки")
            return [[0.0] * self.embedding_dim for _ in texts]

        # ═══ Заглушка ═══
        logger.critical(f"Неизвестный режим {current_mode}, возвращаю заглушки")
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
