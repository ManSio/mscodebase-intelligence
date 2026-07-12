"""
MSCodebase Intelligence — Installer & Updater v3.0
=================================================
Robust TUI with error recovery, self-healing, and safe Windows I/O.
Design principles:
  - Every step wrapped in try/except with retry/skip/cancel
  - Progress bar via single \r line (no flicker)
  - Safe file ops (always ignore_errors on rmtree, handle long paths)
  - Model download with progress + retry
  - Ghost folder cleanup for Windows pip issues
  - KeyboardInterrupt handler restores terminal state
"""

import locale, logging, os, re, shutil, socket, subprocess, sys, time
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).resolve().parent / "src" / "utils"))
from zed_config import get_zed_config_dir, patch_zed_settings

PROJECT_ROOT = Path(__file__).resolve().parent
ZED_EXT_DIR = (
    Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")))
    / "Zed"
    / "extensions"
    / "mscodebase-intelligence"
)
VENV_DIR = ZED_EXT_DIR / "venv"
PYTHON_EXE = (
    VENV_DIR / "Scripts" / "python.exe"
    if sys.platform == "win32"
    else VENV_DIR / "bin" / "python3"
)
UNINSTALLER = ZED_EXT_DIR / "uninstall.bat"
LM_HOST = os.environ.get("LM_STUDIO_HOST", "127.0.0.1")
LM_PORT = int(os.environ.get("LM_STUDIO_PORT", "1234"))
TOTAL_STEPS = 12

# ─── i18n ────────────────────────────────────────────────────
LANG = {
    "title": {
        "en": "MSCodeBase Intelligence — Installer",
        "ru": "MSCodeBase Intelligence — Установщик",
        "zh": "MSCodeBase Intelligence — 安装程序",
    },
    "step": {"en": "Step", "ru": "Шаг", "zh": "步骤"},
    "of": {"en": "of", "ru": "из", "zh": "的"},
    "ok": {"en": "Done", "ru": "Готово", "zh": "完成"},
    "warn": {"en": "Warning", "ru": "Внимание", "zh": "警告"},
    "fail": {"en": "Failed", "ru": "Ошибка", "zh": "失败"},
    "skip": {"en": "Skipped", "ru": "Пропущено", "zh": "已跳过"},
    "retry": {"en": "[r]etry", "ru": "[r]etry", "zh": "[r]etry"},
    "skip_opt": {"en": "[s]kip", "ru": "[s]kip", "zh": "[s]kip"},
    "cancel": {"en": "[c]ancel", "ru": "[c]ancel", "zh": "[c]ancel"},
    "quit": {"en": "[q]uit", "ru": "[q]uit", "zh": "[q]uit"},
    "chk_zed": {"en": "Zed IDE", "ru": "Zed IDE", "zh": "Zed IDE"},
    "chk_lm": {"en": "LM Studio", "ru": "LM Studio", "zh": "LM Studio"},
    "chk_proc": {"en": "Stop processes", "ru": "Остановка процессов", "zh": "停止进程"},
    "chk_copy": {"en": "Copy files", "ru": "Копирование файлов", "zh": "复制文件"},
    "chk_venv": {
        "en": "Virtual environment",
        "ru": "Виртуальное окружение",
        "zh": "虚拟环境",
    },
    "chk_pip": {"en": "Install packages", "ru": "Установка пакетов", "zh": "安装依赖"},
    "chk_llama": {"en": "llama.cpp engine", "ru": "llama.cpp движок", "zh": "llama.cpp引擎"},
    "chk_gguf": {"en": "GGUF reranker model (bge-reranker-v2-m3)", "ru": "GGUF модель реранкера (bge-reranker-v2-m3)", "zh": "GGUF排序模型"},
    "chk_models": {"en": "ONNX models: E5-base (embedder) + BGE-M3 (reranker)", "ru": "ONNX модели: E5-base (эмбеддер) + BGE-M3 (реранкер)", "zh": "ONNX模型: E5-base嵌入 + BGE-M3排序"},
    "chk_db": {"en": "Database", "ru": "База данных", "zh": "数据库"},
    "chk_zedcfg": {"en": "Zed integration", "ru": "Интеграция в Zed", "zh": "Zed集成"},
    "chk_uninst": {"en": "Uninstaller", "ru": "Деинсталлятор", "zh": "卸载程序"},
    "done_all": {
        "en": "Installation complete!",
        "ru": "Установка завершена!",
        "zh": "安装完成！",
    },
    "next": {"en": "Next steps", "ru": "Следующие шаги", "zh": "后续步骤"},
    "restart": {
        "en": "Restart Zed IDE",
        "ru": "Перезапустите Zed IDE",
        "zh": "重启Zed",
    },
    "wait_idx": {
        "en": "Open project, wait for indexing",
        "ru": "Откройте проект, дождитесь индексации",
        "zh": "打开项目，等待索引",
    },
    "start_code": {
        "en": "Start coding!",
        "ru": "Начинайте кодить!",
        "zh": "开始编码！",
    },
    "dl_ask": {
            "en": "Download ONNX models (e5-base ~265 MB + reranker ~544 MB)? (Y/n)",
            "ru": "Скачать ONNX модели (e5-base ~265 МБ + реранкер ~544 МБ)? (Y/n)",
            "zh": "下载ONNX模型(e5-base ~265 MB + 排序 ~544 MB)？(Y/n)",
        },
    "models_ok": {
        "en": "ONNX models installed",
        "ru": "ONNX модели установлены",
        "zh": "ONNX模型已安装",
    },
    "dl_1": {
        "en": "Embedding: e5-base-v2 (multilingual, 768dim)",
        "ru": "Эмбеддер: e5-base-v2 (multilingual, 768dim)",
        "zh": "嵌入模型：e5-base-v2 (多语言, 768维)",
    },
    "dl_2": {
        "en": "Reranker: bge-reranker-v2-m3 (~550 MB)",
        "ru": "Реранкер: bge-reranker-v2-m3 (~550 МБ)",
        "zh": "重排序：bge-reranker-v2-m3 (~550 MB)",
    },
    "ghosts": {
        "en": "Cleaned ghost folders (~)",
        "ru": "Очищены папки-призраки (~)",
        "zh": "已清理幽灵文件夹(~)",
    },
    "lm_off": {
        "en": "LM Studio offline — using local ONNX",
        "ru": "LM Studio офлайн — используется локальный ONNX",
        "zh": "LM Studio离线—使用本地ONNX",
    },
}


