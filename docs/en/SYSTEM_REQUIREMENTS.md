# System Requirements & Architecture Reference

> Based on real benchmarks (2026-07-10) on Windows 11 Insider Preview build 26220
> CPU: AMD Ryzen 5 5600H (12 cores) | RAM: 16 GB DDR4

---

## 1. Minimum Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **CPU** | x86_64 with AVX2 (AMD Ryzen 3xxx / Intel Haswell 4xxx+) | Any x86_64 with AVX2 |
| **RAM** | 8 GB (system) + 1.2 GB (MCP + models) | 16 GB + 1.2 GB |
| **Storage** | 2 GB free (models + index) | 5 GB for large monorepos |
| **OS (Windows)** | Windows 10 22H2+ | Windows 11 stable (not Insider Preview) |
| **OS (macOS)** | macOS 12+ Intel or Apple Silicon | macOS 14+ Apple Silicon (Metal) |
| **OS (Linux)** | Ubuntu 22.04+ x86_64 | Ubuntu 24.04+ |
| **Python** | 3.10+ | 3.12+ |
| **Zed** | v1.10.0+ | latest |

---

## 2. RAM Breakdown (real measurements)

### Current architecture (Qwen3 + BGE-M3 via llama.cpp GGUF)

| Process | RAM (no --mlock) | RAM (with --mlock) | Notes |
|---------|-----------------|-------------------|-------|
| **MCP (python.exe)** | 213 – 252 MB | 213 – 252 MB | Stable, no leaks |
| **llama-server Qwen3** (port 8080) | **346 MB** | 772 MB | Embedding model |
| **llama-server BGE-M3** (port 8081) | **450 MB** | 539 MB | Reranker model |
| **Total** | **~1.0 – 1.1 GB** | ~1.5 – 1.6 GB | |

### Historical comparison

| Date | RAM MCP | RAM Models | Total | Config |
|------|---------|-----------|-------|--------|
| 2026-07-05 | 185 MB | 0 MB (external API) | **185 MB** | LM Studio (remote) |
| 2026-07-08 | 172 MB | 0 MB (external API) | **172 MB** | LM Studio |
| 2026-07-09 (early) | 151 MB | 0 MB (external API) | **151 MB** | LM Studio unavailable |
| 2026-07-09 (late) | 1,931 MB | 757 MB | **2,688 MB** | ONNX in-process 🔴 |
| **2026-07-10** | **252 MB** | **796 MB** | **~1,048 MB** | **Qwen3 + BGE-M3 GGUF** 🟢 |

**Key insight:** ONNX Runtime in MCP process caused 2 GB+ RAM. Moving to llama.cpp GGUF reduced MCP memory by 88% and total by 60%.

---

## 3. Performance Benchmarks

### Search speed (latency in ms)

| Mode | Before (ONNX) | After (Qwen3) | Speedup |
|------|-------------|--------------|---------|
| `fast` | 988 ms | **278 ms** | **3.6x** |
| `quality` | 1,441 ms | **303 ms** | **4.8x** |
| `deep` | ~5,000 ms | **~3,500 ms** | **1.4x** |
| `context` | ~800 ms | **~300 ms** | **2.7x** |

### Embedding throughput

| Metric | Before (ONNX) | After (Qwen3) |
|--------|-------------|--------------|
| Single embed | 988 ms | **292 ms** |
| Batch 10 | 1,500 ms | **308 ms** |
| Throughput | ~200 tok/s | **1,624 tok/s** |
| Rerank 5 docs | 1