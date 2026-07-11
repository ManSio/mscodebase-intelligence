"""
llama.cpp runner — автоматический lifecycle.

Управляет llama-server.exe как подпроцессом:
- Скачивает бинарник при первом запуске
- Скачивает GGUF модели (bge-m3 + reranker)
- Запускает/останавливает сервер
- Health-чеки через /health
- Graceful shutdown

Архитектура:
  MCP process
    ├── LlamaRunner (менеджер подпроцесса)
    │   ├── llama-server --embedding (bge-m3 GGUF)
    │   └── llama-server --reranking (bge-reranker-v2-m3 GGUF)
    └── Fallback: ONNX server (если llama не запустился)
"""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Optional

import hashlib
import httpx

logger = logging.getLogger("mscodebase_server.llama_runner")

# ─── Конфигурация ──────────────────────────────────────────────
LLAMA_VERSION = "b9940"  # ⚠️ перед бампом проверь https://github.com/ggml-org/llama.cpp/security (GHSA-advisories)
LLAMA_BASE_URL = (
    f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_VERSION}"
)
LLAMA_PORT = int(os.getenv("LLAMA_CPP_PORT", "8080"))
LLAMA_HOST = os.getenv("LLAMA_CPP_HOST", "127.0.0.1")

# 🏆 Оптимальные параметры для эмбеддингов (Qwen3-Embedding)
# Основание: бенчмарки 2026-07-09 — ctx 1024 даёт 722 MB RAM (vs 1669 MB с полным)
# batch-size 512: обрабатывает до 512 токенов за один проход
# ubatch-size 128: физический батч для CPU
# device none: CPU-only (работает и на MSVC, и на Clang сборках)
LLAMA_CTX_SIZE = int(os.getenv("LLAMA_CTX_SIZE", "1024"))     # 1024 = ~500 MB RAM для Qwen3
LLAMA_BATCH_SIZE = int(os.getenv("LLAMA_BATCH_SIZE", "512"))   # 256 токенов за проход (быстрая индексация)
LLAMA_UBATCH_SIZE = int(os.getenv("LLAMA_UBATCH_SIZE", "512"))  # 64 микро-батч для CPU
LLAMA_DEFRAG_THOLD = float(os.getenv("LLAMA_DEFRAG_THOLD", "0.3"))  # дефрагментация KV при 30%
LLAMA_CACHE_TYPE = os.getenv("LLAMA_CACHE_TYPE", "q4_0")  # сжатие KV кэша (q4_0 = 4-bit, без потери качества)

# ─── Платформенная детекция ────────────────────────────────────
def _detect_platform() -> tuple:
    """Определяет platform tag для скачивания llama.cpp.

    Returns:
        (tag, exe_name, zip_ext, cpu_info) 
        tag: "win-cpu-x64", "macos-arm64", "macos-x64", "ubuntu-x64"
        exe_name: ".exe" или ""
        zip_ext: ".zip" или ".tar.gz"
        cpu_info: словарь с информацией о CPU
    """
    cpu_info = _detect_cpu()
    
    if sys.platform == "win32":
        return "win-cpu-x64", ".exe", ".zip", cpu_info
    elif sys.platform == "darwin":
        machine = cpu_info.get("arch", "")
        if machine in ("arm64", "aarch64"):
            return "macos-arm64", "", ".tar.gz", cpu_info
        return "macos-x64", "", ".tar.gz", cpu_info
    elif sys.platform == "linux":
        return "ubuntu-x64", "", ".tar.gz", cpu_info
    return "win-cpu-x64", ".exe", ".zip", cpu_info  # fallback


def _detect_cpu() -> dict:
    """Детектит возможности CPU.

    Returns:
        {
            "arch": "x86_64" | "arm64" | "aarch64",
            "avx": bool,
            "avx2": bool,
            "avx512": bool,
            "sse": bool,
            "name": "AMD Ryzen 5 5600H",
            "cores": int,
            "ram_gb": int,
        }
    """
    import subprocess, re
    
    info = {
        "arch": "x86_64",
        "avx": False,
        "avx2": False,
        "avx512": False,
        "sse": False,
        "name": "unknown",
        "cores": os.cpu_count() or 4,
        "ram_gb": 0,
    }
    
    # RAM
    try:
        if sys.platform == "win32":
            out = subprocess.check_output(
                ["wmic", "memorychip", "get", "capacity"], timeout=5
            ).decode()
            total_bytes = sum(int(x) for x in re.findall(r"\d+", out) if len(x) > 5)
            info["ram_gb"] = total_bytes // (1024**3)
        elif sys.platform == "darwin":
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], timeout=5)
            info["ram_gb"] = int(out.strip()) // (1024**3)
        elif sys.platform == "linux":
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        info["ram_gb"] = kb // (1024*1024)
                        break
    except Exception:
        info["ram_gb"] = 8  # conservative default
    
    # CPU name
    try:
        if sys.platform == "win32":
            out = subprocess.check_output(
                ["wmic", "cpu", "get", "name"], timeout=5
            ).decode()
            for line in out.splitlines():
                if line.strip() and "Name" not in line:
                    info["name"] = line.strip()
                    break
        elif sys.platform == "darwin":
            out = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], timeout=5)
            info["name"] = out.decode().strip()
        elif sys.platform == "linux":
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.startswith("model name"):
                        info["name"] = line.split(":")[1].strip()
                        break
    except Exception:
        pass
    
    # CPU features через python
    cpu_name = info["name"].lower()
    
    # По имени CPU определяем возможности
    if "ryzen" in cpu_name or "epyc" in cpu_name:
        info["avx"] = True
        info["avx2"] = True
        info["sse"] = True
        # Ryzen 7000+ (Zen 4) has AVX512
        if any(m in cpu_name for m in ["7", "8", "9"]):
            # Check if Zen 4+ (Ryzen 7000 series)
            import re
            nums = re.findall(r"(\d{4})", cpu_name)
            if nums and int(nums[0][0]) >= 7:
                info["avx512"] = True
    elif "intel" in cpu_name:
        info["avx"] = True
        info["sse"] = True
        # Intel Core 2xxx+ (Sandy Bridge, 2011) → AVX
        # Intel Core 4xxx+ (Haswell, 2013) → AVX2
        # Intel Core 10xxx+ (Ice Lake, 2019) → AVX512
        import re
        nums = re.findall(r"(i\d)-?(\d{4})|(\d+)th", cpu_name)
        if nums:
            gen = 0
            for g in nums:
                if g[1]: gen = int(g[1][0])  # i7-8700K → 8
                elif g[2]: gen = int(g[2])  # 11th Gen → 11
            info["avx2"] = gen >= 4  # Haswell
            info["avx512"] = gen >= 10  # Ice Lake
    elif "arm" in cpu_name or "apple" in cpu_name:
        info["arch"] = "arm64"
    
    # Попробуем проверить через cpuid напрямую если не сработало
    if not info["sse"] and not info["avx"]:
        # Попробуем запустить простой тест
        info["avx2"] = True  # optimistic default для современных CPU
        info["avx"] = True
        info["sse"] = True
    
    return info