def _tr(key, lang="en"):
    d = LANG.get(key, {})
    return d.get(lang, d.get("en", key))


def _detect_lang():
    try:
        full = locale.getlocale(locale.LC_MESSAGES)[0] or ""
        p = full[:2].lower()
        return {"ru": "ru", "uk": "ru", "zh": "zh", "cn": "zh"}.get(p, "en")
    except:
        return "en"


# ─── ANSI + TUI ────────────────────────────────────────────
BOX_W = 60  # фиксированная ширина, не зависит от терминала

class C:
    R = "\033[0m"
    B = "\033[1m"
    D = "\033[2m"
    RED = "\033[91m"
    GRN = "\033[92m"
    YEL = "\033[93m"
    CYN = "\033[96m"


def _ea():
    if sys.platform == "win32":
        os.system("")


def _vis_len(s: str) -> int:
    """Длина строки без ANSI кодов."""
    return len(re.sub(r"\033\[[0-9;]*m", "", s))


def _trunc(s: str, w: int) -> str:
    """Обрезает строку до w видимых символов с учётом ANSI."""
    clean = re.sub(r"\033\[[0-9;]*m", "", s)
    if len(clean) <= w:
        return s
    # Усекаем, сохраняя ANSI коды в начале
    ans = re.match(r"^(\033\[[0-9;]*m)*", s)
    prefix = ans.group(0) if ans else ""
    return prefix + clean[:w] + C.R


