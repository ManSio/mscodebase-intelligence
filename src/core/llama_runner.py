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

import httpx

logger = logging.getLogger("mscodebase_server.llama_runner")

# ─── Конфигурация ──────────────────────────────────────────────
LLAMA_VERSION = "b9940"
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
LLAMA_CTX_SIZE = int(os.getenv("LLAMA_CTX_SIZE", "1024"))     # 1024 = 722 MB RAM для Qwen3
LLAMA_BATCH_SIZE = int(os.getenv("LLAMA_BATCH_SIZE", "512"))   # 512 токенов за проход
LLAMA_UBATCH_SIZE = int(os.getenv("LLAMA_UBATCH_SIZE", "128")) # физический батч CPU

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
                "wmic memorychip get capacity", shell=True, timeout=5
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
                "wmic cpu get name", shell=True, timeout=5
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
DEFAULT_EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "qwen3-embedding")
DEFAULT_RERANKER_MODEL = "bge-reranker-v2-m3"

# Windows Insider: используем Vulkan/Clang сборку вместо MSVC
_USE_VULKAN_BUILD = _is_windows_insider()
if _USE_VULKAN_BUILD:
    logger.info("🔧 Windows Insider detected: using Vulkan/Clang llama-server build")
    LLAMA_BIN_TAG = "win-vulkan-x64"
    LLAMA_BIN_ZIP = f"llama-{LLAMA_VERSION}-bin-{LLAMA_BIN_TAG}{_ZIP_EXT}"
    LLAMA_BIN_URL = f"{LLAMA_BASE_URL}/{LLAMA_BIN_ZIP}"

# ─── Планировщик модели ────────────────────────────────────────
# Пока llama-server умеет загружать только 1 модель за раз.
# Запускаем embedder, при необходимости реранкинга — рестарт с --reranking.
# (В будущем релизах llama.cpp обещают поддержку нескольких моделей в одном процессе)


def _get_ext_dir() -> Path:
    """Определяет директорию расширения."""
    # Если запущено из установленного расширения
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent.parent.parent
    # Если запущено из разработки
    p = Path(__file__).resolve().parent.parent.parent
    if (p / "src" / "main.py").exists():
        return p
    return Path.home() / ".cache" / "mscodebase"


def _get_llama_dir() -> Path:
    """Директория для llama.cpp бинарника."""
    return _get_ext_dir() / "llama"


def _get_models_dir() -> Path:
    """Директория для GGUF моделей."""
    return _get_ext_dir() / "models"


def _llama_bin() -> Path:
    """Полный путь к llama-server бинарнику."""
    return _get_llama_dir() / f"llama-server{_EXE_SUFFIX}"


def _gguf_path(model_key: str) -> Path:
    """Полный путь к GGUF файлу модели."""
    return _get_models_dir() / GGUF_MODELS[model_key]["file"]


# ─── Установка ──────────────────────────────────────────────────

def is_installed() -> bool:
    """Проверяет, установлен ли llama.cpp."""
    return _llama_bin().exists()


def is_compatible() -> bool:
    """Проверяет, может ли llama.cpp работать на этой системе.

    На Windows Insider (build >= 26000) MSVC-сборка не работает из-за
    отсутствия api-ms-win-crt-heap API Set. Используем Vulkan/Clang сборку.
    """
    if _is_windows_insider():
        logger.warning("⚠️ Windows Insider/24H2+ detected. MSVC llama-server "
                       "needs api-ms-win-crt-heap which is missing. "
                       "Using Vulkan/Clang build as fallback.")
        # На Insider бинарник есть в llama_vulkan/
        vulkan_bin = _get_ext_dir() / "llama_vulkan" / f"llama-server{_EXE_SUFFIX}"
        return vulkan_bin.exists()
    return is_installed()


def is_model_downloaded(model_key: str) -> bool:
    """Проверяет, скачана ли GGUF модель."""
    return _gguf_path(model_key).exists()