def _is_windows_insider() -> bool:
    """Проверяет, является ли Windows сборка Insider/24H2+.
    На builds >= 26000 отсутствуют api-ms-win-crt-* API Sets,
    что вызывает ошибку при запуске llama-server.exe.
    """
    if sys.platform != "win32":
        return False
    try:
        import platform
        ver = platform.version()  # "10.0.26220"
        parts = ver.split(".")
        if len(parts) >= 3:
            build = int(parts[2])
            return build >= 26000
    except Exception:
        pass
    return False


_PLATFORM_TAG, _EXE_SUFFIX, _ZIP_EXT, _CPU_INFO = _detect_platform()
LLAMA_BIN_NAME = f"llama-server{_EXE_SUFFIX}"
LLAMA_BIN_ZIP = f"llama-{LLAMA_VERSION}-bin-{_PLATFORM_TAG}{_ZIP_EXT}"
LLAMA_BIN_URL = f"{LLAMA_BASE_URL}/{LLAMA_BIN_ZIP}"

# 📊 Модели GGUF (Q4_K_M — 4-bit, лучший balance точность/скорость)
# 🏆 Qwen3 — DEFAULT (лучшее качество для кода+русский, ctx=1024 → 722 MB RAM)
# 🥈 BGE-M3 — FALLBACK (отличный balance, 692 MB RAM, не зависит от контекста)
# 🥉 Granite-311m — REJECTED (качество в 2-3x ниже для кода)
GGUF_MODELS = {
    "qwen3-embedding": {
        "repo": "enacimie/Qwen3-Embedding-0.6B-Q4_K_M-GGUF",
        "file": "qwen3-embedding-0.6b-q4_k_m.gguf",
        "size_mb": 379,
        "dim": 1024,
        "ctx_recommended": 1024,
    },
    "bge-m3": {
        "repo": "lm-kit/bge-m3-gguf",
        "file": "bge-m3-Q4_K_M.gguf",
        "size_mb": 417,
        "dim": 1024,
    },
    "bge-reranker-v2-m3": {
        "repo": "lm-kit/bge-m3-reranker-v2-gguf",
        "file": "Bge-M3-568M-Q4_K_M.gguf",
        "size_mb": 418,
    },
}

# Модель по умолчанию (можно переопределить через EMEDDING_MODEL)
# qwen3-embedding — лучшее качество (722 MB RAM, 2.4 чанка/с)
# bge-m3 — в 5x быстрее индексация (692 MB RAM, 12 чанков/с)
DEFAULT_EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "bge-m3")
DEFAULT_RERANKER_MODEL = "bge-reranker-v2-m3"

# На Insider (build >= 26000): MSVC сборка не может загрузить api-ms-win-crt-* DLL
# (виртуальные API Set удалены Microsoft). Решение: патчим импорты всех DLL на
# ucrtbase.dll после распаковки (см. _patch_dll_imports в download_llama_binary).
_IS_INSIDER = _is_windows_insider()
if _IS_INSIDER:
    logger.info("🔧 Windows Insider detected: CRT API Set missing, will patch DLL imports")
    LLAMA_BIN_TAG = "win-cpu-x64"
    LLAMA_BIN_ZIP = f"llama-{LLAMA_VERSION}-bin-{LLAMA_BIN_TAG}{_ZIP_EXT}"
    LLAMA_BIN_URL = f"{LLAMA_BASE_URL}/{LLAMA_BIN_ZIP}"

# ─── Vulkan детекция ────────────────────────────────────────
# Если есть Vulkan-совместимая видеокарта — используем GPU для эмбеддингов.
# Это разгружает CPU и ускоряет индексацию в 2-5x.
_HAVE_VULKAN = False
if sys.platform == "win32":
    try:
        _vk_dll = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32" / "vulkan-1.dll"
        if _vk_dll.exists():
            import subprocess as _sp
            _vk_info = _sp.run(["vulkaninfo", "--summary"], capture_output=True, timeout=5, text=True)
            if "GPU0" in _vk_info.stdout and "PHYSICAL_DEVICE_TYPE" in _vk_info.stdout:
                _HAVE_VULKAN = True
                os.environ.setdefault("LLAMA_BACKEND", "vulkan")
                logger.info(f"🖥️ Vulkan GPU detected — using GPU for embeddings")
    except Exception:
        pass

# ─── Планировщик модели ────────────────────────────────────────
# Пока llama-server умеет загружать только 1 модель за раз.
# Запускаем embedder, при необходимости реранкинга — рестарт с --reranking.
# (В будущем релизах llama.cpp обещают поддержку нескольких моделей в одном процессе)