def _box(title, inner, color=C.CYN):
    w = BOX_W
    sys.stdout.write(
        f"  {color}┌─ {C.B}{title}{C.R}{color} {'─' * max(2, w - 4 - _vis_len(title))}┐{C.R}\n"
    )
    for col, txt in inner:
        # Разбиваем длинный текст на строки
        clean = re.sub(r"\033\[[0-9;]*m", "", txt)
        if len(clean) > w - 6:
            # Обрезаем и ставим ...
            txt = _trunc(txt, w - 9) + C.D + "..." + C.R
            clean = re.sub(r"\033\[[0-9;]*m", "", txt)
        pad = max(0, w - 4 - _vis_len(txt))
        sys.stdout.write(
            f"  {color}│ {col}{txt}{' ' * pad}{color} │{C.R}\n"
        )
    sys.stdout.write(f"  {color}└{'─' * (w - 2)}┘{C.R}\n")
    sys.stdout.flush()


def _prog(pct, detail=""):
    w = BOX_W - 4
    fill = max(0, min(w, int(w * pct / 100)))
    bar = f"{C.GRN}{'█' * fill}{C.D}{'░' * (w - fill)}{C.R}"
    det = _trunc(detail, 20) if detail else ""
    sys.stdout.write(f"\r{bar} {pct:3d}%  {det}")
    sys.stdout.flush()


# ─── Safe I/O helpers ──────────────────────────────────────
def _safe_rmtree(path):
    """shutil.rmtree that doesn't crash on locked files."""
    try:
        if isinstance(path, Path):
            path = str(path)
        shutil.rmtree(path, ignore_errors=True)
    except:
        pass


def _safe_unlink(path):
    """Delete a single file, ignore errors."""
    try:
        if isinstance(path, Path):
            path = str(path)
        os.remove(path)
    except:
        pass


def _run(cmd, timeout=120, capture=True):
    """subprocess.run with safety."""
    try:
        if capture:
            return subprocess.run(
                cmd, shell=True, timeout=timeout, capture_output=True, text=True
            )
        return subprocess.run(cmd, shell=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None


# ─── Ghost folder fix ──────────────────────────────────────
def _fix_ghosts():
    """Find and remove ~ prefix folders in site-packages that block pip."""
    candidates = []
    # Scan common site-packages locations
    for base in [Path(sys.prefix) / "Lib" / "site-packages"]:
        if base.exists():
            for p in base.iterdir():
                if p.name.startswith("~"):
                    candidates.append(p)
    for p in candidates:
        _safe_rmtree(p)
    return len(candidates)


# ─── Step implementations ──────────────────────────────────
STEPS = []


def _step(n):
    def deco(fn):
        STEPS.append((n, fn.__name__, fn))
        return fn

    return deco


@_step(0)
def step_zed(lines, lang):
    zcd = get_zed_config_dir()
    zcd.mkdir(parents=True, exist_ok=True)
    lines.append((C.GRN, f"✓ {zcd}"))


@_step(1)
def step_lm(lines, lang):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)
    ok = sock.connect_ex((LM_HOST, LM_PORT)) == 0
    sock.close()
    if ok:
        lines.append((C.GRN, f"✓ LM Studio at {LM_HOST}:{LM_PORT}"))
    else:
        lines.append((C.YEL, f"⚠ {_tr('lm_off', lang)}"))


@_step(2)
def step_proc(lines, lang):
    """Убивает старые MCP процессы, чтобы новый код загрузился без кэша."""
    import subprocess
    killed = 0
    if sys.platform == "win32":
        # Ищем и убиваем python.exe с src.main (MCP сервер)
        r = _run('wmic process where "name like \'%python%\'" get ProcessId,CommandLine /FORMAT:CSV', timeout=10)
        if r:
            for line in r.stdout.split("\n"):
                if "src.main" in line and "python" in line.lower():
                    try:
                        parts = line.split(",")
                        pid = parts[1].strip() if len(parts) > 1 else parts[0].strip()
                        if pid.isdigit():
                            os.kill(int(pid), 15)
                            killed += 1
                    except:
                        pass
        
        # Также ищем llama-server
        r2 = _run('wmic process where "name like \'%llama-server%\'" get ProcessId /FORMAT:CSV', timeout=5)
        if r2:
            for line in r2.stdout.split("\n"):
                parts = line.split(",")
                pid = parts[-1].strip() if parts else ""
                if pid.isdigit():
                    try:
                        os.kill(int(pid), 15)
                        killed += 1
                    except:
                        pass
        
        if killed:
            time.sleep(2)
            lines.append((C.GRN, f"✓ Killed {killed} old process(es)"))
    lines.append((C.D, "· Ready"))
    ZED_EXT_DIR.mkdir(parents=True, exist_ok=True)


