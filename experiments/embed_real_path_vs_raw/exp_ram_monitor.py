"""RAM монитор всех причастных процессов: llama-server (embed+rerank), python MCP (src.main),
ONNX server, все python*. Пишет CSV каждые 1s. Запускать фоново через Start-Job."""
import sys, time, subprocess, os, json

OUT = r"C:\Users\misha\AppData\Local\Temp\opencode\ram_full_trace.csv"
DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 600  # сек

def ps_tree():
    """Вернёт {pid: (name, cmdline, ram_mb)} для python*/llama-server."""
    out = subprocess.check_output(
        'powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -match \\\'python|llama\\\' } | ForEach-Object { \'{0}|{1}|{2}|{3}\' -f $_.ProcessId,$_.Name,([math]::Round($_.WorkingSetSize/1MB)),($_.CommandLine) }"',
        shell=True, text=True, errors='replace'
    )
    res = {}
    for line in out.splitlines():
        parts = line.split('|', 3)
        if len(parts) == 4:
            pid, name, ram, cmd = parts
            res[int(pid)] = {"name": name, "ram": int(ram or 0), "cmd": cmd}
    return res

def sampler(stop, logpath, interval=1.0):
    t0 = time.time()
    lines = ["t_s,pid,name,ram_mb,cmd"]
    while not stop.is_set():
        t = time.time() - t0
        try:
            procs = ps_tree()
            for pid, info in sorted(procs.items(), key=lambda kv: -kv[1]["ram"]):
                cmd = info["cmd"][:120].replace(",", "_")
                # короткая классификация для читаемости
                short = "OTHER"
                if "llama-server" in info["name"].lower():
                    if ":8081" in cmd: short = "LLAMA_RERANK_8081"
                    elif ":8080" in cmd: short = "LLAMA_EMBED_8080"
                    else: short = "LLAMA"
                elif "onnx_server" in cmd or "onnx_server.py" in cmd: short = "ONNX_SERVER"
                elif "src.main" in cmd: short = "MCP_MAIN"
                elif "community_memory" in cmd: short = "COMMUNITY"
                else: short = "PY_OTHER"
                lines.append(f"{t:.1f},{pid},{short},{info['ram']},{cmd}")
        except Exception as _e:
            pass
        time.sleep(interval)
    with open(logpath, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

if __name__ == "__main__":
    st = time.time()
    lines = [f"# {time.strftime('%Y-%m-%d %H:%M:%S')} start, dur={DURATION}s"]
    while time.time() - st < DURATION:
        try:
            procs = ps_tree()
            for pid, info in sorted(procs.items(), key=lambda kv: -kv[1]["ram"]):
                cmd = info["cmd"][:120].replace(",", "_")
                short = "OTHER"
                if "llama-server" in info["name"].lower():
                    if ":8081" in cmd: short = "LLAMA_RERANK_8081"
                    elif ":8080" in cmd: short = "LLAMA_EMBED_8080"
                    else: short = "LLAMA"
                elif "onnx_server" in cmd or "onnx_server.py" in cmd: short = "ONNX_SERVER"
                elif "src.main" in cmd: short = "MCP_MAIN"
                elif "community_memory" in cmd: short = "COMMUNITY"
                else: short = "PY_OTHER"
                lines.append(f"{(time.time()-st):.1f},{pid},{short},{info['ram']},{cmd}")
        except Exception:
            pass
        time.sleep(1.0)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"WRITTEN {OUT}")