def _get_ext_dir() -> Path:
    """Определяет директорию расширения.
    
    Приоритет:
    1. Расширение (по sys.executable: .../venv/Scripts/python.exe)
    2. Frozen (PyInstaller)
    3. Режим разработки (по __file__)
    4. Кеш пользователя
    """
    # Frozen (PyInstaller) — sys.executable это сам бинарник
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent.parent.parent
    # Расширение: .../venv/Scripts/python.exe → …/
    p = Path(sys.executable).resolve().parent.parent.parent
    if (p / "src" / "main.py").exists():
        return p
    # Режим разработки
    p = Path(__file__).resolve().parent.parent.parent
    if (p / "src" / "main.py").exists():
        return p
    return Path.home() / ".cache" / "mscodebase"


def _get_llama_dir() -> Path:
    """Директория для llama.cpp бинарника по умолчанию (MSVC с CRT DLL)."""
    return _get_ext_dir() / "llama_msvc"


def _get_vulkan_dir() -> Path:
    """Директория для Vulkan/Clang сборки (без утечки памяти, для embedder)."""
    return _get_ext_dir() / "llama_vulkan"


def _get_models_dir() -> Path:
    """Директория для GGUF моделей."""
    return _get_ext_dir() / "models"


def _llama_bin() -> Path:
    """Полный путь к llama-server бинарнику (MSVC)."""
    return _get_llama_dir() / f"llama-server{_EXE_SUFFIX}"


def _llama_bin_vulkan() -> Path:
    """Полный путь к Vulkan/Clang сборке (без утечки, для embedder)."""
    return _get_vulkan_dir() / f"llama-server{_EXE_SUFFIX}"


def _gguf_path(model_key: str) -> Path:
    """Полный путь к GGUF файлу модели."""
    return _get_models_dir() / GGUF_MODELS[model_key]["file"]


# ─── Установка ──────────────────────────────────────────────────

def is_installed() -> bool:
    """Проверяет, установлен ли llama.cpp."""
    return _llama_bin().exists()


def is_compatible() -> bool:
    """Проверяет, может ли llama.cpp работать на этой системе."""
    return _llama_bin().exists()


def is_model_downloaded(model_key: str) -> bool:
    """Проверяет, скачана ли GGUF модель."""
    return _gguf_path(model_key).exists()


def _install_vulkan_build(logger, progress_cb=None) -> bool:
    """Скачивает Vulkan/Clang сборку и добавляет CPU fallback DLL."""
    if not _HAVE_VULKAN:
        return False
    vulkan_dir = _get_vulkan_dir()
    vulkan_dir.mkdir(parents=True, exist_ok=True)
    
    v_tag = "win-vulkan-x64"
    v_zip = f"llama-{LLAMA_VERSION}-bin-{v_tag}{_ZIP_EXT}"
    v_url = f"{LLAMA_BASE_URL}/{v_zip}"
    archive_path = vulkan_dir / v_zip
    
    bin_path = vulkan_dir / f"llama-server{_EXE_SUFFIX}"
    if bin_path.exists() and not archive_path.exists():
        return True  # uzhe ustanovleno
    
    logger.info(f"⬇️  Skachivayu Vulkan build ({v_tag})...")
    try:
        import urllib.request
        def _r(b, bs, total):
            if progress_cb and total > 0:
                progress_cb(int(b*bs*100/total), f"vulkan ({b*bs//1024//1024}MB)")
        urllib.request.urlretrieve(v_url, str(archive_path), _r)
        
        needed = {"llama-server.exe", "llama-server-impl.dll", "ggml.dll",
                  "ggml-base.dll", "ggml-vulkan.dll", "mtmd.dll",
                  "ggml-rpc.dll", "ggml-rpc-server.exe",
                  "llama.dll", "llama-common.dll",
                  "llama-server-impl.dll", "llama-batched-bench-impl.dll",
                  "libomp140.x86_64.dll"}
        
        import zipfile
        with zipfile.ZipFile(str(archive_path)) as zf:
            for name in zf.namelist():
                bn = os.path.basename(name)
                if bn in needed:
                    zf.extract(name, str(vulkan_dir))
                    src = vulkan_dir / name
                    dst = vulkan_dir / bn
                    if src != dst:
                        shutil.move(str(src), str(dst))
                        p = src.parent
                        while p != vulkan_dir:
                            try: p.rmdir()
                            except OSError: break
                            p = p.parent
        archive_path.unlink()
        
        # Copy CPU DLLs from main build for fallback
        cpu_dir = _get_llama_dir()
        for f in cpu_dir.iterdir():
            if f.name.startswith('ggml-cpu-') and not (vulkan_dir / f.name).exists():
                shutil.copy2(str(f), str(vulkan_dir / f.name))
        
        # Patch CRT
        patched = _patch_dll_imports(vulkan_dir)
        if patched:
            logger.info(f"🔧 Vulkan CRT patched: {patched}")
        
        logger.info(f"✅ Vulkan build installed: {bin_path}")
        return True
    except Exception as e:
        logger.warning(f"⚠️ Vulkan download failed: {e}")
        return False


