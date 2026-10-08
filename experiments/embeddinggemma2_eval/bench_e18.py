#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E18 (2026-10-07): EmbeddingGemma-2 eval — форк bench.py (E14/E15).

DIFF vs experiments/embeddinggemma/bench.py (минимальный):
1. LLAMA_EXE по умолчанию = experiments/embeddinggemma2_eval/llama-b11476 (первый
   релиз с arch gemma-embedding2, PR #30054, merge 2026-10-06; b9940/b11429 дают
   "unknown model architecture"). Override: env E18_LLAMA_EXE.
2. PRESETS: e18_e5 (прод-контроль, та же сессия), g2q8, g2bf16 (ctx 8192 по вендору).
3. prefix "coderet": вендорные CodeRetrieval-префиксы
   (query "task: code retrieval | query: {...}", doc "title: {file} | text: {...}").
4. Запросы читаются из frozen/QUERIES.jsonl (16 gold + POS_1 + NEG_1), а не из GOLD.
   Корпус тот же (27 файлов src/ — реальные данные).
5. T10-guard: пустые запросы/пустой корпус -> sys.exit(2), а не "0%".
6. NEG-контроль: max-sim OOD-запроса vs корпус (ожидание тишины, H7).
7. Server: параметр ctx (-c), версия бинарника и git-sha харнесса пишутся в results.env.

USAGE:
  python experiments/embeddinggemma2_eval/bench_e18.py <key> --port <p> --out <res.json>
    [--ubatch 512|2048] [--ctx 2048|8192] [--chunk-tokens N] [--qual-tokens N]
    [--prefix none|coderet]
  key ∈ e18_e5 | g2q8 | g2bf16