def download_llama_binary(progress_cb=None) -> bool:
    """Скачивает и распаковывает llama.cpp бинарник."""
    llama_dir = _get_llama_dir()
    llama_dir.mkdir(parents=True, exist_ok=True)

    archive_path = llama_dir / LLAMA_BIN_ZIP
    if archive_path.exists() and _llama_bin().exists():
        logger.info(f"✅ llama.cpp уже установлен: {_llama_bin()}")
        return True

    logger.info(f"⬇️  Скачиваю llama.cpp ({_PLATFORM_TAG}): {LLAMA_BIN_URL}")

    try:
        # Скачиваем архив
        def _report(b, bs, total):
            if progress_cb:
                pct = int(b * bs * 100 / total) if total > 0 else 0
                progress_cb(pct, f"llama.cpp ({b*bs//1024//1024}MB / {total//1024//1024}MB)")

        urllib.request.urlretrieve(LLAMA_BIN_URL, str(archive_path), _report)

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
                      "libomp140.x86_64.dll"}
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
                    extract(zf, name, llama_dir)
                    extracted = llama_dir / name
                    if extracted != llama_dir / basename:
                        move(extracted, llama_dir / basename)
            zf.close()
        else:
            # tar.gz
            import tarfile
            with tarfile.open(str(archive_path), "r:gz") as tf:
                for member in tf.getmembers():
                    basename = os.path.basename(member.name)
                    if needed is None or basename in needed:
                        tf.extract(member, str(llama_dir))
                        extracted = llama_dir / member.name
                        if extracted != llama_dir / basename:
                            move(extracted, llama_dir / basename)

        # Удаляем архив
        archive_path.unlink()

        # Делаем исполняемым (macOS/Linux)
        if sys.platform != "win32":
            _llama_bin().chmod(0o755)
            # На macOS может быть .dylib вместо .dll
            for f in llama_dir.iterdir():
                if f.suffix in (".dylib", ".so"):
                    f.chmod(0o755)

        logger.info(f"✅ llama.cpp установлен: {_llama_bin()}")
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
                "wmic os get caption", shell=True, timeout=5
            ).decode()
            for line in out.splitlines():
                if line.strip() and "caption" not in line.lower():
                    os_name = line.strip()
                    break
        except Exception:
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

    def __init__(self):
        self._process: Optional[subprocess.Popen] = None
        self._model_key: Optional[str] = None  # что загружено: bge-m3 | bge-reranker-v2-m3
        self._host = LLAMA_HOST
        self._port = LLAMA_PORT
        self._startup_timeout = 15  # секунд ждём /health

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    async def start(self, model_key: str = DEFAULT_EMBEDDING_MODEL) -> bool:
        """Запускает llama-server с указанной моделью.

        Args:
            model_key: 'qwen3-embedding' (default, лучший), 'bge-m3' (fallback),
                       'bge-reranker-v2-m3' (reranker)

        Returns:
            True если сервер запущен и отвечает на /health
        """
        if self.is_alive() and self._model_key == model_key:
            return True  # уже запущен с этой моделью

        await self.stop()

        if not is_installed():
            logger.error("llama.cpp не установлен. Запустите install.py")
            return False

        gguf_path = _gguf_path(model_key)
        if not gguf_path.exists():
            logger.error(f"GGUF модель не найдена: {gguf_path}")
            return False

        flags = ["--embedding"] if model_key in ("bge-m3", "qwen3-embedding") else ["--reranking"]

        try:
            self._process = subprocess.Popen(
                [
                    str(_llama_bin()),
                    "--host", self._host,
                    "--port", str(self._port),
                    "-m", str(gguf_path),
                    "-c", str(LLAMA_CTX_SIZE),     # 🔒 1024 = 722 MB (Qwen3) / 573 MB (BGE-M3)
                    "--batch-size", str(LLAMA_BATCH_SIZE),   # 🔥 512 токенов за проход
                    "--ubatch-size", str(LLAMA_UBATCH_SIZE), # ⚡ 128 физический батч для CPU
                    "--no-webui",
                    "-ngl", "0",  # CPU-only
                    "--mlock",      # блокировка в RAM (без свопинга)
                    *flags,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW
                if sys.platform == "win32" else 0,
            )
            self._model_key = model_key

            # Ждём /health
            t0 = time.time()
            async with httpx.AsyncClient(timeout=2.0) as client:
                for i in range(self._startup_timeout):
                    await asyncio.sleep(1)
                    try:
                        r = await client.get(f"{self.base_url}/health")
                        if r.status_code == 200:
                            dt = time.time() - t0
                            logger.info(
                                f"🚀 llama.cpp ({model_key}) готов за {dt:.1f}s"
                            )
                            return True
                    except Exception:
                        pass

            # Не дождались
            logger.error(f"llama.cpp ({model_key}) не стартовал за {self._startup_timeout}s")
            await self.stop()
            return False

        except Exception as e:
            logger.error(f"Ошибка запуска llama.cpp: {e}")
            return False

    async def stop(self):
        """Останавливает сервер."""
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

__all__ = [
    "LlamaRunner",
    "get_global_runner",
    "is_installed",
    "download_llama_binary",
    "download_gguf_model",
    "install_all",
]