def _patch_dll_imports(dll_dir: Path) -> int:
    """Заменяет api-ms-win-crt-* → ucrtbase.dll в PE-импортах всех DLL в папке.
    
    На Windows Insider (build >= 26000) Microsoft удалила виртуальные API Set
    DLL (api-ms-win-crt-*). Функции из них есть в ucrtbase.dll — меняем имя DLL.
    
    Returns: количество пропатченных импортов.
    """
    import struct
    patched = 0
    for fpath in dll_dir.iterdir():
        if fpath.suffix.lower() not in (".dll", ".exe"):
            continue
        try:
            data = bytearray(fpath.read_bytes())
        except Exception:
            continue

        try:
            pe_off = struct.unpack_from('<I', data, 0x3C)[0]
            if data[pe_off:pe_off + 4] != b'PE\x00\x00':
                continue

            opt = pe_off + 24
            magic = struct.unpack_from('<H', data, opt)[0]
            ds = opt + (96 if magic == 0x10b else 112)
            irva = struct.unpack_from('<I', data, ds + 8)[0]
            if irva == 0:
                continue

            so = ds + 128
            ns = struct.unpack_from('<H', data, pe_off + 6)[0]

            def _r2r(rva):
                for i in range(ns):
                    s = so + i * 40
                    sv = struct.unpack_from('<I', data, s + 12)[0]
                    ss = struct.unpack_from('<I', data, s + 8)[0]
                    sr = struct.unpack_from('<I', data, s + 20)[0]
                    if sv <= rva < sv + ss:
                        return sr + (rva - sv)
                return None

            itr = _r2r(irva)
            if itr is None:
                continue

            changed = 0
            pos = itr
            while True:
                nth = struct.unpack_from('<I', data, pos)[0]
                nr = struct.unpack_from('<I', data, pos + 12)[0]
                if nth == 0 and nr == 0:
                    break
                dnr = _r2r(nr)
                if dnr is not None:
                    end = data.index(b'\x00', dnr)
                    dn = data[dnr:end].decode('ascii', errors='replace')
                    if dn.lower().startswith('api-ms-win-crt-'):
                        new_name = b'ucrtbase.dll\x00'
                        old_len = end - dnr
                        if len(new_name) <= old_len:
                            data[dnr:dnr + len(new_name)] = new_name
                            for i in range(dnr + len(new_name), dnr + old_len):
                                data[i] = 0
                            changed += 1
                pos += 20

            if changed:
                fpath.write_bytes(bytes(data))
                patched += changed
                logger.debug(f"  🔄 {fpath.name}: {changed} imports patched")
        except Exception:
            logger.warning(f"⚠️ PE patch failed for {fpath.name}, skipping")
            continue

    return patched


# Хэш известного релиза llama.cpp b9940 для проверки целостности скачанного архива.
# При обновлении LLAMA_VERSION нужно пересчитать хэш:
#   python -c "import hashlib; print(hashlib.sha256(open('llama-...zip','rb').read()).hexdigest())"
# Если проверка не проходит — бинарник не будет установлен.
# win-cpu-x64 + win-vulkan-x64: посчитаны 2026-07-11 для b9940.
LLAMA_BIN_SHA256 = {
    "win-cpu-x64": "d5d7248c7aacaeb0c8f15311acb0f1081874aa7a5de55843702e9e2394a05788",
    "win-vulkan-x64": "036835f0adb53b5d48444ab9adb7c29fff898be6fa74f7f9fc15f674ea38b153",
    "macos-arm64": "",  # вычислить: hashlib.sha256(open('llama-...tar.gz','rb').read()).hexdigest()
    "macos-x64": "",
    "ubuntu-x64": "",
}


def _verify_archive_sha256(archive_path: Path, tag: str) -> bool:
    """Проверяет SHA256 скачанного архива, если хэш известен."""
    expected = LLAMA_BIN_SHA256.get(tag)
    if not expected:
        logger.warning(f"⚠️ SHA256 для {tag} не задан, пропускаем проверку")
        return True
    try:
        actual = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        if actual == expected:
            logger.info(f"✅ SHA256 {tag}: {actual[:16]}... совпадает")
            return True
        logger.error(f"❌ SHA256 не совпадает! Ожидался {expected}, получен {actual[:16]}...")
        archive_path.unlink()
        return False
    except Exception as e:
        logger.error(f"❌ Ошибка проверки SHA256: {e}")
        return False


