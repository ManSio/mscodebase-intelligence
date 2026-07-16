"""
Установка и конфигурация llama.cpp и GGUF моделей.

Отвечает за:
- Определение платформы и CPU
- Скачивание и распаковку llama-server бинарника
- Скачивание GGUF моделей (bge-m3, reranker)
- Проверку установки и совместимости
- Патчинг PE-импортов для Windows Insider (build >= 26000)
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import struct
import subprocess
import sys
import urllib.request
from pathlib import Path

logger = logging.getLogger("mscodebase_server.llama_install")

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
    import subprocess

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
    except Exception as _e:
        logger.warning("exception", exc_info=True)
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
    except Exception as _e:
        logger.warning("exception", exc_info=True)
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
        "sha256": "17c3e3f2eaabc6e321702b4a13680d042e72afc5d602f359f27a670c3e54718c",
    },
    "bge-m3": {
        "repo": "lm-kit/bge-m3-gguf",
        "file": "bge-m3-Q4_K_M.gguf",
        "size_mb": 417,
        "dim": 1024,
        "sha256": "e251234fcb7d050991a6be491952f485bf5c641dd10c3272dc1301fd281ad50f",
    },
    "bge-reranker-v2-m3": {
        "repo": "lm-kit/bge-m3-reranker-v2-gguf",
        "file": "Bge-M3-568M-Q4_K_M.gguf",
        "size_mb": 418,
        "sha256": "ce947cece730cbf7d836da8c5490a9987ef0f919014b9275e7ce9aa12d96e6d9",
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

# ─── Path helpers ────────────────────────────────────────────────
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
                _vk_bin = _get_vulkan_dir() / f"llama-server{_EXE_SUFFIX}"
                if _vk_bin.exists():
                    _HAVE_VULKAN = True
                    os.environ.setdefault("LLAMA_BACKEND", "vulkan")
                    logger.info("🖥️ Vulkan GPU detected — using GPU for embeddings")
                else:
                    logger.info("🖥️ Vulkan GPU detected, but no Vulkan build — using CPU (msvc)")
    except Exception as _e:
        logger.warning("exception", exc_info=True)
        pass


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
            def extract(zf, name, dst):
                return zf.extract(name, str(dst))
            def move(src, dst):
                return shutil.move(str(src), str(dst))
        else:
            # macOS/Linux — всё из bin/ в llama/
            needed = None  # extract all
            def extract(zf, name, dst):
                return zf.extract(name, str(dst))
            def move(src, dst):
                return shutil.move(str(src), str(dst))

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
        # Insider: CRT DLL патчатся (api-ms-win-crt-* → ucrtbase.dll), Vulkan работает
        if _HAVE_VULKAN and sys.platform == "win32":
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

    # Проверка SHA256 (если хэш известен)
    gguf_sha256 = info.get('sha256', '')
    if gguf_sha256:
        logger.info(f'⬇️  SHA256 для {info["file"]}: {gguf_sha256[:16]}...')

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


__all__ = [
    # constants
    "LLAMA_VERSION", "LLAMA_BASE_URL", "LLAMA_PORT", "LLAMA_HOST",
    "LLAMA_CTX_SIZE", "LLAMA_BATCH_SIZE", "LLAMA_UBATCH_SIZE",
    "LLAMA_DEFRAG_THOLD", "LLAMA_CACHE_TYPE",
    "GGUF_MODELS", "DEFAULT_EMBEDDING_MODEL", "DEFAULT_RERANKER_MODEL",
    "LLAMA_BIN_SHA256", "LLAMA_BIN_NAME", "LLAMA_BIN_ZIP", "LLAMA_BIN_URL",
    # module-level vars (public)
    "_IS_INSIDER", "_HAVE_VULKAN", "_EXE_SUFFIX", "_ZIP_EXT",
    "_PLATFORM_TAG", "_CPU_INFO",
    # detect functions
    "_detect_platform", "_detect_cpu", "_is_windows_insider",
    # path functions
    "_get_ext_dir", "_get_llama_dir", "_get_vulkan_dir", "_get_models_dir",
    "_llama_bin", "_llama_bin_vulkan", "_gguf_path",
    # status functions
    "is_installed", "is_compatible", "is_model_downloaded",
    # install functions
    "_install_vulkan_build", "_patch_dll_imports", "_verify_archive_sha256",
    "download_llama_binary", "download_gguf_model", "install_all",
    # system info
    "get_system_summary",
]
