"""
ONNX Embedding Server — общий HTTP-сервер для эмбеддингов.
Загружает bge-m3 ОДИН раз, обслуживает все MCP-процессы.

API (совместим с LM Studio):
  POST /v1/embeddings  →  {"data": [{"embedding": [...], "index": 0}, ...]}
  GET  /v1/models      →  {"data": [{"id": "bge-m3"}]}
  GET  /health         →  {"status": "ok"}
"""

import argparse
import json
import logging
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import onnxruntime as ort
from transformers import AutoTokenizer

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("onnx_server")

# Глобальные переменные (загружаются один раз при старте)
_model_dir: Path = (
    Path(__file__).resolve().parent.parent.parent
    / ".codebase_models"
    / "onnx"
    / "bge-m3"
)
_models_cache: dict = {}
_session = None
_tokenizer = None
_start_time = time.time()


def init_model():
    """Загружает модель ONNX + токенизатор (один раз при старте)."""
    global _model_dir, _session, _tokenizer

    model_path = _model_dir / "model.onnx"
    model_parent = _model_dir

    if not model_path.exists():
        # Ищем в других местах
        alt_paths = [
            Path.home()
            / ".cache"
            / "mscodebase"
            / "models"
            / ".codebase_models"
            / "onnx"
            / "bge-m3"
            / "model.onnx",
            _model_dir.parent.parent / "bge-m3" / "model.onnx",
        ]
        for alt in alt_paths:
            if alt.exists():
                model_path = alt
                model_parent = alt.parent
                break
        else:
            raise FileNotFoundError(
                f"ONNX модель не найдена. Установите через install.py. "
                f"Искал: {_model_dir / 'model.onnx'}"
            )

    logger.info(
        f"⏳ Загрузка модели: {model_path} ({model_path.stat().st_size / 1024 / 1024:.0f} MB)"
    )

    _tokenizer = AutoTokenizer.from_pretrained(str(model_parent))

    opts = ort.SessionOptions()
    opts.enable_cpu_mem_arena = False
    opts.intra_op_num_threads = 2
    opts.inter_op_num_threads = 1
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL

    _session = ort.InferenceSession(
        str(onnx_path), sess_options=opts, providers=["CPUExecutionProvider"]
    )

    dim = _session.get_outputs()[0].shape[-1]
    logger.info(
        f"✅ ONNX сервер готов: bge-m3 ({dim}dim, {onnx_path.stat().st_size / 1024 / 1024:.0f} MB)"
    )


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Возвращает эмбеддинги для списка текстов."""
    encoded = _tokenizer(
        texts,
        padding=True,
        truncation=True,
        max_length=2048,
        return_tensors="np",
    )
    outputs = _session.run(
        None,
        {
            "input_ids": encoded["input_ids"].astype(np.int64),
            "attention_mask": encoded["attention_mask"].astype(np.int64),
        },
    )

    embeddings = outputs[0]
    input_mask_expanded = np.expand_dims(encoded["attention_mask"], -1).astype(float)
    sum_embeddings = np.sum(embeddings * input_mask_expanded, 1)
    sum_mask = np.clip(np.sum(input_mask_expanded, 1), a_min=1e-9, a_max=None)
    pooled = (sum_embeddings / sum_mask).tolist()
    return pooled


class EmbeddingHandler(BaseHTTPRequestHandler):
    """HTTP-handler для эмбеддингов."""

    def _send_json(self, data: dict, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/v1/models":
            self._send_json(
                {
                    "data": [{"id": "bge-m3", "object": "model"}],
                }
            )
        elif path == "/health":
            self._send_json(
                {
                    "status": "ok",
                    "uptime_sec": int(time.time() - _start_time),
                    "model": "bge-m3",
                }
            )
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/v1/embeddings":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length))
                texts = body.get("input", [])
                if isinstance(texts, str):
                    texts = [texts]

                t0 = time.time()
                embeddings = embed_texts(texts)
                dt = (time.time() - t0) * 1000

                result = [
                    {"object": "embedding", "index": i, "embedding": emb}
                    for i, emb in enumerate(embeddings)
                ]
                self._send_json(
                    {
                        "data": result,
                        "model": "bge-m3",
                        "usage": {"prompt_tokens": 0, "total_tokens": 0},
                    }
                )

            except Exception as e:
                logger.error(f"Embedding error: {e}")
                self._send_json({"error": str(e)}, 500)
        else:
            self._send_json({"error": "not found"}, 404)

    def log_message(self, format, *args):
        logger.debug(f"{self.client_address[0]} - {format % args}")


def main():
    parser = argparse.ArgumentParser(description="ONNX Embedding Server")
    parser.add_argument("--port", type=int, default=1235, help="Port (default: 1235)")
    parser.add_argument(
        "--host", type=str, default="127.0.0.1", help="Host (default: 127.0.0.1)"
    )
    args = parser.parse_args()

    init_model()

    server = HTTPServer((args.host, args.port), EmbeddingHandler)
    logger.info(f"🚀 ONNX сервер запущен на http://{args.host}:{args.port}")
    logger.info(f"   POST /v1/embeddings — эмбеддинги")
    logger.info(f"   GET  /v1/models     — список моделей")
    logger.info(f"   GET  /health        — проверка здоровья")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("🛑 ONNX сервер остановлен")
        server.server_close()


if __name__ == "__main__":
    main()