def download_llama_binary(progress_cb=None) -> bool:
    """Скачивает и распаковывает llama.cpp бинарник.
    
    На Windows Insider (build >= 26000) после распаковки патчит PE-импорты
    всех DLL: заменяет api-ms-win-crt-* → ucrtbase.dll, так как на Insider
    виртуальные CRT API Set DLL удалены Microsoft.
    """
    target_dir = _get_llama_dir()
    bin_path = _llama_bin()

    target_dir.mkdir(parents=True, exist_ok=True)

    archive_path = target_dir / LLAMA_BIN_ZIP
    if archive_path.exists() and bin_path.exists():
        logger.info(f"✅ llama.cpp уже установлен: {bin_path}")
        return True

    logger.info(f"⬇️  Скачиваю llama.cpp ({LLAMA_BIN_TAG}): {LLAMA_BIN_URL}")

    try:
        # Скачиваем архив
        def _report(b, bs, total):
            if progress_cb:
                pct = int(b * bs * 100 / total) if total > 0 else 0
                progress_cb(pct, f"llama.cpp ({b*bs//1024//1024}MB / {total//1024//1024}MB)")

        urllib.request.urlretrieve(LLAMA_BIN_URL, str(archive_path), _report)

        # Проверка целостности скачанного архива
        if not _verify_archive_sha256(archive_path, LLAMA_BIN_TAG):
            logger.error("🚫 Отказ от установки: SHA256 не прошёл проверку")
            return False

        # Список нужных файлов (платформозависимый)
        if sys.platform == "win32":
            needed = {"llama-server.exe", "llama-server-impl.dll", "ggml.dll",
                      "ggml-base.dll", "ggml-cpu-x64.dll", "ggml-cpu-haswell.dll",
                      "ggml-cpu-zen4.dll", "ggml-cpu-sandybridge.dll",
                      "ggml-cpu-ivybridge.dll", "ggml-cpu-alderlake.dll",
                      "ggml-cpu-cannonlake.dll", "ggml-cpu-cascadelake.dll",
                      "ggml-cpu-cooperlake.dll", "ggml-cpu-skylakex.dll",
                      "ggml-cpu-piledriver.dll", "ggml-cpu-sapphirerapids.dll",
                      "ggml-cpu-sse42.dll", "ggml-rpc.dll", "ggml-rpc-server.exe",
                      "llama.dll", "llama-common.dll",
                      "llama-server-impl.dll", "llama-batched-bench-impl.dll",
                      "libomp140.x86_64.dll", "mtmd.dll"}
            extract = lambda zf, name, dst: zf.extract(name, str(dst))
            move = lambda src, dst: shutil.move(str(src), str(dst))
        else:
            # macOS/Linux — всё из bin/ в llama/
            needed = None  # extract all
            extract = lambda zf, name, dst: zf.extract(name, str(dst))
            move = lambda src, dst: shutil.move(str(src), str(dst))

        if _ZIP_EXT == ".zip":
            import zipfile
            zf = zipfile.ZipFile(str(archive_path), "r")
            for name in zf.namelist():
                basename = os.path.basename(name)
                if needed is None or basename in needed:
                    extract(zf, name, target_dir)
                    extracted = target_dir / name
                    if extracted != target_dir / basename:
                        move(extracted, target_dir / basename)
            zf.close()
        else:
            # tar.gz
            import tarfile
            with tarfile.open(str(archive_path), "r:gz") as tf:
                for member in tf.getmembers():
                    basename = os.path.basename(member.name)
                    if needed is None or basename in needed:
                        tf.extract(member, str(target_dir))
                        extracted = target_dir / member.name
                        if extracted != target_dir / basename:
                            move(extracted, target_dir / basename)

        # Удаляем архив
        archive_path.unlink()

        # Делаем исполняемым (macOS/Linux)
        if sys.platform != "win32":
            bin_path.chmod(0o755)
            for f in target_dir.iterdir():
                if f.suffix in (".dylib", ".so"):
                    f.chmod(0o755)

        # На Insider (build >= 26000): патчим api-ms-win-crt-* → ucrtbase во всех DLL
        if _IS_INSIDER and sys.platform == "win32":
            patched = _patch_dll_imports(target_dir)
            if patched > 0:
                logger.info(f"🔧 api-ms-win-crt-* → ucrtbase.dll: {patched} imports patched in {target_dir.name}")

        # Vulkan: если есть GPU — скачиваем Vulkan build и добавляем CPU fallback
        if _HAVE_VULKAN and sys.platform == "win32" and not _IS_INSIDER:
            _install_vulkan_build(logger, progress_cb)

        logger.info(f"✅ llama.cpp установлен: {bin_path} (build={LLAMA_BIN_TAG})")
        return True

    except Exception as e:
        logger.error(f"❌ Ошибка скачивания llama.cpp: {e}")
        if archive_path.exists():
            archive_path.unlink()
        return False


def download_gguf_model(model_key: str, progress_cb=None) -> bool:
    """Скачивает GGUF модель из Hugging Face."""
    models_dir = _get_models_dir()
    models_dir.mkdir(parents=True, exist_ok=True)

    info = GGUF_MODELS[model_key]
    gguf_path = _gguf_path(model_key)

    if gguf_path.exists():
        logger.info(f"✅ GGUF модель уже скачана: {gguf_path.name}")
        return True

    # Скачиваем через huggingface_hub (если есть) или urllib
    from huggingface_hub import hf_hub_download

    logger.info(f"⬇️  Скачиваю GGUF: {info['repo']}/{info['file']}")

    def _on_progress(cb):
        """Оборачивает callback в формат huggingface_hub."""
        class _Progress:
            def __init__(self):
                self._last_pct = -1
            def __call__(self, current, total):
                if total > 0:
                    pct = int(current * 100 / total)
                    if pct != self._last_pct:
                        self._last_pct = pct
                        mb = current / (1024 * 1024)
                        total_mb = total / (1024 * 1024)
                        if progress_cb:
                            progress_cb(pct, f"{gguf_path.name} ({mb:.0f}MB/{total_mb:.0f}MB)")
        return _Progress()

    try:
        path = hf_hub_download(
            repo_id=info["repo"],
            filename=info["file"],
            cache_dir=str(models_dir.parent / ".hf_cache"),
        )
        # Копируем в models_dir (hf_hub хранит в своей структуре)
        if Path(path) != gguf_path:
            shutil.copy2(path, str(gguf_path))
        logger.info(f"✅ GGUF модель скачана: {gguf_path} ({info['size_mb']} MB)")
        if progress_cb:
            progress_cb(100, f"{gguf_path.name} — готов")
        return True

    except Exception as e:
        logger.error(f"❌ Ошибка скачивания GGUF модели {model_key}: {e}")
        if progress_cb:
            progress_cb(0, f"Ошибка: {e}")
        return False


def install_all(progress_cb=None) -> bool:
    """Полная установка: llama.cpp + обе GGUF модели."""
    ok = True

    def _p(pct, msg):
        if progress_cb:
            progress_cb(pct, msg)

    # 1. Бинарник llama
    _p(5, "Скачиваю llama.cpp...")
    if not download_llama_binary(lambda p, m: _p(int(p * 0.15), m)):
        ok = False

    # 2. Embedder GGUF
    _p(20, "Скачиваю bge-m3 (embedder)...")
    if not download_gguf_model("bge-m3", lambda p, m: _p(20 + int(p * 0.4), m)):
        ok = False

    # 3. Reranker GGUF
    _p(60, "Скачиваю bge-reranker-v2-m3...")
    if not download_gguf_model("bge-reranker-v2-m3", lambda p, m: _p(60 + int(p * 0.35), m)):
        ok = False

    _p(100, "Установка завершена!")
    return ok


# ─── System Info ────────────────────────────────────────────────