@_step(3)
def step_copy(lines, lang):
    skip = {
        ".git",
        "__pycache__",
        "venv",
        ".venv",
        ".codebase_indices",
        ".codebase_models",
        ".pytest_cache",
        ".ruff_cache",
        ".zed",
        ".idea",
        ".env",
        "llama_msvc",      # управляется step_llama
        "llama_vulkan",     # управляется step_llama
        "models",            # управляется step_gguf
    }
    items = [i for i in PROJECT_ROOT.iterdir() if i.name not in skip]
    copied = 0
    skipped = 0
    deleted = 0
    
    # --- Фаза 1: копируем новые/изменённые файлы ---
    for idx, item in enumerate(items):
        dst = ZED_EXT_DIR / item.name
        _prog(int((idx + 1) / len(items) * 100), item.name)
        try:
            if item.is_dir():
                _sync_dir(item, dst)
                copied += 1
            else:
                if _is_up_to_date(item, dst):
                    skipped += 1
                else:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(item), str(dst))
                    copied += 1
        except:
            pass
    sys.stdout.write("\n")
    
    # --- Фаза 2: удаляем из ZED_EXT_DIR то, чего нет в PROJECT_ROOT ---
    dst_names = {i.name for i in ZED_EXT_DIR.iterdir() if i.name not in skip}
    src_names = {i.name for i in items}
    orphaned = dst_names - src_names
    for name in orphaned:
        p = ZED_EXT_DIR / name
        try:
            if p.is_dir():
                _safe_rmtree(p)
            else:
                _safe_unlink(p)
            deleted += 1
        except:
            pass
    
    lines.append((C.GRN, f"✓ {copied} copied, {skipped} up-to-date" + (f", {deleted} removed" if deleted else "")))
    
    # Чистим __pycache__ в extension, чтобы старый байткод не мешал
    import pathlib
    pycache_dirs = list(pathlib.Path(ZED_EXT_DIR).rglob("__pycache__"))
    for d in pycache_dirs:
        _safe_rmtree(d)
    pyc_files = list(pathlib.Path(ZED_EXT_DIR).rglob("*.pyc"))
    for f in pyc_files:
        try:
            f.unlink()
        except:
            pass
    if pycache_dirs:
        lines.append((C.D, f"  ✓ cleaned {len(pycache_dirs)} __pycache__ dirs"))


def _is_up_to_date(src: Path, dst: Path) -> bool:
    """Проверяет, синхронизирован ли файл (по mtime и размеру)."""
    if not dst.exists():
        return False
    try:
        s_st = src.stat()
        d_st = dst.stat()
        return s_st.st_mtime <= d_st.st_mtime and s_st.st_size == d_st.st_size
    except:
        return False


def _sync_dir(src: Path, dst: Path):
    """Инкрементальная синхронизация директории: копирует новые/изменённые файлы,
    удаляет из dst файлы, которых нет в src."""
    if not dst.exists():
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copytree(str(src), str(dst), dirs_exist_ok=True)
        return
    
    src_files = {}
    for child in src.rglob("*"):
        if child.is_file():
            rel = child.relative_to(src)
            src_files[rel] = child
    
    dst_files = {}
    for child in dst.rglob("*"):
        if child.is_file():
            rel = child.relative_to(dst)
            dst_files[rel] = child
    
    # Копируем новые/изменённые
    for rel, src_path in src_files.items():
        dst_path = dst / rel
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        if not _is_up_to_date(src_path, dst_path):
            shutil.copy2(str(src_path), str(dst_path))
    
    # Удаляем orphaned
    for rel, dst_path in dst_files.items():
        if rel not in src_files:
            try:
                dst_path.unlink()
            except:
                pass


@_step(4)
def step_venv(lines, lang):
    if VENV_DIR.exists():
        lines.append((C.GRN, f"✓ {VENV_DIR}"))
        return
    r = _run(f'"{sys.executable}" -m venv "{VENV_DIR}"', timeout=60)
    if r and r.returncode == 0:
        lines.append((C.GRN, f"✓ {VENV_DIR}"))
    else:
        raise RuntimeError("venv creation failed")


