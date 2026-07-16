"""
ONNX Inference Server — общий HTTP-сервер для эмбеддингов и реранкинга.
Загружает модели ОДИН раз в подпроцессе, обслуживает все MCP-процессы.

API:
  POST /v1/embeddings  →  {"data": [{"embedding": [...], "index": 0}, ...]}
  POST /v1/rerank      →  {"scores": [0.95, 0.12, ...]}
  GET  /v1/models      →  {"data": [{"id": "bge-m3"}, {"id": "bge-reranker-v2-m3"}]}
  GET  /health         →  {"status": "ok"}

Memory design:
  - Embedder (bge-m3) и reranker (bge-reranker-v2-m3) живут в ПОДПРОЦЕССЕ.
  - MCP-процесс НЕ загружает ONNX-модели, только HTTP-клиенты.
  - GC форсируется после каждого запроса для контроля RSS.
  - enable_cpu_mem_arena = False — без предвыделенного пула.
"""

import argparse
import gc
import json
import logging
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

__all__ = [
    "init_embedder",
    "embed_texts",
    "init_reranker",
    "rerank",
    "InferenceHandler",
    "main",
]
# Константы токенизации для BGE-M3 (XLM-Roberta)
_TOKENIZER_PAD_ID = 1      # <pad>
_TOKENIZER_CLS_ID = 0      # <s>
_TOKENIZER_SEP_ID = 2      # </s>
_TOKENIZER_UNK_ID = 3      # <unk>
_MAX_SEQ_LEN = 2048        # BGE-M3 поддерживает до 8192, но 2048 достаточно

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("onnx_server")

_start_time = time.time()

# ─── Embedder (bge-m3) ────────────────────────────────────────────
_embed_session = None
_embed_tokenizer = None

# ─── Reranker (bge-reranker-v2-m3) ────────────────────────────────
_reranker_session = None
_reranker_tokenizer = None


def _find_model(subdir_name: str) -> Optional[Path]:
    """Ищет model.onnx в стандартных locations."""
    roots = [
        Path(__file__).resolve().parent.parent.parent / ".codebase_models" / "onnx",
        Path.home() / ".cache" / "mscodebase" / "models" / ".codebase_models" / "onnx",
    ]
    for root in roots:
        p = root / subdir_name / "model.onnx"
        if p.exists():
            return p
    return None