def get_system_summary() -> dict:
    """Возвращает сводку о системе для отчёта установки.

    Returns:
        {
            "os": "Windows 11",
            "arch": "x86_64",
            "python": "3.14.0",
            "cpu": "AMD Ryzen 5 5600H",
            "cores": 12,
            "ram_gb": 16,
            "avx2": True,
            "avx512": False,
            "provider": "llama.cpp",
            "provider_ram_mb": 523,
        }
    """
    os_name = sys.platform
    if sys.platform == "win32":
        try:
            out = subprocess.check_output(
                ["wmic", "os", "get", "caption"], timeout=5
            ).decode()
            for line in out.splitlines():
                if line.strip() and "caption" not in line.lower():
                    os_name = line.strip()
                    break
        except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
            os_name = f"Windows {sys.getwindowsversion().major}"
    elif sys.platform == "darwin":
        try:
            out = subprocess.check_output(
                ["sw_vers", "-productVersion"], timeout=5
            )
            os_name = f"macOS {out.decode().strip()}"
        except Exception:
            os_name = "macOS"
    elif sys.platform == "linux":
        try:
            out = subprocess.check_output(
                ["lsb_release", "-ds"], timeout=5
            )
            os_name = out.decode().strip()
        except Exception:
            os_name = "Linux"

    provider = "llama.cpp" if is_installed() else "ONNX server"
    provider_ram = 523 if is_installed() else 1689

    return {
        "os": os_name,
        "arch": _CPU_INFO.get("arch", "x86_64"),
        "python": sys.version.split()[0],
        "cpu": _CPU_INFO.get("name", "unknown"),
        "cores": _CPU_INFO.get("cores", os.cpu_count() or 4),
        "ram_gb": _CPU_INFO.get("ram_gb", 8),
        "avx2": _CPU_INFO.get("avx2", False),
        "avx512": _CPU_INFO.get("avx512", False),
        "provider": provider,
        "provider_ram_mb": provider_ram,
    }


# ─── Runtime ────────────────────────────────────────────────────

