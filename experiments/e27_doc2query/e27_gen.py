#!/usr/bin/env python3
# -*- coding: utf-8
"""E27: генерация RU-описаний файлов через Qwen3-0.6B-Q4 (b11476, CPU).
Промпт frozen (MANIFEST.md). /no_think против thinking-режима Qwen3.
USAGE: python experiments/e27_doc2query/e27_gen.py --smoke | --all --port 8112
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
import argparse
import json
import re
import subprocess
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent.parent
EXP = ROOT / "experiments" / "e27_doc2query"
MODELS = EXP / "models"
GGUF = MODELS / "Qwen3-0.6B-Q4_K_M.gguf"
LLAMA = ROOT / "experiments" / "embeddinggemma2_eval" / "llama-b11476" / "llama-server.exe"
sys.path.insert(0, str(ROOT / "experiments" / "embeddinggemma2_eval"))
from bench_e18 import GOLD_FILES, DISTRACTORS  # noqa: E402

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
PROMPT_T = ("Опиши назначение этого Python-файла строго ОДНИМ предложением "
            "до 25 слов на русском языке. Запрещены списки, заголовки, примеры "
            "кода и общие рассуждения. Только суть. /no_think\n\nФАЙЛ {rel}\n"
            "```python\n{head}\n```")


def start_server(port):
    log = MODELS / "qwen_stderr.log"
    cmd = [str(LLAMA), "--host", "127.0.0.1", "--port", str(port), "-m", str(GGUF),
           "-c", "4096", "--threads", "10", "--no-webui", "-ngl", "0"]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                            stderr=open(log, "wb"), creationflags=CREATE_NO_WINDOW)
    t0 = time.time()
    with httpx.Client(timeout=3.0) as c:
        while time.time() - t0 < 180:
            if proc.poll() is not None:
                raise RuntimeError(f"server exited rc={proc.returncode}")
            try:
                if c.get(f"http://127.0.0.1:{port}/health").status_code == 200:
                    return proc
            except Exception:
                time.sleep(1)
    raise RuntimeError("server not healthy")


def gen(client, rel, head):
    def once(seed, temp):
        t0 = time.perf_counter()
        r = client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": PROMPT_T.format(rel=rel, head=head)}],
            "temperature": temp, "top_p": 0.9, "max_tokens": 300, "seed": seed})
        dt = time.perf_counter() - t0
        if r.status_code != 200:
            raise RuntimeError(f"gen HTTP {r.status_code}: {r.text[:200]}")
        txt = r.json()["choices"][0]["message"]["content"] or ""
        txt = txt.strip()
        if "<think>" in txt:
            txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.S).strip()
        if "</think>" in txt:
            txt = txt.split("</think>")[-1].strip()
        return txt, dt
    txt, dt = once(42, 0.2)  # детерминированно (сид); greedy-t0 даёт обрывы
    retried = False
    if not txt or len(txt) < 20:  # семплированная пустота/обрывок — повтор
        txt, dt2 = once(43, 0.2)
        dt += dt2
        retried = True
    return txt, dt, retried


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--port", type=int, default=8112)
    ap.add_argument("--out", default=str(EXP / "results" / "descriptions.json"))
    args = ap.parse_args()
    if not GGUF.exists():
        print(f"FATAL: missing {GGUF}", file=sys.stderr)
        sys.exit(2)
    files = sorted(set(GOLD_FILES) | set(DISTRACTORS))
    if args.smoke:
        files = ["src/core/search/bm25.py"]
    proc = start_server(args.port)
    try:
        client = httpx.Client(base_url=f"http://127.0.0.1:{args.port}", timeout=300.0)
        out = {}
        for f in files:
            body = (ROOT / f).read_text(encoding="utf-8", errors="replace")
            desc, dt, retried = gen(client, f.replace("\\", "/"), body[:2000])
            out[f.replace("\\", "/")] = {"desc": desc, "sec": round(dt, 1),
                                          "retried": retried, "short": len(desc) < 20,
                                          "sampling": "t0.2/s42,retry t0.2/s43"}
            print(f"[{dt:.1f}s]{' R' if retried else ''} {f}\n  -> {desc}\n", flush=True)
        if args.all:
            if not out:
                print("FATAL: empty output", file=sys.stderr)
                sys.exit(2)
            p = Path(args.out)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"OK -> {p}  total_s={sum(v['sec'] for v in out.values()):.0f}")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    main()