def _make_session_opts() -> ort.SessionOptions:
    """Единые оптимизации памяти для всех ONNX-сессий."""
    opts = ort.SessionOptions()
    opts.enable_cpu_mem_arena = False   # без предвыделенного пула RAM
    import multiprocessing
    cores = multiprocessing.cpu_count()
    opts.intra_op_num_threads = max(2, min(cores // 2, 8))  # половина ядер, макс 8
    opts.inter_op_num_threads = 1
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    return opts


# ═══════════════════════════════════════════════════════════════════
# Embedder
# ═══════════════════════════════════════════════════════════════════

def init_embedder(model_dir_override: Optional[str] = None):
    """Загружает bge-m3 — один раз при старте."""
    global _embed_session, _embed_tokenizer

    if model_dir_override:
        model_path = Path(model_dir_override) / "model.onnx"
    else:
        found = _find_model("bge-m3")
        if not found:
            raise FileNotFoundError("bge-m3 embedder not found. Run install.py first.")
        model_path = found

    model_dir = model_path.parent
    logger.info(f"⏳ Загрузка embedder: {model_path} ({model_path.stat().st_size / 1024 / 1024:.0f} MB)")

    _embed_tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
    _embed_tokenizer.enable_padding(pad_token="<pad>", pad_id=_TOKENIZER_PAD_ID)
    _embed_tokenizer.enable_truncation(max_length=_MAX_SEQ_LEN)
    _embed_session = ort.InferenceSession(
        str(model_path),
        sess_options=_make_session_opts(),
        providers=["CPUExecutionProvider"],
    )
    dim = _embed_session.get_outputs()[0].shape[-1]
    logger.info(f"✅ Embedder готов: {model_dir.name} ({dim}dim, {model_path.stat().st_size / 1024 / 1024:.0f} MB)")


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Возвращает эмбеддинги для списка текстов.

    Использует tokenizers.Tokenizer напрямую (НЕ AutoTokenizer) —
    без обращений к huggingface.co и без зависаний на Windows.
    """
    encoded = _embed_tokenizer.encode_batch(texts, add_special_tokens=True)
    ids = np.array([e.ids for e in encoded], dtype=np.int64)
    mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
    outputs = _embed_session.run(None, {
        "input_ids": ids,
        "attention_mask": mask,
    })
    embeddings = outputs[0]
    mask_f = np.expand_dims(mask, -1).astype(float)
    sum_emb = np.sum(embeddings * mask_f, 1)
    sum_mask = np.clip(np.sum(mask_f, 1), a_min=1e-9, a_max=None)
    return (sum_emb / sum_mask).tolist()


# ═══════════════════════════════════════════════════════════════════
# Reranker
# ═══════════════════════════════════════════════════════════════════

def init_reranker(model_dir_override: Optional[str] = None):
    """Загружает bge-reranker-v2-m3 — один раз при старте (опционально)."""
    global _reranker_session, _reranker_tokenizer

    if model_dir_override:
        model_path = Path(model_dir_override) / "model.onnx"
    else:
        model_path = None
        for slug in ["reranker-bge-reranker-v2-m3", "bge-reranker-v2-m3"]:
            found = _find_model(slug)
            if found:
                model_path = found
                break
        if not model_path:
            logger.info("Reranker model not found — rerank endpoint disabled")
            return

    model_dir = model_path.parent
    logger.info(f"⏳ Загрузка reranker: {model_path} ({model_path.stat().st_size / 1024 / 1024:.0f} MB)")

    _reranker_tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
    _reranker_tokenizer.enable_padding(pad_token="<pad>", pad_id=_TOKENIZER_PAD_ID)
    _reranker_tokenizer.enable_truncation(max_length=512)
    _reranker_session = ort.InferenceSession(
        str(model_path),
        sess_options=_make_session_opts(),
        providers=["CPUExecutionProvider"],
    )
    logger.info(f"✅ Reranker готов: {model_dir.name} ({model_path.stat().st_size / 1024 / 1024:.0f} MB)")


def rerank(query: str, passages: list[str]) -> list[float]:
    """Cross-encoder reranking: query vs each passage, returns scores [0..1]."""
    pairs = [[query, p] for p in passages]
    encoded = _reranker_tokenizer.encode_batch(pairs, add_special_tokens=True)
    ids = np.array([e.ids for e in encoded], dtype=np.int64)
    mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
    outputs = _reranker_session.run(None, {
        "input_ids": ids,
        "attention_mask": mask,
    })
    logits = outputs[0].flatten()
    return (1.0 / (1.0 + np.exp(-logits))).tolist()


# ═══════════════════════════════════════════════════════════════════
# HTTP Handler
# ═══════════════════════════════════════════════════════════════════

class InferenceHandler(BaseHTTPRequestHandler):
    """HTTP-handler для эмбеддингов и реранкинга."""

    # Разрешаем CORS только для localhost-запросов (защита от "Bleeding Llama"-класса)
    _CORS_ORIGIN = "http://127.0.0.1"

    def _send_json(self, data: dict, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", self._CORS_ORIGIN)
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", self._CORS_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/v1/models":
            models = [{"id": "bge-m3", "object": "model"}]
            if _reranker_session is not None:
                models.append({"id": "bge-reranker-v2-m3", "object": "model"})
            self._send_json({"data": models})
        elif path == "/health":
            self._send_json({
                "status": "ok",
                "uptime_sec": int(time.time() - _start_time),
                "embedder": "bge-m3",
                "reranker": _reranker_session is not None,
            })
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            raw_length = self.headers.get("Content-Length", "")
            if not raw_length or not raw_length.isdigit() or int(raw_length) <= 0:
                self._send_json({"error": "missing or invalid Content-Length"}, 411)
                return
            length = int(raw_length)
            body = json.loads(self.rfile.read(length))
        except Exception as e:
            self._send_json({"error": f"invalid request: {e}"}, 400)
            return

        if path == "/v1/embeddings":
            self._handle_embed(body)
        elif path == "/v1/rerank":
            self._handle_rerank(body)
        else:
            self._send_json({"error": "not found"}, 404)

        # GC после каждого запроса для контроля RSS
        gc.collect()

    def _handle_embed(self, body: dict):
        try:
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
            self._send_json({
                "data": result,
                "model": "bge-m3",
                "usage": {"prompt_tokens": 0, "total_tokens": 0, "inference_ms": round(dt, 1)},
            })
        except Exception as e:
            logger.error(f"Embedding error: {e}")
            self._send_json({"error": str(e)}, 500)

    def _handle_rerank(self, body: dict):
        try:
            query = body.get("query", "")
            passages = body.get("passages", [])
            if not query or not passages:
                self._send_json({"error": "query and passages are required"}, 400)
                return
            t0 = time.time()
            scores = rerank(query, passages)
            dt = (time.time() - t0) * 1000
            self._send_json({
                "scores": scores,
                "model": "bge-reranker-v2-m3",
                "usage": {"inference_ms": round(dt, 1)},
            })
        except Exception as e:
            logger.error(f"Rerank error: {e}")
            self._send_json({"error": str(e)}, 500)

    def log_message(self, format, *args):
        logger.debug(f"{self.client_address[0]} - {format % args}")


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="ONNX Inference Server")
    parser.add_argument("--port", type=int, default=1235)
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--model-dir", type=str, default=None,
                        help="Embedder model dir (overrides auto-detect)")
    parser.add_argument("--reranker-dir", type=str, default=None,
                        help="Reranker model dir (overrides auto-detect)")
    args = parser.parse_args()

    init_embedder(model_dir_override=args.model_dir)
    init_reranker(model_dir_override=args.reranker_dir)

    server = ThreadingHTTPServer((args.host, args.port), InferenceHandler)
    server.timeout = 30  # таймаут на чтение запроса
    logger.info(f"🚀 ONNX сервер http://{args.host}:{args.port}")
    if args.host != "127.0.0.1":
        logger.warning(f"⚠️  Сервер слушает {args.host}, а не 127.0.0.1 — CORS ограничен localhost")
    logger.info(f"🔒 CORS origin: {InferenceHandler._CORS_ORIGIN}")
    logger.info("   POST /v1/embeddings — эмбеддинги")
    logger.info(f"   POST /v1/rerank     — реранкинг ({'active' if _reranker_session else 'disabled'})")
    logger.info("   GET  /v1/models     — список моделей")
    logger.info("   GET  /health        — проверка здоровья + GC после каждого запроса")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("🛑 ONNX сервер остановлен")
        server.server_close()


if __name__ == "__main__":
    main()