"""

import argparse
import ctypes
import json
import os
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
EXP = ROOT / "experiments" / "embeddinggemma2_eval"
E18MODELS = EXP / "models"
FROZEN_Q = EXP / "frozen" / "QUERIES.jsonl"
EXT = Path(r"C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence")
LLAMA_EXE = Path(os.environ.get(
    "E18_LLAMA_EXE", str(EXP / "llama-b11476" / "llama-server.exe")))

# (gguf-path, max_input_tokens, full dim, note)
PRESETS = {
    "e18_e5": (EXT / "models" / "multilingual-e5-small-Q8_0.gguf", 480, 384,
               "prod control, same session"),
    "g2q8": (E18MODELS / "embeddinggemma-2-Q8_0.gguf", 8192, 768,
             "gemma2 Q8_0 ggml-org"),
    "g2bf16": (E18MODELS / "embeddinggemma-2-BF16.gguf", 8192, 768,
               "gemma2 BF16 ggml-org"),
    "g2q4": (E18MODELS / "embeddinggemma-2-UD-Q4_K_XL.gguf", 8192, 768,
             "gemma2 UD-Q4_K_XL unsloth"),
    "g2q3m": (E18MODELS / "embeddinggemma-2.Q3_K_M.gguf", 8192, 768,
              "gemma2 Q3_K_M prithivMLmods"),
    "g2q3l": (E18MODELS / "embeddinggemma-2.Q3_K_L.gguf", 8192, 768,
              "gemma2 Q3_K_L prithivMLmods"),
}

# Корпус — как E14 (реальные файлы; запросы — из frozen).
GOLD_FILES = [
    "src/core/indexing/freshness.py",
    "src/core/indexing/db_manager.py",
    "src/core/indexing/db_writer.py",
    "src/core/search/engine.py",
    "src/core/intelligence/verify_on_read.py",
    "src/providers/embedder/remote_embedder.py",
    "src/core/indexing/project_indexer_registry.py",
    "src/mcp/tools/indexing_tools.py",
    "src/providers/reranker/search_result_reranker.py",
    "src/core/search/bm25.py",
    "src/providers/reranker/multi_provider.py",
    "src/providers/reranker/llama_install.py",
    "src/core/di_container.py",
    "src/config/settings.py",
    "src/core/indexing/index_project_runner.py",
    "src/core/indexing/parser.py",
]
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


def llama_version(exe: Path) -> str:
    try:
        r = subprocess.run([str(exe), "--version"], capture_output=True,
                           text=True, timeout=30,
                           creationflags=CREATE_NO_WINDOW)
        out = (r.stdout + r.stderr).strip().splitlines()
        return out[0][:120] if out else "unknown"
    except Exception as e:
        return f"version-probe-failed: {type(e).__name__}"


class Server:
    def __init__(self, gguf: Path, port: int, log_path: Path, ubatch: int = 512,
                 ctx: int = 2048):
        self.gguf, self.port, self.log_path = gguf, port, log_path
        self.ubatch, self.ctx = ubatch, ctx
        # E19: бэкенд через env (E18_NGL=99 для Vulkan/iGPU, по умолч. 0 = CPU)
        self.ngl = int(os.environ.get("E18_NGL", "0"))
        self.proc = None

    def start(self):
        cmd = [
            str(LLAMA_EXE), "--host", "127.0.0.1", "--port", str(self.port),
            "-m", str(self.gguf), "-c", str(self.ctx), "--batch-size", "2048",
            "--ubatch-size", str(self.ubatch), "--threads", "10",
            "--cache-type-k", "q4_0", "--cache-type-v", "q4_0",
            "--no-webui", "-ngl", str(self.ngl), "--embedding", "--pooling", "mean",
        ]
        self.proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL,
            stderr=open(self.log_path, "wb"),
            creationflags=CREATE_NO_WINDOW,
        )
        t0 = time.time()
        with httpx.Client(timeout=3.0) as c:
            while time.time() - t0 < 180:
                if self.proc.poll() is not None:
                    raise RuntimeError(f"llama-server exited rc={self.proc.returncode}")
                try:
                    if c.get(f"http://127.0.0.1:{self.port}/health").status_code == 200:
                        return
                except Exception:
                    time.sleep(1)
        raise RuntimeError("llama-server not healthy after 180s")

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
    def __init__(self, key, port, skip_server, ubatch=512, chunk_tokens=420,
                 qual_tokens=400, prefix="none", ctx=2048):
        self.key = key
        self.gguf, self.max_tokens, self.dim, self.note = PRESETS[key]
        self.port = port
        self.skip_server = skip_server
        self.ubatch = ubatch
        self.chunk_tokens = chunk_tokens
        self.qual_tokens = qual_tokens
        self.prefix = prefix
        self.ctx = ctx
        self.url = f"http://127.0.0.1:{port}"
        self.client = httpx.Client(timeout=240.0)
        self.server = None
        self.queries = self._load_queries()  # T10: exit(2) если пусто

    def _load_queries(self):
        if not FROZEN_Q.exists():
            print(f"FATAL: frozen queries missing: {FROZEN_Q}", file=sys.stderr)
            sys.exit(2)
        rows = [json.loads(l) for l in
                FROZEN_Q.read_text(encoding="utf-8").splitlines() if l.strip()]
        if not rows:  # T10: тихий ноль запрещён
            print("FATAL: frozen queries empty, refusing 0% metric", file=sys.stderr)
            sys.exit(2)
        return rows

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

    def read_files_named(self, relpaths, max_chars=20000):
        out = []
        for f in sorted(set(relpaths)):
            p = ROOT / f
            if p.exists():
                out.append((f.replace("\\", "/"),
                            p.read_text(encoding="utf-8", errors="replace")[:max_chars]))
        return out

    def doc_t(self, text: str, title: str = "doc") -> str:
        if self.prefix == "coderet":
            return f"title: {title} | text: {text}"
        return text

    def qry_t(self, text: str) -> str:
        if self.prefix == "coderet":
            return f"task: code retrieval | query: {text}"
        return text

    # ── фазы ─────────────────────────────────────────────────────
    def phase_throughput(self):
        srcs = self.read_files(set(GOLD_FILES) | set(DISTRACTORS))
        if not srcs:  # T10
            print("FATAL: throughput corpus empty", file=sys.stderr)
            sys.exit(2)
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
        srcs = self.read_files(set(GOLD_FILES) | set(DISTRACTORS))
        rows = []
        pfx_tok = 12 if self.prefix == "coderet" else 0
        for target in CHUNK_SWEEP_TARGETS:
            if target > min(self.max_tokens, self.ctx):
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

    def phase_quality(self):
        """hit@1/hit@5/MRR по frozen-запросам (gold+positive) + NEG max-sim."""
        files = sorted(set(GOLD_FILES) | set(DISTRACTORS))
        named = self.read_files_named(files)
        if not named:  # T10
            print("FATAL: quality corpus empty", file=sys.stderr)
            sys.exit(2)
        texts, file_ids = [], []
        for f, body in named:
            step = max(len(body) // 3, 1)
            for i in range(3):
                seg = body[i * step: (i + 1) * step]
                if len(seg) < 30:
                    continue
                c = self.doc_t(self.prep(seg, self.qual_tokens), title=f)
                if len(c) < 20:
                    continue
                texts.append(c)
                file_ids.append(f)
        if not texts:  # T10
            print("FATAL: quality chunks empty", file=sys.stderr)
            sys.exit(2)
        scored = [q for q in self.queries if q["type"] in ("gold", "positive")]
        neg = [q for q in self.queries if q["type"] == "negative"]
        if not scored:  # T10
            print("FATAL: no scored queries", file=sys.stderr)
            sys.exit(2)
        queries = [self.qry_t(q["query"]) for q in scored]
        Q, _ = self.embed(queries)
        C, _ = self.embed(texts)
        res = self._score(Q, C, file_ids, [(q["query"], q["expect"]) for q in scored])
        neg_res = []
        for q in neg:
            Qn, _ = self.embed([self.qry_t(q["query"])])
            sim = (Qn / np.linalg.norm(Qn, axis=1, keepdims=True)) @ (
                C / np.linalg.norm(C, axis=1, keepdims=True)).T
            assert sim.shape == (1, len(texts)), f"neg sim shape {sim.shape}"
            top = sorted([(float(sim[0, i]), file_ids[i]) for i in range(len(texts))],
                         reverse=True)[:3]
            neg_res.append({"id": q["id"], "max_sim": top[0][0], "top3": top})
        return res, Q, C, file_ids, neg_res

    def _score(self, Q, C, file_ids, queries):
        n = len(queries)
        Qn = Q / np.linalg.norm(Q, axis=1, keepdims=True)
        Cn = C / np.linalg.norm(C, axis=1, keepdims=True)
        sim = Qn @ Cn.T
        out = {"n_queries": n, "n_chunks": len(C), "q_dim": Q.shape[1]}
        for k in ("h1f", "h5f", "mrrf", "h1c", "h5c", "mrrc"):
            out[k] = []
        for qi, (q, exp) in enumerate(queries):
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

    def phase_mrl(self, Q, C, file_ids, queries):
        """MRL head-truncation. Два варианта (честность сравнения):
        e14style — как E14 (без re-normalize, для сравнения с E14);
        renorm — по best practice вендора (re-normalize после среза)."""
        Qn = Q / np.linalg.norm(Q, axis=1, keepdims=True)
        Cn = C / np.linalg.norm(C, axis=1, keepdims=True)
        rows = []
        for d in MRL_DIMS:
            if d >= Q.shape[1]:
                continue
            for mode in ("e14style", "renorm"):
                if mode == "e14style":
                    sim = Qn[:, :d] @ Cn[:, :d].T
                else:
                    Qd = Qn[:, :d] / np.linalg.norm(Qn[:, :d], axis=1, keepdims=True)
                    Cd = Cn[:, :d] / np.linalg.norm(Cn[:, :d], axis=1, keepdims=True)
                    sim = Qd @ Cd.T
                h1 = h5 = mrr = 0
                for qi, (_, exp) in enumerate(queries):
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
                rows.append({"dim": d, "mode": mode,
                             "hit@1": h1 / len(queries), "hit@5": h5 / len(queries),
                             "mrr": mrr / len(queries)})
        return rows

    def run(self):
        if not self.skip_server:
            self.server = Server(self.gguf, self.port,
                                 E18MODELS / f"{self.key}_stderr.log",
                                 self.ubatch, self.ctx)
            self.server.start()
        ram = wss_mb(self.server.proc.pid) if self.server else -1
        print(f"[{self.key}] dim={self.dim} max_tok={self.max_tokens} RAM_wss={ram:.0f}MB", flush=True)

        tp = self.phase_throughput()
        print(f"[{self.key}] throughput ok", flush=True)

        cs = self.phase_chunk_sweep()
        print(f"[{self.key}] chunk sweep ok ({len(cs)} rows)", flush=True)

        qual, Q, C, file_ids, neg_res = self.phase_quality()
        scored_q = [(q["query"], q["expect"]) for q in self.queries
                    if q["type"] in ("gold", "positive")]
        mrl = self.phase_mrl(Q, C, file_ids, scored_q)
        print(f"[{self.key}] quality h1f={qual['score']['h1f'][1]:.3f} "
              f"mrrc={qual['score']['mrrc'][1]:.3f} "
              f"neg_max={neg_res[0]['max_sim']:.3f}" if neg_res else "", flush=True)

        return {
            "key": self.key, "gguf": str(self.gguf.name), "note": self.note,
            "dim_full": self.dim, "max_input_tokens": self.max_tokens,
            "ram_wss_mb": ram,
            "throughput": tp, "chunk_sweep": cs,
            "quality": {
                "q_dim": qual["q_dim"], "n_queries": qual["n_queries"],
                "n_chunks": qual["n_chunks"],
                "hit@1_file": qual["score"]["h1f"][1], "hit@5_file": qual["score"]["h5f"][1],
                "mrr_file": qual["score"]["mrrf"][1],
                "hit@1_chunk": qual["score"]["h1c"][1], "hit@5_chunk": qual["score"]["h5c"][1],
                "mrr_chunk": qual["score"]["mrrc"][1],
                "per_query_h1f": qual["score"]["h1f"][0],
            },
            "mrl": mrl,
            "controls": {
                "pos_queries": [q["id"] for q in self.queries if q["type"] == "positive"],
                "neg": neg_res,
            },
            "env": {"cpu_threads": 10, "ubatch": self.ubatch, "ctx": self.ctx,
                    "kv": "q4_0", "pooling": "mean",
                    "chunk_tokens": self.chunk_tokens, "qual_tokens": self.qual_tokens,
                    "prefix": self.prefix,
                    "llama_exe": str(LLAMA_EXE), "llama_version": llama_version(LLAMA_EXE),
                    "ngl": self.server.ngl if self.server else -1},
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("key", choices=list(PRESETS))
    ap.add_argument("--port", type=int, default=8096)
    ap.add_argument("--out", required=True)
    ap.add_argument("--skip-server", action="store_true")
    ap.add_argument("--ubatch", type=int, default=512)
    ap.add_argument("--ctx", type=int, default=2048)
    ap.add_argument("--chunk-tokens", type=int, default=420)
    ap.add_argument("--qual-tokens", type=int, default=400)
    ap.add_argument("--prefix", choices=["none", "coderet"], default="none")
    args = ap.parse_args()

    bench = Bench(args.key, args.port, args.skip_server, args.ubatch,
                  args.chunk_tokens, args.qual_tokens, args.prefix, args.ctx)
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
