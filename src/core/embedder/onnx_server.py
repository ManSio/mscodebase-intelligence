"""
ONNX HTTP Server — Singleton сервис для эмбеддингов.

Запускается on-demand (discover-or-launch pattern) через onnx_client.py.
Самоуничтожается через IDLE_TIMEOUT секунд без запросов.

Usage:
    python onnx_server.py [--port PORT] [--model MODEL_NAME]
"""
import argparse
import json
import logging
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

logger = logging.getLogger("mscodebase_server.onnx_server")

# Добавляем корень проекта в sys.path для импортов
# parents[3]: src/core/embedder/onnx_server.py → корень (репо или расширение Zed).
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

# Конфигурация
DEFAULT_PORT = int(os.getenv("ONNX_PORT", "9876"))
DEFAULT_MODEL = os.getenv("ONNX_MODEL", "multilingual-e5-small-int8")
IDLE_TIMEOUT = int(os.getenv("ONNX_IDLE_TIMEOUT", "600"))  # 10 минут

last_request_time = time.time()
_request_lock = threading.Lock()
_shutdown_event = threading.Event()


class OnnxHandler(BaseHTTPRequestHandler):
    """HTTP handler для эмбеддинг API."""

    def do_GET(self):
        if self.path == "/health":
            self._send_json({"status": "ok", "model": getattr(self.server, 'model_name', 'unknown')})
        elif self.path == "/ready":
            ready = hasattr(self.server, 'session') and self.server.session is not None
            self._send_json({"ready": ready})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        global last_request_time
        with _request_lock:
            last_request_time = time.time()

        content_length = int(self.headers.get('Content-Length', 0))
        if content_length == 0:
            self.send_response(400)
            self.end_headers()
            return

        raw_data = self.rfile.read(content_length)
        try:
            data = json.loads(raw_data.decode('utf-8'))
        except json.JSONDecodeError:
            self._send_json({"error": "Invalid JSON"}, 400)
            return

        try:
            if self.path == "/embed":
                text = data.get("text", "")
                if not text:
                    self._send_json({"error": "Missing 'text' field"}, 400)
                    return
                logger.info(f"[ONNX Server] Embedding: {text[:50]}")
                vector = self._embed_single(text)
                self._send_json({"vector": vector})

            elif self.path == "/embed_batch":
                texts = data.get("texts", [])
                if not texts or not isinstance(texts, list):
                    self._send_json({"error": "Missing or invalid 'texts' list"}, 400)
                    return
                vectors = self._embed_batch(texts)
                self._send_json({"vectors": vectors})

            else:
                self.send_response(404)
                self.end_headers()

        except Exception as e:
            logger.error(f"[ONNX Server] Error: {e}", exc_info=True)
            self._send_json({"error": str(e)}, 500)

    def _embed_single(self, text: str) -> List[float]:
        """Эмбеддинг одного текста."""
        session = self.server.session
        tokenizer = self.server.tokenizer
        input_names = self.server.input_names
        max_length = self.server.max_length

        # Токенизация через tokenizers (как в RemoteEmbedder)
        enc = tokenizer.encode(text, add_special_tokens=True)
        # Padding/truncation до max_length
        ids = enc.ids[:max_length]
        attention_mask = enc.attention_mask[:max_length]
        if len(ids) < max_length:
            pad_len = max_length - len(ids)
            ids = ids + [1] * pad_len  # pad_id = 1
            attention_mask = attention_mask + [0] * pad_len

        # Подготовка входов для ONNX
        seq_len = len(ids)
        onnx_inputs = {}
        for name in input_names:
            if name == "input_ids":
                onnx_inputs[name] = np.array([ids], dtype=np.int64)
            elif name == "attention_mask":
                onnx_inputs[name] = np.array([attention_mask], dtype=np.int64)
            elif name == "token_type_ids":
                onnx_inputs[name] = np.zeros((1, seq_len), dtype=np.int64)
            else:
                logger.warning(f"[ONNX Server] Unknown input: {name}, skipping")

        # Инференс
        outputs = session.run(None, onnx_inputs)

        # Mean pooling with attention mask (like remote_embedder)
        embeddings = outputs[0]  # (1, seq_len, hidden)
        attention_mask_arr = onnx_inputs["attention_mask"]  # (1, seq_len)

        # Mean pooling
        mask_expanded = np.expand_dims(attention_mask_arr, -1).astype(float)  # (1, seq_len, 1)
        sum_emb = np.sum(embeddings * mask_expanded, axis=1)  # (1, hidden)
        sum_mask = np.clip(np.sum(mask_expanded, axis=1), a_min=1e-9, a_max=None)  # (1, 1)
        vector = sum_emb / sum_mask  # (1, hidden)

        # Нормализация
        norm = np.linalg.norm(vector)
        if norm > 0:
            vector = vector / norm

        return vector[0].astype(np.float32).tolist()

    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Батч эмбеддинг."""
        session = self.server.session
        tokenizer = self.server.tokenizer
        input_names = self.server.input_names
        max_length = self.server.max_length

        # Токенизация батча через tokenizers
        encodings = tokenizer.encode_batch(texts, add_special_tokens=True)

        batch_ids = []
        batch_masks = []
        for enc in encodings:
            ids = enc.ids[:max_length]
            mask = enc.attention_mask[:max_length]
            if len(ids) < max_length:
                pad_len = max_length - len(ids)
                ids = ids + [1] * pad_len  # pad_id = 1
                mask = mask + [0] * pad_len
            batch_ids.append(ids)
            batch_masks.append(mask)

        batch_array = np.array(batch_ids, dtype=np.int64)
        mask_array = np.array(batch_masks, dtype=np.int64)
        batch_size = len(batch_ids)
        seq_len = batch_array.shape[1]
        onnx_inputs = {}
        for name in input_names:
            if name == "input_ids":
                onnx_inputs[name] = batch_array
            elif name == "attention_mask":
                onnx_inputs[name] = mask_array
            elif name == "token_type_ids":
                onnx_inputs[name] = np.zeros((batch_size, seq_len), dtype=np.int64)
            else:
                logger.warning(f"[ONNX Server] Unknown input: {name}, skipping")

        outputs = session.run(None, onnx_inputs)
        embeddings = outputs[0]  # (batch, seq_len, hidden)

        # Mean pooling with attention mask (like remote_embedder)
        attention_mask = onnx_inputs["attention_mask"]  # (batch, seq_len)

        mask_expanded = np.expand_dims(attention_mask, -1).astype(float)
        sum_emb = np.sum(embeddings * mask_expanded, axis=1)
        sum_mask = np.clip(np.sum(mask_expanded, axis=1), a_min=1e-9, a_max=None)
        vectors = sum_emb / sum_mask

        # Нормализация
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        vectors = vectors / np.maximum(norms, 1e-12)

        return vectors.astype(np.float32).tolist()

    def _send_json(self, data: Dict[str, Any], status: int = 200):
        response = json.dumps(data).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format, *args):
        # Отключаем логи в stdout (важно для MCP stdio transport)
        pass


def select_onnx_providers(policy: str, available: List[str]) -> List[str]:
    """Выбор ONNX execution providers по политике MSCODEBASE_ONNX_PROVIDER.

    Args:
        policy: "auto" (default) | "cpu" | "dml" | "cuda"
        available: список доступных провайдеров (ort.get_available_providers()).

    Returns:
        Список провайдеров для InferenceSession (порядок = приоритет).
        CPU всегда в конце как fallback.
    """
    _policy = (policy or "auto").strip().lower()
    _available = set(available or [])
    providers = ["CPUExecutionProvider"]

    if _policy == "cpu":
        pass  # CPU only
    elif _policy == "dml":
        if "DmlExecutionProvider" in _available:
            providers.insert(0, "DmlExecutionProvider")
        else:
            logger.warning("[ONNX Server] MSCODEBASE_ONNX_PROVIDER=dml, но DirectML недоступен — fallback на CPU")
    elif _policy == "cuda":
        if "CUDAExecutionProvider" in _available:
            providers.insert(0, "CUDAExecutionProvider")
        else:
            logger.warning("[ONNX Server] MSCODEBASE_ONNX_PROVIDER=cuda, но CUDA недоступен — fallback на CPU")
    else:  # auto (default)
        if "DmlExecutionProvider" in _available:
            providers.insert(0, "DmlExecutionProvider")

    logger.info(f"[ONNX Server] Provider policy={_policy} → {providers}")
    return providers


def load_model(model_name: str):
    """Загружает ONNX модель и токенизатор."""
    import onnxruntime as ort
    from tokenizers import Tokenizer

    # Пути к модели (проверяем несколько вариантов)
    search_paths = [
        PROJECT_ROOT / "models" / model_name,
        PROJECT_ROOT / ".codebase_models" / "onnx" / model_name,
        Path.home() / ".cache" / "mscodebase" / "models" / ".codebase_models" / "onnx" / model_name,
    ]
    # Также проверяем корень расширения Zed: PROJECT_ROOT уже указывает
    # на корень (репо или расширение), см. search_paths[1].
    ext_dir = Path(__file__).resolve().parent.parent.parent.parent
    if ext_dir.exists():
        search_paths.insert(0, ext_dir / ".codebase_models" / "onnx" / model_name)

    models_dir = None
    for p in search_paths:
        if p.exists():
            models_dir = p
            break

    if models_dir is None:
        raise FileNotFoundError(f"Model directory not found for: {model_name}")

    onnx_path = models_dir / "model_quantized.onnx"
    if not onnx_path.exists():
        onnx_path = models_dir / "model.onnx"

    tokenizer_path = models_dir / "tokenizer.json"

    if not onnx_path.exists():
        raise FileNotFoundError(f"ONNX model not found: {onnx_path} in {models_dir}")
    if not tokenizer_path.exists():
        raise FileNotFoundError(f"Tokenizer not found: {tokenizer_path}")

    # Загружаем токенизатор
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    tokenizer.enable_padding(pad_token="<pad>", pad_id=1, length=512)
    tokenizer.enable_truncation(max_length=512)

    # Настройка ONNX Runtime
    opts = ort.SessionOptions()
    opts.enable_cpu_mem_arena = False
    opts.enable_mem_pattern = False
    opts.enable_mem_reuse = True
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    opts.intra_op_num_threads = int(os.getenv("ONNX_INTRA_THREADS", "8"))
    opts.inter_op_num_threads = int(os.getenv("ONNX_INTER_THREADS", "1"))
    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL

    # Провайдеры (WIN-11: политика через select_onnx_providers, см. функцию выше)
    _provider_policy = os.getenv("MSCODEBASE_ONNX_PROVIDER", "auto")
    providers = select_onnx_providers(_provider_policy, ort.get_available_providers())

    session = ort.InferenceSession(str(onnx_path), sess_options=opts, providers=providers)
    input_names = [inp.name for inp in session.get_inputs()]

    logger.info(f"[ONNX Server] Model loaded: {onnx_path}")
    logger.info(f"[ONNX Server] Inputs: {input_names}")
    logger.info(f"[ONNX Server] Providers: {session.get_providers()}")

    return session, tokenizer, input_names


def idle_killer():
    """Фоновый поток: убивает сервер при бездействии."""
    global last_request_time
    while not _shutdown_event.is_set():
        time.sleep(30)
        with _request_lock:
            if time.time() - last_request_time > IDLE_TIMEOUT:
                logger.info(f"[ONNX Server] Idle timeout ({IDLE_TIMEOUT}s), shutting down...")
                _shutdown_event.set()
                os._exit(0)


def run_server(port: int, model_name: str):
    """Запуск HTTP сервера."""
    # Загружаем модель при старте
    session, tokenizer, input_names = load_model(model_name)

    # Создаём сервер
    server = HTTPServer(('127.0.0.1', port), OnnxHandler)
    server.model_name = model_name
    server.session = session
    server.tokenizer = tokenizer
    server.input_names = input_names
    server.max_length = 512

    # Запускаем idle killer
    threading.Thread(target=idle_killer, daemon=True).start()

    logger.info(f"[ONNX Server] Running on http://127.0.0.1:{port}")
    logger.info(f"[ONNX Server] Idle timeout: {IDLE_TIMEOUT}s")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        logger.info("[ONNX Server] Stopped")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ONNX Embedding Server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to listen on")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="Model name (directory in models/)")
    args = parser.parse_args()

    run_server(args.port, args.model)