@_step(5)
def step_pip(lines, lang):
    req = ZED_EXT_DIR / "requirements.txt"
    if not req.exists():
        raise FileNotFoundError(f"requirements.txt not found at {req}")
    n = len(req.read_text().splitlines())
    # Fix ghosts before pip
    g = _fix_ghosts()
    if g:
        lines.append((C.D, f"  {_tr('ghosts', lang)}: {g}"))
    # Upgrade pip
    _run(f'"{PYTHON_EXE}" -m pip install --upgrade pip', timeout=60)
    # Install
    proc = subprocess.Popen(
        f'"{PYTHON_EXE}" -m pip install -r "{req}"',
        shell=True,
        cwd=str(ZED_EXT_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    last = ""
    for line in proc.stdout:
        line = line.strip()
        if line:
            last = line[:40]
        _prog(50, last)
    proc.wait()
    if proc.returncode == 0:
        sys.stdout.write("\n")
        lines.append((C.GRN, f"✓ {n} packages"))
    else:
        raise RuntimeError(f"pip failed (exit {proc.returncode})")


@_step(6)
def step_llama(lines, lang):
    """Скачивает llama-server.exe с GitHub и синхронизирует в ZED_EXT_DIR."""
    from src.core.llama_runner import (
        is_installed, download_llama_binary, LLAMA_VERSION,
        _get_llama_dir, _IS_INSIDER,
    )

    zed_llama_dir = ZED_EXT_DIR / "llama_msvc"
    zed_bin = zed_llama_dir / "llama-server.exe"

    if zed_bin.exists():
        lines.append((C.GRN, f"✓ llama.cpp в расширении: {LLAMA_VERSION}"))
        return

    # Проверяем в проекте (куда download_llama_binary скачает)
    if is_installed():
        lines.append((C.D, f"  📋 Копирую llama.cpp в расширение..."))
        try:
            src_dir = _get_llama_dir()
            if zed_llama_dir.exists():
                _safe_rmtree(zed_llama_dir)
            shutil.copytree(str(src_dir), str(zed_llama_dir))
            lines.append((C.GRN, f"✓ llama.cpp скопирован в расширение"))
            return
        except Exception as e:
            lines.append((C.YEL, f"⚠ Ошибка копирования: {e}"))

    # Нет нигде — скачиваем
    arch_label = "MSVC"
    lines.append((C.D, f"  ⬇ Скачиваю llama-server.exe ({arch_label})..."))
    if _IS_INSIDER:
        lines.append((C.D, "  🔧 Insider: будет пропатчен CRT API Set → ucrtbase.dll"))

    def _prog_llama(pct, msg):
        _prog(pct, msg)

    if download_llama_binary(progress_cb=_prog_llama):
        sys.stdout.write("\n")
        lines.append((C.GRN, f"✓ llama.cpp {LLAMA_VERSION}"))
        # Копируем в расширение
        try:
            src_dir = _get_llama_dir()
            if zed_llama_dir.exists():
                _safe_rmtree(zed_llama_dir)
            shutil.copytree(str(src_dir), str(zed_llama_dir))
            lines.append((C.GRN, f"✓ llama.cpp скопирован в расширение"))
        except Exception as e:
            lines.append((C.YEL, f"⚠ Не удалось скопировать в расширение: {e}"))
    else:
        lines.append((C.YEL, f"⚠ Не удалось скачать llama.cpp (будет ONNX)"))


@_step(7)
def step_gguf(lines, lang):
    """Скачивает GGUF модель реранкера (bge-reranker-v2-m3) и синхронизирует в ZED_EXT_DIR."""
    from src.core.llama_runner import is_model_downloaded, download_gguf_model, GGUF_MODELS, _get_models_dir

    all_ok = True
    zed_models_dir = ZED_EXT_DIR / "models"

    for key in ["bge-reranker-v2-m3"]:
        # Проверяем в ZED_EXT_DIR (где MCP реально работает)
        zed_gguf = zed_models_dir / GGUF_MODELS[key]["file"]
        if zed_gguf.exists():
            lines.append((C.GRN, f"  ✓ {GGUF_MODELS[key]['file']} (расширение)"))
            continue

        # Проверяем в проекте
        if is_model_downloaded(key):
            # Копируем в расширение
            lines.append((C.D, f"  📋 Копирую {GGUF_MODELS[key]['file']} в расширение..."))
            try:
                zed_models_dir.mkdir(parents=True, exist_ok=True)
                src_gguf = _get_models_dir() / GGUF_MODELS[key]["file"]
                if src_gguf.exists():
                    shutil.copy2(str(src_gguf), str(zed_gguf))
                    lines.append((C.GRN, f"  ✓ {GGUF_MODELS[key]['file']} (скопирован)"))
                    continue
            except Exception as e:
                lines.append((C.YEL, f"  ⚠ Не удалось скопировать {key}: {e}"))

        # Скачиваем
        lines.append((C.D, f"  ⬇ {GGUF_MODELS[key]['file']} (~{GGUF_MODELS[key]['size_mb']} MB)..."))

        if download_gguf_model(key, progress_cb=lambda p, m: _prog(p, m)):
            sys.stdout.write("\n")
            lines.append((C.GRN, f"  ✓ {GGUF_MODELS[key]['file']}"))
            # Копируем в расширение
            try:
                zed_models_dir.mkdir(parents=True, exist_ok=True)
                src_gguf = _get_models_dir() / GGUF_MODELS[key]["file"]
                if src_gguf.exists():
                    shutil.copy2(str(src_gguf), str(zed_gguf))
            except Exception:
                pass
        else:
            sys.stdout.write("\n")
            lines.append((C.YEL, f"  ⚠ {GGUF_MODELS[key]['file']} не скачан (будет ONNX)"))
            all_ok = False

    if all_ok:
        lines.append((C.GRN, f"✅ GGUF модель реранкера готова — llama.cpp работает"))


@_step(8)
def step_models(lines, lang):
    """Download ONNX models: e5-base-v2 (embedder) + bge-reranker-v2-m3 (reranker).

    Checks:
      1. ZED_EXT_DIR  (where MCP server runs)
      2. PROJECT_ROOT (local dev)
      3. Shared: ~/.cache/mscodebase/models/
    If found at (2) or (3) → copy to (1).
    If not found anywhere → download fresh.
    """
    SHARED_DIR = Path.home() / ".cache" / "mscodebase" / "models"

    models = {
        "e5-base-v2": ("intfloat/multilingual-e5-base", "embedding", 265),
        "reranker-bge-reranker-v2-m3": ("BAAI/bge-reranker-v2-m3", "reranker", 544),
    }

    def _find_model(slug: str) -> Path | None:
        """Check all locations, return first source dir."""
        for base in [ZED_EXT_DIR, SHARED_DIR, PROJECT_ROOT]:
            p = base / ".codebase_models" / "onnx" / slug / "model.onnx"
            if p.exists():
                return base / ".codebase_models" / "onnx" / slug
        return None

    need_download: list[tuple[str, str, str, int]] = []  # (name, type, slug, size_mb)
    need_copy: list[tuple[str, str, str, Path]] = []  # (name, type, slug, src_dir)

    for slug, (name, mtype, size_mb) in models.items():
        dst_dir = ZED_EXT_DIR / ".codebase_models" / "onnx" / slug
        dst_m = dst_dir / "model.onnx"

        if dst_m.exists():
            sz = dst_m.stat().st_size / 1024 / 1024
            lines.append((C.GRN, f"  ✓ {slug}: {sz:.0f} MB (ZED_EXT_DIR)"))
            continue

        src = _find_model(slug)
        if src and src != dst_dir:
            need_copy.append((name, mtype, slug, src))
        else:
            need_download.append((name, mtype, slug, size_mb))

    # ─── Phase 1: Copy existing models ─────────────────────
    for name, mtype, slug, src in need_copy:
        dst = ZED_EXT_DIR / ".codebase_models" / "onnx" / slug
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            _safe_rmtree(dst)
        shutil.copytree(str(src), str(dst))
        sz = (dst / "model.onnx").stat().st_size / 1024 / 1024
        lines.append((C.GRN, f"  ✓ {slug}: {sz:.0f} MB (synced)"))
        # Seed shared cache
        shared = SHARED_DIR / ".codebase_models" / "onnx" / slug
        if not (shared / "model.onnx").exists():
            shared.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(str(src), str(shared))

    if not need_download:
        lines.append((C.GRN, f"  {_tr('models_ok', lang)}"))
        return

    # ─── Phase 2: Offer download ───────────────────────────
    total_mb = sum(sz for _, _, _, sz in need_download)
    lines.append(
        (
            C.YEL,
            f"? Download {len(need_download)} models ({total_mb} MB total)? (Y/n)",
        )
    )
    ch = input(f"  {C.B}> {C.R}").strip().lower()
    if ch not in ("", "y", "yes"):
        lines.append((C.D, "  Skipped — will use LM Studio as fallback"))
        return

    _run(f'"{sys.executable}" -m pip install huggingface-hub -q', timeout=60)

    for name, mtype, slug, _ in need_download:
        label = _tr("dl_1" if mtype == "embedding" else "dl_2", lang)
        lines.append((C.D, f"  {label}..."))

        # Download to PROJECT_ROOT first
        proc = _run(
            f'"{sys.executable}" "{PROJECT_ROOT / "scripts" / "download_model.py"}" '
            f'--model "{name}" --type "{mtype}" --auto-clean',
            timeout=600,
        )
        src = PROJECT_ROOT / ".codebase_models" / "onnx" / slug
        if proc and proc.returncode == 0 and (src / "model.onnx").exists():
            # Copy to ZED_EXT_DIR
            dst = ZED_EXT_DIR / ".codebase_models" / "onnx" / slug
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                _safe_rmtree(dst)
            shutil.copytree(str(src), str(dst))
            sz = (dst / "model.onnx").stat().st_size / 1024 / 1024
            lines.append((C.GRN, f"  ✓ {slug}: {sz:.0f} MB"))

            # Also seed shared cache
            shared = SHARED_DIR / ".codebase_models" / "onnx" / slug
            if not (shared / "model.onnx").exists():
                shared.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(str(src), str(shared))
        else:
            lines.append((C.YEL, f"  ⚠ {slug} failed — will use LM Studio as fallback"))


@_step(9)
def step_db(lines, lang):
    db_path = PROJECT_ROOT / ".codebase_indices" / "lancedb_v2"
    if not db_path.exists():
        lines.append((C.D, "· Not found — will create on first run"))
        return
    try:
        import lancedb

        db = lancedb.connect(str(db_path))
        tables = db.list_tables()
        if tables:
            t = db.open_table(tables[0])
            fields = [f.name for f in t.schema]
            lines.append((C.GRN, f"✓ {len(tables)} table(s), {len(fields)} fields"))
        else:
            lines.append((C.D, "· Empty"))
    except Exception as e:
        lines.append((C.YEL, f"⚠ {e}"))


@_step(10)
def step_zedcfg(lines, lang):
    cmd = f"{PYTHON_EXE} -u -m src.main"
    if patch_zed_settings(
        cmd,
        mode="global",
        lsp_config=None,
        languages_config=None,
        install_path=str(ZED_EXT_DIR),
    ):
        lines.append((C.GRN, f"✓ MCP configured"))
    else:
        raise RuntimeError("Failed to configure Zed")


@_step(11)
def step_uninst(lines, lang):
    content = _build_uninstall_bat()
    try:
        UNINSTALLER.write_text(content, encoding="utf-8")
        lines.append((C.GRN, f"✓ {UNINSTALLER.name}"))
    except Exception as e:
        lines.append((C.YEL, f"⚠ {e}"))


# ─── Uninstaller ───────────────────────────────────────────
def _build_uninstall_bat():
    py, ext = str(PYTHON_EXE), str(ZED_EXT_DIR)
    return (
        "@echo off\r\nchcp 65001 >nul\r\necho Uninstalling...\r\n"
        f'taskkill /f /im python.exe /fi "WINDOWTITLE eq mscodebase*" >nul 2>&1\r\n'
        f'taskkill /f /im python.exe /fi "WINDOWTITLE eq main*" >nul 2>&1\r\n'
        f'taskkill /f /im llama-server.exe >nul 2>&1\r\n'
        f'taskkill /f /im onnx_server.exe >nul 2>&1\r\n'
        f"timeout /t 2 /nobreak >nul\r\n"
        f'for /l %i in (1,1,3) do (rd /s /q "{ext}" 2>nul & if not exist "{ext}" goto DEL)\r\n'
        f"echo Failed. Restart PC and run again.\r\ngoto END\r\n:DEL\r\necho Removed.\r\n:END\r\npause >nul\r\n"
    )


# ─── Main ──────────────────────────────────────────────────
def main():
    _ea()
    lang = _detect_lang()
    # Enable UTF-8 mode for Russian on Windows
    if sys.platform == "win32":
        import io

        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    # Sort steps by index
    STEPS.sort(key=lambda x: x[0])

    # Welcome
    _box(
        "",
        [
            (C.CYN, f"{C.B}{_tr('title', lang)}{C.R}"),
            (C.D, f"  {PROJECT_ROOT.name}  |  Python {sys.version[:5]}"),
        ],
        C.CYN,
    )

    ok_count = 0
    skip_count = 0
    fail_count = 0
    t0 = time.time()

    for n, name, fn in STEPS:
        title = _tr(name.replace("step_", "chk_"), lang)
        label = f"{_tr('step', lang)} {n + 1}/{TOTAL_STEPS}: {title}"
        lines = []
        max_retries = 2
        step_status = "ok"

        for attempt in range(max_retries + 1):
            try:
                fn(lines, lang)
                _box(label, lines, C.GRN)
                ok_count += 1
                break
            except Exception as e:
                err_msg = str(e).split("\n")[0][:60]
                if attempt < max_retries:
                    lines.append((C.YEL, f"⚠ {err_msg}"))
                    _box(label, lines, C.YEL)
                    ch = (
                        input(f"  {C.B}[r]etry / [s]kip / [c]ancel{C.R}: ")
                        .strip()
                        .lower()
                    )
                    if ch == "s":
                        lines.append((C.YEL, f"  {_tr('skip', lang)}"))
                        step_status = "skip"
                        break
                    elif ch == "c":
                        print(f"\n  {C.RED}Aborted.{C.R}")
                        return
                    # else: retry
                else:
                    lines.append((C.RED, f"✘ {err_msg}"))
                    _box(label, lines, C.RED)
                    ch = input(f"  {C.B}[s]kip / [c]ancel{C.R}: ").strip().lower()
                    if ch == "s":
                        lines.append((C.YEL, f"  {_tr('skip', lang)}"))
                        step_status = "skip"
                        break
                    else:
                        print(f"\n  {C.RED}Aborted.{C.R}")
                        return
        else:
            step_status = "fail"  # inner for completed without break

        if step_status == "skip":
            skip_count += 1
        elif step_status == "fail":
            fail_count += 1

    # Summary
    elapsed = time.time() - t0
    has_err = fail_count > 0
    has_warn = skip_count > 0

    status_line = (
        f"{C.B}✓ {_tr('done_all', lang)}  ({elapsed:.0f}s){C.R}"
        if not has_err
        else f"{C.B}⚠ {_tr('done_all', lang)}  ({elapsed:.0f}s){C.R}"
    )
    detail_line = f"{ok_count} ok, {skip_count} skipped, {fail_count} failed"

    summary = [
        (C.GRN if not has_err else C.RED if has_err else C.YEL, status_line),
        (C.D if not has_err else C.YEL, detail_line),
        (C.D, f"  {_tr('next', lang)}:"),
        (C.D, f"  1. {_tr('restart', lang)}"),
        (C.D, f"  2. {_tr('wait_idx', lang)}"),
        (C.D, f"  3. {_tr('start_code', lang)}"),
    ]
    _box(
        _tr("done_all", lang),
        summary,
        C.GRN if not has_err else C.RED if fail_count > 0 else C.YEL,
    )
    print(f"\n  {C.D}Extension: {ZED_EXT_DIR}{C.R}")
    print(f"  {C.D}Python:    {PYTHON_EXE}{C.R}")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n  {C.RED}Aborted by user.{C.R}")
        sys.exit(1)
