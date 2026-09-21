"""E14: репродукция реального пути MCP-индексации.
Инстанцирует RemoteEmbedder как в MCP, _init_provider_async, затем embed_batch.
Семплирует RAM в фоновом потоке: self, llama 8080, llama 8081, onnx server (если есть).
"""
import sys, time, threading
sys.stdout.reconfigure(encoding='utf-8')
import os, subprocess

# как MCP: mode init + цикл embed
import pathlib
sys.path.insert(0, r"D:\Project\MSCodeBase")
from src.providers.embedder.remote_embedder import RemoteEmbedder

WATCH = """~/.none"""
PIDS = [os.getpid()]

def _pid_of(name_filter):
    try:
        out = subprocess.check_output(
            "powershell -NoProfile -Command \"Get-CimInstance Win32_Process -Filter \\\"Name='%s'\\\" | ForEach-Object { '{0}|{1}' -f $_.ProcessId,$_.CommandLine }\""
            % name_filter, shell=True, text=True, errors='replace')
        found = []
        for line in out.splitlines():
            if '|' in line:
                pid, cmd = line.split('|', 1)
                found.append((int(pid), cmd))
        return found
    except Exception as _e:
        return []

def _ram_mb(pid):
    try:
        out = subprocess.check_output(
            f"powershell -NoProfile -Command \"(Get-Process -Id {pid} -EA SilentlyContinue).WorkingSet64\"",
            shell=True, text=True, errors='replace')
        return int(float(out.strip() or 0)) // 1048576
    except Exception:
        return -1

def sampler(stop, logpath, interval=0.5):
    t0 = time.time()
    lines = []
    while not stop.is_set():
        t = time.time() - t0
        self_ram = _ram_mb(os.getpid())
        emb = _ram_mb(1396)
        rer = _ram_mb(9348)
        # все python помимо self
        pys = [_rm for _rm in []]
        ils = ""
        for _pid, _cmd in _pid_of("pythonw.exe") + _pid_of("python.exe"):
            if _pid == os.getpid():
                continue
            if "onnx_server" in _cmd or "onnx_server.py" in _cmd:
                ils += f" onnx_server={_ram_mb(_pid)}MB"
        lines.append(f"t={t:5.1f} self={self_ram}MB embed8080={emb}MB rerank8081={rer}MB{ils}")
        time.sleep(interval)
    with open(logpath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

emb = RemoteEmbedder()
print("mode после init:", emb.mode, "| _onnx_client:", emb._onnx_client is not None)
# только те инстансы, которые MCP делает на старте (не трогаем глобальные серверы):
# _init_provider_async запускается в потоке; вызываем напрямую как стартовый путь
from threading import Thread
emb._init_provider_async()
print("mode после provider_async:", emb.mode)
if emb._onnx_client is not None:
    print("onnx server running:", emb._onnx_client._is_server_running() if hasattr(emb._onnx_client, '_is_server_running') else '?')

stop = threading.Event()
th = threading.Thread(target=sampler, args=(stop, r"C:\Users\misha\AppData\Local\Temp\opencode\ram_e14.txt"), daemon=True)
th.start()

import httpx, lancedb
DB = r"C:\Users\misha\AppData\Local\mscodebase\projects\bfe9644b\lancedb_v2\index_mscodebase_bfe9644b.db"
db = lancedb.connect(DB)
df = db.open_table("codebase_chunks").to_pandas().head(2000)
texts = [str(x) for x in df["text"].tolist()]
texts.sort(key=len)

for i in range(0, len(texts), 32):
    batch = texts[i:i+32]
    try:
        emb.embed_batch(batch)
    except Exception as e:
        print(f"  embed_batch fail at {i}: {type(e).__name__}: {e}")
    if i % 320 == 0:
        print(f"  [{i}/{len(texts)}] mode={emb.mode} onnx_client={emb._onnx_client is not None}")
stop.set()
# финальный дамп процесса self
print("self RAM final:", _ram_mb(os.getpid()), "MB")
print("--- trace ---")
with open(r"C:\Users\misha\AppData\Local\Temp\opencode\ram_e14.txt", encoding="utf-8") as f:
    print(f.read())