#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E15 (2026-09-21): А/B-бенчмарк embedder'ов — multilingual-e5-small (prod) vs EmbeddingGemma 300M.

МЕТОДОЛОГИЯ (§5):
- Обе модели запускаются llama-server c ТЕМИ ЖЕ флагами, что прод (llama_runner._spawn_embedder):
  -c 2048 --batch-size 2048 --ubatch-size 512 --threads 10 --cache-type-k/q4_0 --no-webui
  -ngl 0 --embedding --pooling mean. e5 префиксы прод не ставит (llama.cpp ветка) — raw text.
- Реальный путь вызова POST /v1/embeddings (как remote_embedder.embed_batch).
- Метрики: tok/s, ch/s, p50 latency, WorkingSet RAM, hit@1/hit@5/MRR (file-level и chunk-level),
  MRL-dim sweep (768/512/256/128, post-hoc head-truncation + re-normalize).
- Детерминизм: фиксированный список файлов и запросов, сортированный порядок.

USAGE:
  python experiments/embeddinggemma/bench.py <key> --port <p> --out <res.json> [--skip-server]
  key ∈ prod_e5 | gemma_q8 | gemma_q4 | gemma_qat4 | gemma_q8_ru
LIVE CHEAT (MRL из готового JSON): --mrl-from <res.json> --key gemma_q8
"""

import argparse
import ctypes
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import httpx
import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
EXP = ROOT / "experiments" / "embeddinggemma"
MODELS_DIR = EXP / "models"
EXT = Path(r"C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence")
LLAMA_EXE = EXT / "llama_msvc" / "llama-server.exe"

# (gguf-path, max_input_tokens, full dim, note)
PRESETS = {
    "prod_e5": (EXT / "models" / "multilingual-e5-small-Q8_0.gguf", 480, 384, "baseline prod"),
    "gemma_q8": (MODELS_DIR / "embeddinggemma-300M-Q8_0.gguf", 2048, 768, "gemma Q8_0 ggml-org"),
    "gemma_q4": (MODELS_DIR / "embeddinggemma-300m-Q4_0.gguf", 2048, 768, "gemma Q4_0 unsloth"),
    "gemma_qat4": (MODELS_DIR / "embeddinggemma-300M-qat-Q4_0.gguf", 2048, 768, "gemma Q4_0 QAT ggml-org"),
    "nomic_q8": (MODELS_DIR / "nomic-embed-text-v1.5.Q8_0.gguf", 8192, 768, "nomic-embed v1.5 Q8_0 nomic-ai"),
    "bge_small": (MODELS_DIR / "bge-small-en-v1.5-q8_0.gguf", 512, 384, "bge-small-en-v1.5 Q8_0 ggml-org"),
    "minilm": (MODELS_DIR / "all-MiniLM-L6-v2.F16.gguf", 512, 384, "all-MiniLM-L6-v2 F16 leliuga"),
}

GOLD = [
    ("как работает hot-reload свежести индекса при изменении файлов", "src/core/indexing/freshness.py"),
    ("миграция схемы добавление колонок file_mtime_ns в таблицу LanceDB", "src/core/indexing/db_manager.py"),
    ("когда таблица пересоздаётся при schema mismatch полный rebuild", "src/core/indexing/db_writer.py"),
    ("векторный поиск похожих чанков по индексу через LanceDB distance", "src/core/search/engine.py"),
    ("ленивая проверка факта памяти verify on read статус ADR", "src/core/intelligence/verify_on_read.py"),
    ("удалённый эмбеддинг через HTTP API llama server batch", "src/providers/embedder/remote_embedder.py"),
    ("per project indexer registry multi window пулы по путям проектов", "src/core/indexing/project_indexer_registry.py"),
    ("переиндексация одного изменённого файла notify change rate limit", "src/mcp/tools/indexing_tools.py"),
    ("ранжирование результатов реранкером BGE M3 перестановка топ", "src/providers/reranker/search_result_reranker.py"),
    ("bm25 ключевые слова медленный но точный полнотекстовый", "src/core/search/bm25.py"),
    ("чат через LM Studio и Ollama реранкинг эмбеддинг многопровайдерный", "src/providers/reranker/multi_provider.py"),
    ("скачивание GGUF моделей эмбеддинг реранкер установка llama сервер", "src/providers/reranker/llama_install.py"),
    ("сборка сервисов dependency injection фабрика indexer создание коллекции", "src/core/di_container.py"),
    ("конфигурация настроек индекса чанк размер оверлап переменные окружения", "src/config/settings.py"),
    ("переиндексация продолжение записи resume порциями known hashes", "src/core/indexing/index_project_runner.py"),
    ("парсер исходников чанки большие тексты фолбэк строки перекрытие", "src/core/indexing/parser.py"),
]

# Дистракторы — НЕ пересекаются с золотыми файлами (иначе эваль вырождается).
DISTRACTORS = [
    "src/providers/reranker/reranker_scoring.py",
    "src/core/indexing/index_parser.py",
    "src/mcp/server_tools.py",
    "src/utils/ui_formatter.py",
    "src/core/consistency.py",
    "src/core/instruction_scan.py",
    "src/mcp/server.py",
    "src/core/artifact_paths.py",
    "src/core/indexing/indexer.py",
    "src/providers/reranker/llama_runner.py",
    "src/core/search/graph_adapter_pure.py",
]

THROUGHPUT_N = 32
BATCHES = [1, 4, 8, 16, 32]
REPS = 2
CHUNK_TOKENS = 420
CHUNK_SWEEP_TARGETS = [128, 256, 384, 512, 768, 1024, 1500, 1900]
CHUNK_SWEEP_N = 8
MRL_DIMS = [768, 512, 256, 128]
QUAL_CHUNK_TOKENS = 400

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def wss_mb(pid: int) -> float:
    class _PMC(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
        ]
    k = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi
    h = k.OpenProcess(0x0410, False, pid)  # QUERY_LIMITED | QUERY
    if not h:
        return -1.0
    try:
        pmc = _PMC(); pmc.cb = ctypes.sizeof(_PMC)
        if not psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
            return -1.0
        return pmc.WorkingSetSize / (1024 * 1024)
    finally:
        k.CloseHandle(h)


class Server:
    def __init__(self, gguf: Path, port: int, log_path: Path, ubatch: int = 512):
        self.gguf, self.port, self.log_path, self.ubatch = gguf, port, log_path, ubatch
        self.proc = None

    def start(self):
        cmd = [
            str(LLAMA_EXE), "--host", "127.0.0.1", "--port", str(self.port),
            "-m", str(self.gguf), "-c", "2048", "--batch-size", "2048",
            "--ubatch-size", str(self.ubatch), "--threads", "10",
            "--cache-type-k", "q4_0", "--cache-type-v", "q4_0",
            "--no-webui", "-ngl", "0", "--embedding", "--pooling", "mean",
        ]
        self.proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL,
            stderr=open(self.log_path, "wb"),
            creationflags=CREATE_NO_WINDOW,
        )
        t0 = time.time()
        with httpx.Client(timeout=3.0) as c:
            while time.time() - t0 < 120:
                if self.proc.poll() is not None:
                    raise RuntimeError(f"llama-server exited rc={self.proc.returncode}")
                try:
                    if c.get(f"http://127.0.0.1:{self.port}/health").status_code == 200:
                        return
                except Exception:
                    time.sleep(1)
        raise RuntimeError("llama-server not healthy after 120s")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        self.proc = None


class Bench:
    def __init__(self, key, port, skip_server, ubatch=512, chunk_tokens=420, qual_tokens=400, prefix="none"):
        self.key = key
        self.gguf, self.max_tokens, self.dim, self.note = PRESETS[key]
        self.port = port
        self.skip_server = skip_server
        self.ubatch = ubatch
        self.chunk_tokens = chunk_tokens
        self.qual_tokens = qual_tokens
        self.prefix = prefix
        self.url = f"http://127.0.0.1:{port}"
        self.client = httpx.Client(timeout=240.0)
        self.server = None
        self._corpora = None

    # ── transport ────────────────────────────────────────────────
    def token_count(self, text: str) -> int:
        r = self.client.post(self.url + "/tokenize", json={"content": text, "add_special": False}, timeout=30)
        r.raise_for_status()
        return len(r.json()["tokens"])

    def prep(self, text: str, target: int) -> str:
        """Префикс text ≈ target токенов (итеративно, безопасно для hot-path)."""
        t = text
        n = self.token_count(t)
        for _ in range(6):
            if n <= target:
                return t
            t = t[: int(len(t) * (target / n) * 0.95) or 1]
            n = self.token_count(t)
        return t

    def embed(self, texts) -> np.ndarray:
        """POST /v1/embeddings (raw, как прод). Возвращает матрицу [n, dim]."""
        s = time.perf_counter()
        r = self.client.post(self.url + "/v1/embeddings", json={"input": list(texts)})
        dt_ms = (time.perf_counter() - s) * 1000
        if r.status_code != 200:
            raise RuntimeError(f"embed HTTP {r.status_code}: {r.text[:300]}")
        items = sorted(r.json()["data"], key=lambda x: x.get("index", 0))
        return np.asarray([d["embedding"] for d in items], dtype=np.float32), dt_ms

    def embed_timed(self, texts, toks):
        vecs, dt_ms = self.embed(texts)
        total_tok = sum(toks)
        dt_s = dt_ms / 1000.0
        return vecs, total_tok, dt_s, len(texts) / dt_s, total_tok / dt_s

    # ── исходные тексты ──────────────────────────────────────────
    def read_files(self, relpaths, max_chars=20000):
        texts = []
        for f in sorted(set(relpaths)):
            p = ROOT / f
            if p.exists():
                texts.append(p.read_text(encoding="utf-8", errors="replace")[:max_chars])
        return texts

    def doc_t(self, text: str) -> str:
        return "search_document: " + text if self.prefix == "nomic" else text

    def qry_t(self, text: str) -> str:
        return "search_query: " + text if self.prefix == "nomic" else text

    # ── фазы ─────────────────────────────────────────────────────
    def phase_throughput(self):
        srcs = self.read_files({f for _, f in GOLD} | set(DISTRACTORS))
        texts = [self.doc_t(self.prep(t, self.chunk_tokens)) for t in srcs][: THROUGHPUT_N]
        toks = [self.token_count(t) for t in texts]
        self.embed(texts[:4])  # warmup
        rows = []
        for b in BATCHES:
            spd, tok, lat = [], [], []
            for _ in range(REPS):
                req_lats = []
                total_tok = 0
                t0 = time.perf_counter()
                for i in range(0, len(texts), b):
                    _, dt_ms = self.embed(texts[i: i + b])
                    total_tok += sum(toks[i: i + b])
                    req_lats.append(dt_ms)
                dt = time.perf_counter() - t0
                spd.append(len(texts) / dt)
                tok.append(total_tok / dt)
                lat.append(statistics.median(req_lats))
            rows.append({
                "batch": b, "ch_s": statistics.median(spd), "tok_s": statistics.median(tok),
                "p50_req_ms": statistics.median(lat),
            })
        return rows

    def phase_chunk_sweep(self):
        srcs = self.read_files({f for _, f in GOLD} | set(DISTRACTORS))
        rows = []
        pfx_tok = 1 if self.prefix == "nomic" else 0
        for target in CHUNK_SWEEP_TARGETS:
            if target > self.max_tokens:
                continue
            if self.ubatch and target + pfx_tok > self.ubatch - 2:
                continue
            texts = [self.doc_t(self.prep(s, target)) for s in srcs[: CHUNK_SWEEP_N]]
            toks = [self.token_count(t) for t in texts]
            vecs, total_tok, dt_s, ch_s, tok_s = self.embed_timed(texts, toks)
            rows.append({
                "target_tokens": target, "actual_tokens_mean": int(sum(toks) / len(toks)),
                "ch_s": ch_s, "tok_s": tok_s, "req_ms": dt_s * 1000, "dim": vecs.shape[1],
            })
        return rows

    def _corpus_files(self):
        gold_files = sorted({f for _, f in GOLD})
        extra = gold_files + DISTRACTORS
        return extra

    def phase_quality(self):
        """hit@1/hit@5/MRR (file-level: первый файл-золото среди уникальных файлов;
        chunk-level: лучший чанк золотого файла). Возвращает аггрегаты + матрицы."""
        files = set()
        for _, f in GOLD:
            files.add(f)
        files |= set(DISTRACTORS)
        texts, file_ids, gold_flags = [], [], []
        for f in sorted(files):
            p = ROOT / f
            if not p.exists():
                continue
            body = p.read_text(encoding="utf-8", errors="replace")
            step = max(len(body) // 3, 1)
            for i in range(3):
                seg = body[i * step: (i + 1) * step]
                if len(seg) < 30:
                    continue
                c = self.doc_t(self.prep(seg, self.qual_tokens))
                if len(c) < 20:
                    continue
                texts.append(c)
                file_ids.append(f.replace("\\", "/"))
                gold_flags.append(f in {g for _, g in GOLD})
        queries = [self.qry_t(q) for q, _ in GOLD]
        Q, _ = self.embed(queries)
        C, _ = self.embed(texts)
        return self._score(Q, C, file_ids, queries), Q, C, file_ids, texts

    def _score(self, Q, C, file_ids, queries):
        n = len(queries)
        Qn = Q / np.linalg.norm(Q, axis=1, keepdims=True)
        Cn = C / np.linalg.norm(C, axis=1, keepdims=True)
        sim = Qn @ Cn.T
        out = {"n_queries": n, "n_chunks": len(C), "q_dim": Q.shape[1]}
        for k in ("h1f", "h5f", "mrrf", "h1c", "h5c", "mrrc"):
            out[k] = []
        for qi, (q, exp) in enumerate(GOLD):
            exp = exp.replace("\\", "/")
            order = np.argsort(-sim[qi])
            # file-level
            seen, rank_f = set(), None
            for rk, i in enumerate(order):
                f = file_ids[i]
                if f in seen:
                    continue
                seen.add(f)
                if f == exp:
                    rank_f = rk + 1
                    break
            # chunk-level: лучший чанк золотого файла
            gold_ranks = [int(np.where(order == i)[0][0]) + 1
                          for i in range(len(file_ids)) if file_ids[i] == exp]
            rank_c = min(gold_ranks) if gold_ranks else 10**6
            out["h1f"].append(1 if rank_f == 1 else 0)
            out["h5f"].append(1 if rank_f and rank_f <= 5 else 0)
            out["mrrf"].append(1.0 / rank_f if rank_f else 0.0)
            out["h1c"].append(1 if rank_c == 1 else 0)
            out["h5c"].append(1 if rank_c <= 5 else 0)
            out["mrrc"].append(1.0 / rank_c)
        agg = {k: [v, float(np.mean(v))] for k, v in out.items() if isinstance(v, list)}
        return {"score": agg, "n_queries": n, "n_chunks": len(C), "q_dim": Q.shape[1]}

    def phase_mrl(self, Q, C, file_ids):
        """MRL head-truncation + re-normalize. Файл-level hit@1/5/MRR на каждой dim."""
        Qn = Q / np.linalg.norm(Q, axis=1, keepdims=True)
        Cn = C / np.linalg.norm(C, axis=1, keepdims=True)
        rows = []
        for d in MRL_DIMS:
            if d >= Q.shape[1]:
                continue
            sim = Qn[:, :d] @ Cn[:, :d].T
            h1 = h5 = mrr = 0
            for qi, (_, exp) in enumerate(GOLD):
                exp = exp.replace("\\", "/")
                order = np.argsort(-sim[qi])
                seen, rank_f = set(), None
                for rk, i in enumerate(order):
                    f = file_ids[i]
                    if f in seen:
                        continue
                    seen.add(f)
                    if f == exp:
                        rank_f = rk + 1
                        break
                h1 += 1 if rank_f == 1 else 0
                h5 += 1 if rank_f and rank_f <= 5 else 0
                mrr += 1.0 / rank_f if rank_f else 0.0
            rows.append({"dim": d, "hit@1": h1 / len(GOLD), "hit@5": h5 / len(GOLD), "mrr": mrr / len(GOLD)})
        return rows

    def run(self):
        if not self.skip_server:
            self.server = Server(self.gguf, self.port, MODELS_DIR / f"{self.key}_stderr.log", self.ubatch)
            self.server.start()
        ram = wss_mb(self.server.proc.pid) if self.server else -1
        print(f"[{self.key}] dim={self.dim} max_tok={self.max_tokens} RAM_wss={ram:.0f}MB")

        tp = self.phase_throughput()
        print(f"[{self.key}] throughput ok")

        cs = self.phase_chunk_sweep()
        print(f"[{self.key}] chunk sweep ok")

        qual, Q, C, file_ids, _ = self.phase_quality()
        mrl = self.phase_mrl(Q, C, file_ids)
        print(f"[{self.key}] quality h1f={qual['score']['h1f'][1]:.3f} mrrc={qual['score']['mrrc'][1]:.3f}")

        return {
            "key": self.key, "gguf": str(self.gguf.name), "note": self.note,
            "dim_full": self.dim, "max_input_tokens": self.max_tokens,
            "ram_wss_mb": ram,
            "throughput": tp, "chunk_sweep": cs,
            "quality": {
                "q_dim": qual["q_dim"], "n_queries": qual["n_queries"], "n_chunks": qual["n_chunks"],
                "hit@1_file": qual["score"]["h1f"][1], "hit@5_file": qual["score"]["h5f"][1],
                "mrr_file": qual["score"]["mrrf"][1],
                "hit@1_chunk": qual["score"]["h1c"][1], "hit@5_chunk": qual["score"]["h5c"][1],
                "mrr_chunk": qual["score"]["mrrc"][1],
            },
            "mrl": mrl,
            "env": {"cpu_threads": 10, "ubatch": self.ubatch, "ctx": 2048, "kv": "q4_0", "pooling": "mean",
                "chunk_tokens": self.chunk_tokens, "qual_tokens": self.qual_tokens, "prefix": self.prefix},
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("key", choices=list(PRESETS))
    ap.add_argument("--port", type=int, default=8093)
    ap.add_argument("--out", required=True)
    ap.add_argument("--skip-server", action="store_true")
    ap.add_argument("--ubatch", type=int, default=512)
    ap.add_argument("--chunk-tokens", type=int, default=420)
    ap.add_argument("--qual-tokens", type=int, default=400)
    ap.add_argument("--prefix", choices=["none", "nomic"], default="none")
    args = ap.parse_args()

    bench = Bench(args.key, args.port, args.skip_server, args.ubatch,
                  args.chunk_tokens, args.qual_tokens, args.prefix)
    try:
        res = bench.run()
    finally:
        if bench.server:
            bench.server.stop()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK → {out}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback

        traceback.print_exc()
        sys.exit(1)