class LlamaRunner:
    """Управляет жизненным циклом llama.cpp сервера.

    Использование:
        runner = LlamaRunner()
        await runner.start()
        health = await runner.health()
        await runner.stop()
    """

    RERANK_PORT = int(os.getenv("LLAMA_CPP_RERANK_PORT", "8081"))
    MAX_RAM_MB = int(os.getenv("LLAMA_MAX_RAM_MB", "1024"))  # авто-рестарт при превышении

    def __init__(self):
        self._process: Optional[subprocess.Popen] = None
        self._model_key: Optional[str] = None
        self._reranker_process: Optional[subprocess.Popen] = None
        self._host = LLAMA_HOST
        self._port = LLAMA_PORT
        self._startup_timeout = 30
        # Watchdog — авто-рестарт при утечке памяти
        self._watchdog_stop = threading.Event()
        self._watchdog_thread: Optional[threading.Thread] = None

    def _start_watchdog(self):
        """Фоновый мониторинг RAM llama-server. Перезапуск при превышении лимита."""
        if self._watchdog_thread is not None and self._watchdog_thread.is_alive():
            return
        self._watchdog_stop.clear()
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            name="llama-watchdog",
            daemon=True,
        )
        self._watchdog_thread.start()
        logger.debug(f"🔍 Watchdog запущен (лимит {self.MAX_RAM_MB} MB)")

    def _watchdog_loop(self):
        while not self._watchdog_stop.wait(30):
            for proc, name in [(self._process, "embedder"), (self._reranker_process, "reranker")]:
                if proc is None:
                    continue
                try:
                    pid = proc.pid
                    import subprocess as _sp
                    out = _sp.check_output(
                        ['powershell', '-NoProfile', '-Command',
                         f'Get-Process -Id {pid} | Select-Object -ExpandProperty WorkingSet64'],
                        timeout=5
                    ).decode().strip()
                    ram_mb = int(out) // (1024*1024)
                    if ram_mb > self.MAX_RAM_MB:
                        logger.warning(f"🚨 {name} RAM {ram_mb}MB > лимит {self.MAX_RAM_MB}MB. Перезапуск...")
                        if name == "embedder":
                            self._restart_embedder()
                        else:
                            self._restart_reranker()
                except Exception as _wtf:
                    logger.error(f"Watchdog error ({name} PID={pid}): {_wtf}")

    def _restart_embedder(self):
        model_key = self._model_key or DEFAULT_EMBEDDING_MODEL
        # Асинхронный рестарт в синхронном потоке
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.stop())
        loop.run_until_complete(self.start(model_key))
        loop.close()

    def _restart_reranker(self):
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.stop_reranker())
        loop.run_until_complete(self.start_reranker())
        loop.close()
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    @property
    def reranker_url(self) -> str:
        return f"http://{self._host}:{self.RERANK_PORT}"

    async def start(self, model_key: str = DEFAULT_EMBEDDING_MODEL) -> bool:
        """Запускает llama-server (просто Popen, без health check)."""
        if self.is_alive() and self._model_key == model_key:
            return True

        gguf_path = _gguf_path(model_key)
        if not gguf_path.exists():
            logger.error(f"GGUF модель не найдена: {gguf_path}")
            return False

        flags = ["--embedding"] if model_key in ("bge-m3", "qwen3-embedding") else ["--reranking"]
        
        try:
            self._process = subprocess.Popen(
                [
                    str(_llama_bin_vulkan()) if os.getenv("LLAMA_BACKEND","msvc").lower()=="vulkan" else str(_llama_bin()),
                    "--host", self._host,
                    "--port", str(self._port),
                    "-m", str(gguf_path),
                    "-c", str(LLAMA_CTX_SIZE),
                    "--batch-size", "512",
                    "--ubatch-size", "512",
                    "--cache-type-k", str(LLAMA_CACHE_TYPE),
                    "--cache-type-v", str(LLAMA_CACHE_TYPE),
                    "--no-webui",
                    "-ngl", str(int(os.getenv("LLAMA_NGL","99"))) if os.getenv("LLAMA_BACKEND","msvc").lower()=="vulkan" else "0",
                    *flags,
                ],
                stdout=subprocess.DEVNULL,
                stderr=open(self._log_path(), 'a'),
                cwd=str(_llama_bin_vulkan().parent) if os.getenv("LLAMA_BACKEND","msvc").lower()=="vulkan" else str(_llama_bin().parent),
            )
            self._model_key = model_key
            logger.info(f"🚀 llama-server ({model_key}) синхронно запущен, PID={self._process.pid}")
            return True

        except Exception as e:
            logger.error(f"Ошибка запуска llama.cpp: {e}")
            return False

    def _start_sync(self, model_key: str = DEFAULT_EMBEDDING_MODEL) -> bool:
        """Синхронная версия start() — без asyncio, для вызова из run_server().
        
        На Insider: если CPU DLL пропали (Zed сбросил расширение) —
        автоматически качает и патчит бинарник.
        """
        if self.is_alive() and self._model_key == model_key:
            return True

        # На Insider: проверяем наличие CPU DLL и восстанавливаем если надо
        if _IS_INSIDER and sys.platform == 'win32':
            cpu_dll = _llama_bin().parent / 'ggml-cpu-haswell.dll'
            if not cpu_dll.exists():
                logger.warning('⚠️ CPU DLL не найдены — запускаю download_llama_binary()')
                if download_llama_binary():
                    logger.info('✅ llama.cpp восстановлен после авто-загрузки')
                else:
                    logger.error('❌ Не удалось восстановить llama.cpp')
                    return False

        gguf_path = _gguf_path(model_key)
        if not gguf_path.exists():
            logger.error(f"GGUF модель не найдена: {gguf_path}")
            return False

        flags = ["--embedding"] if model_key in ("bge-m3", "qwen3-embedding") else ["--reranking"]

        try:
            self._process = subprocess.Popen(
                [
                    str(_llama_bin_vulkan()) if os.getenv("LLAMA_BACKEND","msvc").lower()=="vulkan" else str(_llama_bin()),
                    "--host", self._host,
                    "--port", str(self._port),
                    "-m", str(gguf_path),
                    "-c", str(LLAMA_CTX_SIZE),
                    "--batch-size", "512",
                    "--ubatch-size", "512",
                    "--cache-type-k", str(LLAMA_CACHE_TYPE),
                    "--cache-type-v", str(LLAMA_CACHE_TYPE),
                    "--no-webui",
                    "-ngl", str(int(os.getenv("LLAMA_NGL","99"))) if os.getenv("LLAMA_BACKEND","msvc").lower()=="vulkan" else "0",
                                        *flags,
                                    ],
                                    stdout=subprocess.DEVNULL,
                                    stderr=open(self._log_path(), 'a'),
                                    cwd=str(_llama_bin_vulkan().parent) if os.getenv("LLAMA_BACKEND","msvc").lower()=="vulkan" else str(_llama_bin().parent),
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
                if sys.platform == "win32" else 0,
            )
            self._model_key = model_key
            logger.info(f"🚀 llama-server ({model_key}) синхронно запущен, PID={self._process.pid}")
            return True

        except Exception as e:
            logger.error(f"Ошибка синхронного запуска llama.cpp: {e}")
            return False

    async def start_reranker(self) -> bool:
        """Запускает llama-server с --reranking (BGE-M3 на порту RERANK_PORT)."""
        if self._reranker_process is not None:
            poll = self._reranker_process.poll()
            if poll is None:
                return True  # уже работает

        gguf_path = _gguf_path(DEFAULT_RERANKER_MODEL)
        if not gguf_path.exists():
            logger.error(f"Reranker GGUF не найден: {gguf_path}")
            return False

        self._ensure_port_free(self.RERANK_PORT)

        try:
            self._reranker_process = subprocess.Popen(
                [
                    str(_llama_bin_vulkan()) if os.getenv("LLAMA_BACKEND","msvc").lower()=="vulkan" else str(_llama_bin()),
                    "--host", self._host,
                    "--port", str(self.RERANK_PORT),
                    "-m", str(gguf_path),
                    "-c", str(LLAMA_CTX_SIZE),     # 🔒 1024 = 573 MB для BGE-M3
                    "--batch-size", "512",
                    "--ubatch-size", "512",
                    "--cache-type-k", str(LLAMA_CACHE_TYPE), # 🧹 сжатие KV кэша
                    "--cache-type-v", str(LLAMA_CACHE_TYPE), # 🧹 сжатие KV кэша
                    "--no-webui",
                    "-ngl", str(int(os.getenv("LLAMA_NGL","99"))) if os.getenv("LLAMA_BACKEND","msvc").lower()=="vulkan" else "0",
                    "--reranking",
                ],
                stdout=subprocess.DEVNULL,
                stderr=open(self._reranker_log_path(), 'a'),
                cwd=str(_llama_bin_vulkan().parent) if os.getenv("LLAMA_BACKEND","msvc").lower()=="vulkan" else str(_llama_bin().parent),
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
                if sys.platform == "win32" else 0,
            )



            # Ждём /health
            t0 = time.time()
            async with httpx.AsyncClient(timeout=2.0) as client:
                for i in range(self._startup_timeout):
                    await asyncio.sleep(1)
                    try:
                        r = await client.get(f"http://{self._host}:{self.RERANK_PORT}/health")
                        if r.status_code == 200:
                            dt = time.time() - t0
                            logger.info(f"🚀 Reranker (BGE-M3) готов за {dt:.1f}s")
                            return True
                    except Exception:
                        pass

            logger.error(f"Reranker не стартовал за {self._startup_timeout}s")
            await self.stop_reranker()
            return False

        except Exception as e:
            logger.error(f"Ошибка запуска reranker: {e}")
            return False

    async def stop_reranker(self):
        """Останавливает reranker."""
        if self._reranker_process:
            try:
                self._reranker_process.terminate()
                self._reranker_process.wait(timeout=5)
            except Exception:
                try:
                    self._reranker_process.kill()
                    self._reranker_process.wait(timeout=2)
                except Exception:
                    pass
            self._reranker_process = None
            logger.info("🛑 Reranker остановлен")

    async def stop(self):
        """Останавливает embedder (reranker не трогаем)."""
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                    self._process.wait(timeout=2)
                except Exception:
                    pass
            self._process = None
            self._model_key = None
            logger.info("🛑 llama.cpp остановлен")

    def _log_path(self) -> str:
        """Путь к лог-файлу для stderr llama-server."""
        return str(_get_ext_dir() / 'llama_server_stderr.log')

    def _reranker_log_path(self) -> str:
        return str(_get_ext_dir() / 'llama_reranker_stderr.log')

    def _ensure_port_free(self, port: int):
        """Освобождает порт, убивая только процесс llama-server (по команде)."""
        import subprocess as _sp
        # Проверяем, что порт в ожидаемом диапазоне (8080-8090 для llama.cpp)
        if not (8080 <= port <= 8090):
            logger.warning(f"⚠️ Порт {port} вне диапазона llama.cpp (8080-8090), пропускаем")
            return
        try:
            # Шаг 1: находим PID процесса на порту
            out = _sp.check_output(
                ['powershell', '-NoProfile', '-Command',
                 f'Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess'],
                timeout=5
            ).decode().strip()
            for line in out.split('\n'):
                pid = line.strip()
                if not (pid and pid.isdigit() and int(pid) > 0):
                    continue
                # Шаг 2: проверяем CommandLine процесса — убиваем только llama-server
                try:
                    cmd = _sp.check_output(
                        ['powershell', '-NoProfile', '-Command',
                         f'Get-CimInstance -ClassName Win32_Process -Filter "ProcessId = {pid}" | Select-Object -ExpandProperty CommandLine'],
                        timeout=3
                    ).decode().strip().lower()
                    if 'llama-server' not in cmd and 'ggml-rpc-server' not in cmd:
                        logger.warning(f'⏭️ Порт {port} занят процессом PID {pid} (не llama-server), пропускаем')
                        continue
                except Exception:
                    # Не смогли проверить — не убиваем
                    logger.warning(f'⚠️ Не удалось проверить PID {pid} на порту {port}, пропускаем')
                    continue
                # Шаг 3: убиваем
                _sp.run(['taskkill', '/F', '/PID', pid], capture_output=True, timeout=3)
                logger.warning(f'🧹 Убит процесс llama-server PID {pid} (порт {port})')
        except Exception as e:
            logger.warning(f'⚠️ Ошибка при освобождении порта {port}: {e}')

    def is_alive(self) -> bool:
        """Проверяет, жив ли процесс."""
        if self._process is None:
            return False
        ret = self._process.poll()
        return ret is None

    async def health(self) -> dict:
        """Проверяет здоровье сервера."""
        if not self.is_alive():
            return {"status": "dead", "model": None}
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(f"{self.base_url}/health")
                if r.status_code == 200:
                    data = r.json()
                    return {
                        "status": "ok",
                        "model": self._model_key,
                        "uptime": data.get("uptime_sec", 0),
                    }
                return {"status": "error", "model": self._model_key}
        except Exception:
            return {"status": "unreachable", "model": self._model_key}

    async def embed(self, texts: list[str]) -> Optional[list[list[float]]]:
        """Отправляет запрос на эмбеддинги."""
        if self._model_key != "bge-m3":
            # Автоматический рестарт с embedder
            if not await self.start("bge-m3"):
                return None
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(
                    f"{self.base_url}/v1/embeddings",
                    json={"input": texts},
                )
                if r.status_code == 200:
                    data = r.json()
                    return [item["embedding"] for item in data.get("data", [])]
                return None
        except Exception as e:
            logger.debug(f"llama.cpp embed error: {e}")
            return None

    async def rerank(self, query: str, passages: list[str]) -> Optional[list[float]]:
        """Отправляет запрос на реранкинг."""
        if self._model_key != "bge-reranker-v2-m3":
            if not await self.start("bge-reranker-v2-m3"):
                return None
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(
                    f"{self.base_url}/v1/rerank",
                    json={"query": query, "documents": passages, "top_n": len(passages)},
                )
                if r.status_code == 200:
                    results = r.json().get("results", [])
                    scores = [0.0] * len(passages)
                    for res in results:
                        idx = res.get("index", 0)
                        # Sigmoid нормализация (llama.cpp возвращает logits)
                        logit = res.get("relevance_score", 0.0)
                        scores[idx] = 1.0 / (1.0 + (2.71828 ** (-logit)))
                    return scores
                return None
        except Exception as e:
            logger.debug(f"llama.cpp rerank error: {e}")
            return None


# ─── Singleton ───────────────────────────────────────────────────

_global_runner: Optional[LlamaRunner] = None
_global_lock = threading.Lock()


def get_global_runner() -> LlamaRunner:
    """Возвращает глобальный LlamaRunner (singleton)."""
    global _global_runner
    with _global_lock:
        if _global_runner is None:
            _global_runner = LlamaRunner()
        return _global_runner


def reset_global_runner():
    """Сброс singleton (для тестов)."""
    global _global_runner
    with _global_lock:
        _global_runner = None



__all__ = [
    "LlamaRunner",
    "get_global_runner",
    "is_installed",
    "download_llama_binary",
    "download_gguf_model",
    "install_all",
]
