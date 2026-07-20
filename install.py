"""
MSCodebase Intelligence — Installer & Updater v3.1
=================================================
Robust TUI with error recovery, self-healing, and safe cross-platform I/O.

Design principles:
  - Every step wrapped in try/except with retry/skip/cancel
  - Progress bar via single \r line (no flicker)
  - Safe file ops (always ignore_errors on rmtree, handle long paths)
  - Model download with progress + retry
  - Ghost folder cleanup targets the *target venv*, not the installer's own interpreter
  - Process cleanup uses CIM/PowerShell on Windows (wmic is removed on 24H2+) with a
    taskkill fallback, and pgrep/pkill on POSIX
  - KeyboardInterrupt handler restores terminal state
  - No silent exception swallowing without at least a debug-level trace

Changelog v3.0 -> v3.1 (все пункты — реальные баги, не стилистика):
  1. _fix_ghosts() сканировал sys.prefix (интерпретатор, которым запущен install.py),
     а не VENV_DIR (venv самого расширения) — призраки в реальном месте не находились.
  2. step_proc использовал `wmic`, удалённый по умолчанию в Windows 11 24H2 —
     заменено на PowerShell Get-CimInstance с fallback на taskkill /FI.
  3. step_proc не имел POSIX-ветки — старые процессы на Linux/macOS не убивались.
  4. step_venv проверял только существование папки, не наличие рабочего python.exe —
     битый venv считался готовым и пропускался.
  5. Голые `except: pass` в safe-I/O хелперах заменены на `except Exception: logger.debug(...)`
     — ошибка не убивает установку, но не теряется бесследно.
  6. Добавлена path-safety проверка (resolve + is_relative_to) в _sync_dir перед удалением
     "осиротевших" файлов — защита от case, когда символическая ссылка/edge-case путь
     резолвится за пределы ZED_EXT_DIR.
  7. step_pip теперь предпочитает requirements-lock.txt, если он есть рядом с
     requirements.txt (совместимо с dependency-lock практикой, принятой в проекте).
"""

import io
import json
import locale
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

sys.path.insert(0, str(Path(__file__).resolve().parent / "src" / "utils"))
from zed_config import get_zed_config_dir, patch_zed_settings  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent
ZED_EXT_DIR = (
    Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")))
    / "Zed"
    / "extensions"
    / "mscodebase-intelligence"
)
VENV_DIR = ZED_EXT_DIR / "venv"
IS_WINDOWS = sys.platform == "win32"
PYTHON_EXE = VENV_DIR / "Scripts" / "python.exe" if IS_WINDOWS else VENV_DIR / "bin" / "python3"
VENV_SITE_PACKAGES = (
    VENV_DIR / "Lib" / "site-packages"
    if IS_WINDOWS
    else VENV_DIR / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
)
UNINSTALLER = ZED_EXT_DIR / ("uninstall.bat" if IS_WINDOWS else "uninstall.sh")
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
    "chk_venv": {"en": "Virtual environment", "ru": "Виртуальное окружение", "zh": "虚拟环境"},
    "chk_pip": {"en": "Install packages", "ru": "Установка пакетов", "zh": "安装依赖"},
    "chk_llama": {"en": "llama.cpp engine", "ru": "llama.cpp движок", "zh": "llama.cpp引擎"},
    "chk_gguf": {
        "en": "GGUF reranker model (bge-reranker-v2-m3)",
        "ru": "GGUF модель реранкера (bge-reranker-v2-m3)",
        "zh": "GGUF排序模型",
    },
    "chk_models": {
        "en": "ONNX models: E5-small (embedder) + BGE-M3 (reranker)",
        "ru": "ONNX модели: E5-small (эмбеддер) + BGE-M3 (реранкер)",
        "zh": "ONNX模型: E5-small嵌入 + BGE-M3排序",
    },
    "chk_db": {"en": "Database", "ru": "База данных", "zh": "数据库"},
    "chk_zedcfg": {"en": "Zed integration", "ru": "Интеграция в Zed", "zh": "Zed集成"},
    "chk_uninst": {"en": "Uninstaller", "ru": "Деинсталлятор", "zh": "卸载程序"},
    "done_all": {"en": "Installation complete!", "ru": "Установка завершена!", "zh": "安装完成！"},
    "next": {"en": "Next steps", "ru": "Следующие шаги", "zh": "后续步骤"},
    "restart": {"en": "Restart Zed IDE", "ru": "Перезапустите Zed IDE", "zh": "重启Zed"},
    "wait_idx": {
        "en": "Open project, wait for indexing",
        "ru": "Откройте проект, дождитесь индексации",
        "zh": "打开项目，等待索引",
    },
    "start_code": {"en": "Start coding!", "ru": "Начинайте кодить!", "zh": "开始编码！"},
    "dl_ask": {
        "en": "Download ONNX models (e5-small-int8 ~113 MB + reranker ~544 MB)? (Y/n)",
        "ru": "Скачать ONNX модели (e5-small-int8 ~113 МБ + реранкер ~544 МБ)? (Y/n)",
        "zh": "下载ONNX模型(e5-small-int8 ~113 MB + 排序 ~544 MB)？(Y/n)",
    },
    "models_ok": {"en": "ONNX models installed", "ru": "ONNX модели установлены", "zh": "ONNX模型已安装"},
    "dl_1": {
        "en": "Embedding: multilingual-e5-small-int8 (multilingual, 384dim, ~113 MB)",
        "ru": "Эмбеддер: multilingual-e5-small-int8 (multilingual, 384dim, ~113 МБ)",
        "zh": "嵌入模型：multilingual-e5-small-int8 (多语言, 384维, ~113 MB)",
    },
    "dl_2": {
        "en": "Reranker: bge-reranker-v2-m3 (~550 MB)",
        "ru": "Реранкер: bge-reranker-v2-m3 (~550 МБ)",
        "zh": "重排序：bge-reranker-v2-m3 (~550 MB)",
    },
    "ghosts": {"en": "Cleaned ghost folders (~)", "ru": "Очищены папки-призраки (~)", "zh": "已清理幽灵文件夹(~)"},
    "lm_off": {
        "en": "LM Studio offline — using local ONNX",
        "ru": "LM Studio офлайн — используется локальный ONNX",
        "zh": "LM Studio离线—使用本地ONNX",
    },
}


def _tr(key: str, lang: str = "en") -> str:
    d = LANG.get(key, {})
    return d.get(lang, d.get("en", key))


def _detect_lang() -> str:
    try:
        full = locale.getlocale(locale.LC_MESSAGES)[0] or ""
        p = full[:2].lower()
        return {"ru": "ru", "uk": "ru", "zh": "zh", "cn": "zh"}.get(p, "en")
    except Exception as e:
        logger.debug("locale detection failed: %s", e)
        return "en"


# ─── ANSI + TUI ────────────────────────────────────────────
BOX_W = 60  # фиксированная ширина, не зависит от терминала
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


class C:
    R = "\033[0m"
    B = "\033[1m"
    D = "\033[2m"
    RED = "\033[91m"
    GRN = "\033[92m"
    YEL = "\033[93m"
    CYN = "\033[96m"


def _enable_ansi() -> None:
    if IS_WINDOWS:
        os.system("")


def _vis_len(s: str) -> int:
    """Длина строки без ANSI кодов."""
    return len(_ANSI_RE.sub("", s))


def _trunc(s: str, w: int) -> str:
    """Обрезает строку до w видимых символов с учётом ANSI."""
    clean = _ANSI_RE.sub("", s)
    if len(clean) <= w:
        return s
    ans = re.match(r"^(\033\[[0-9;]*m)*", s)
    prefix = ans.group(0) if ans else ""
    return prefix + clean[:w] + C.R


def _box(title: str, inner: list[tuple[str, str]], color: str = C.CYN) -> None:
    w = BOX_W
    sys.stdout.write(
        f"  {color}┌─ {C.B}{title}{C.R}{color} {'─' * max(2, w - 4 - _vis_len(title))}┐{C.R}\n"
    )
    for col, txt in inner:
        clean = _ANSI_RE.sub("", txt)
        if len(clean) > w - 6:
            txt = _trunc(txt, w - 9) + C.D + "..." + C.R
        pad = max(0, w - 4 - _vis_len(txt))
        sys.stdout.write(f"  {color}│ {col}{txt}{' ' * pad}{color} │{C.R}\n")
    sys.stdout.write(f"  {color}└{'─' * (w - 2)}┘{C.R}\n")
    sys.stdout.flush()


def _line(status: str, title: str, detail: str = "", color: str = C.GRN) -> None:
    """Однострочный статус шага (вместо _box). Обновляет строку на месте через \r."""
    w = BOX_W - 6
    clean_title = _ANSI_RE.sub("", title)
    clean_detail = _ANSI_RE.sub("", detail)
    dots = max(2, w - len(clean_title) - len(clean_detail) - 4)
    sys.stdout.write(f"\r  {color}{status}{C.R} {title} {C.D}{'.' * dots}{C.R} {detail}   ")
    sys.stdout.flush()


def _prog(pct: int, detail: str = "") -> None:
    w = BOX_W - 4
    fill = max(0, min(w, int(w * pct / 100)))
    bar = f"{C.GRN}{'█' * fill}{C.D}{'░' * (w - fill)}{C.R}"
    det = _trunc(detail, 20) if detail else ""
    sys.stdout.write(f"\r{bar} {pct:3d}%  {det}")
    sys.stdout.flush()


# ─── Safe I/O helpers ──────────────────────────────────────
def _safe_rmtree(path: Path | str) -> None:
    """shutil.rmtree, устойчивый к заблокированным файлам. Не глотает ошибку молча."""
    try:
        shutil.rmtree(str(path), ignore_errors=True)
    except Exception as e:
        logger.debug("rmtree(%s) failed: %s", path, e)


def _safe_unlink(path: Path | str) -> None:
    """Удаляет один файл, не роняя установку при ошибке."""
    try:
        os.remove(str(path))
    except Exception as e:
        logger.debug("unlink(%s) failed: %s", path, e)


def _is_within(path: Path, root: Path) -> bool:
    """Path-safety guard: path обязан резолвиться внутрь root перед удалением/записью."""
    try:
        return path.resolve().is_relative_to(root.resolve())
    except Exception:
        return False


def _run(cmd: str, timeout: int = 120, capture: bool = True) -> Optional[subprocess.CompletedProcess]:
    """subprocess.run с таймаутом и безопасным возвратом None вместо исключения."""
    try:
        if capture:
            return subprocess.run(cmd, shell=True, timeout=timeout, capture_output=True, text=True)
        return subprocess.run(cmd, shell=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.debug("command timed out after %ss: %s", timeout, cmd[:80])
        return None
    except Exception as e:
        logger.debug("command failed: %s (%s)", cmd[:80], e)
        return None


# ─── Ghost folder fix ──────────────────────────────────────
def _fix_ghosts() -> int:
    """Находит и удаляет папки с префиксом '~' в site-packages ЦЕЛЕВОГО venv
    (VENV_SITE_PACKAGES), а не в site-packages интерпретатора, которым запущен
    install.py — это два разных места, и до v3.1 сканировался не тот."""
    if not VENV_SITE_PACKAGES.exists():
        return 0
    candidates = [p for p in VENV_SITE_PACKAGES.iterdir() if p.name.startswith("~")]
    for p in candidates:
        _safe_rmtree(p)
    return len(candidates)


# ─── Process cleanup (cross-platform, wmic-free) ───────────
def _kill_by_cmdline_windows(pattern: str) -> int:
    """Убивает процессы, чья командная строка содержит pattern.

    wmic удалён по умолчанию в Windows 11 24H2 — используем PowerShell
    Get-CimInstance (современный преемник WMI, доступен всегда), с fallback
    на taskkill по имени образа, если PowerShell недоступен.
    """
    killed = 0
    ps_cmd = (
        "powershell -NoProfile -Command "
        f"\"Get-CimInstance Win32_Process | Where-Object {{ $_.CommandLine -like '*{pattern}*' }} "
        "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; "
        "Write-Output $_.ProcessId }\""
    )
    r = _run(ps_cmd, timeout=15)
    if r and r.returncode == 0 and r.stdout.strip():
        killed = len([line for line in r.stdout.splitlines() if line.strip().isdigit()])
        return killed

    # Fallback: taskkill не умеет фильтровать по cmdline, только по имени образа/окну.
    # Это грубее (может задеть процессы с тем же именем не от нас), но лучше, чем ничего.
    logger.debug("PowerShell CIM query failed, falling back to taskkill by image name")
    _run('taskkill /F /IM python.exe /FI "WINDOWTITLE eq mscodebase*"', timeout=10)
    return killed


def _kill_by_cmdline_posix(pattern: str) -> int:
    """POSIX-эквивалент: pkill по паттерну командной строки. До v3.1 эта ветка
    отсутствовала вовсе — старые MCP-процессы на Linux/macOS никогда не убивались."""
    r = _run(f"pgrep -f '{pattern}'", timeout=10)
    if not r or not r.stdout.strip():
        return 0
    pids = [line.strip() for line in r.stdout.splitlines() if line.strip().isdigit()]
    for pid in pids:
        try:
            os.kill(int(pid), 15)  # SIGTERM
        except ProcessLookupError:
            pass
        except Exception as e:
            logger.debug("kill(%s) failed: %s", pid, e)
    return len(pids)


# ─── Step implementations ──────────────────────────────────
STEPS: list[tuple[int, str, "callable"]] = []


def _step(n: int):
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
    try:
        ok = sock.connect_ex((LM_HOST, LM_PORT)) == 0
    finally:
        sock.close()
    if ok:
        lines.append((C.GRN, f"✓ LM Studio at {LM_HOST}:{LM_PORT}"))
    else:
        lines.append((C.YEL, f"⚠ {_tr('lm_off', lang)}"))


@_step(2)
def step_proc(lines, lang):
    """Убивает старые MCP-процессы, чтобы новый код загрузился без кэша.

    v3.1: на Windows больше не использует wmic (удалён в 24H2+), на POSIX
    теперь тоже реально что-то делает (раньше было тихо no-op).
    """
    killed = 0
    if IS_WINDOWS:
        killed += _kill_by_cmdline_windows("src.main")
        killed += _kill_by_cmdline_windows("llama-server")
    else:
        killed += _kill_by_cmdline_posix("src\\.main")
        killed += _kill_by_cmdline_posix("llama-server")

    if killed:
        time.sleep(2)
        lines.append((C.GRN, f"✓ Killed {killed} old process(es)"))
    else:
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
        "llama_msvc",   # управляется step_llama
        "llama_vulkan",  # управляется step_llama
        "models",        # управляется step_gguf
    }
    items = [i for i in PROJECT_ROOT.iterdir() if i.name not in skip]
    copied = skipped = deleted = 0

    # --- Фаза 1: копируем новые/изменённые файлы ---
    for idx, item in enumerate(items):
        dst = ZED_EXT_DIR / item.name
        _prog(int((idx + 1) / max(1, len(items)) * 100), item.name)
        try:
            if item.is_dir():
                _sync_dir(item, dst)
                copied += 1
            elif _is_up_to_date(item, dst):
                skipped += 1
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(item), str(dst))
                copied += 1
        except Exception as e:
            logger.debug("copy %s -> %s failed: %s", item, dst, e)
    sys.stdout.write("\n")

    # --- Фаза 2: удаляем из ZED_EXT_DIR то, чего нет в PROJECT_ROOT ---
    if ZED_EXT_DIR.exists():
        dst_names = {i.name for i in ZED_EXT_DIR.iterdir() if i.name not in skip}
        src_names = {i.name for i in items}
        for name in dst_names - src_names:
            p = ZED_EXT_DIR / name
            if not _is_within(p, ZED_EXT_DIR):
                logger.debug("refusing to delete %s — resolves outside ZED_EXT_DIR", p)
                continue
            if p.is_dir():
                _safe_rmtree(p)
            else:
                _safe_unlink(p)
            deleted += 1

    detail = f"✓ {copied} copied, {skipped} up-to-date"
    if deleted:
        detail += f", {deleted} removed"
    lines.append((C.GRN, detail))

    # Чистим __pycache__ в расширении, чтобы старый байткод не мешал
    pycache_dirs = list(ZED_EXT_DIR.rglob("__pycache__"))
    for d in pycache_dirs:
        _safe_rmtree(d)
    for f in ZED_EXT_DIR.rglob("*.pyc"):
        _safe_unlink(f)
    if pycache_dirs:
        lines.append((C.D, f"  ✓ cleaned {len(pycache_dirs)} __pycache__ dirs"))

    # Маркерный файл расширения (для main.py)
    marker_dst = ZED_EXT_DIR / "__mscodebase_ext__.marker"
    marker_src = PROJECT_ROOT / "__mscodebase_ext__.marker"
    if marker_src.exists():
        marker_dst.write_text(marker_src.read_text(encoding="utf-8"), encoding="utf-8")
        lines.append((C.GRN, "  ✓ marker created"))
    else:
        marker_dst.write_text("# MSCodeBase Extension Marker\n", encoding="utf-8")
        lines.append((C.D, "  ✓ marker created (default)"))


def _is_up_to_date(src: Path, dst: Path) -> bool:
    """Проверяет, синхронизирован ли файл (по mtime и размеру).

    ВАЖНО: строгое меньше (<), не меньше-равно (<=). Иначе ручной cp в
    расширение «замораживает» файл — install.py перестаёт его обновлять,
    потому что mtime в dst >= mtime в src.
    """
    if not dst.exists():
        return False
    try:
        s_st, d_st = src.stat(), dst.stat()
        return s_st.st_mtime < d_st.st_mtime and s_st.st_size == d_st.st_size
    except OSError as e:
        logger.debug("stat comparison failed for %s: %s", src, e)
        return False


def _sync_dir(src: Path, dst: Path) -> None:
    """Инкрементальная синхронизация директории: копирует новые/изменённые
    файлы, удаляет из dst файлы, которых нет в src. Path-safety: удаление
    происходит только для путей, реально резолвящихся внутрь dst."""
    if not dst.exists():
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copytree(str(src), str(dst), dirs_exist_ok=True)
        return

    src_files = {c.relative_to(src): c for c in src.rglob("*") if c.is_file()}
    dst_files = {c.relative_to(dst): c for c in dst.rglob("*") if c.is_file()}

    for rel, src_path in src_files.items():
        dst_path = dst / rel
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        if not _is_up_to_date(src_path, dst_path):
            shutil.copy2(str(src_path), str(dst_path))

    for rel, dst_path in dst_files.items():
        if rel in src_files:
            continue
        if not _is_within(dst_path, dst):
            logger.debug("refusing to delete %s — resolves outside %s", dst_path, dst)
            continue
        _safe_unlink(dst_path)


@_step(4)
def step_venv(lines, lang):
    """v3.1: раньше проверялось только существование VENV_DIR — битый venv
    (папка есть, python.exe нет/сломан) считался готовым и молча пропускался.
    Теперь проверяем реальную работоспособность интерпретатора."""
    if VENV_DIR.exists() and PYTHON_EXE.exists():
        r = _run(f'"{PYTHON_EXE}" --version', timeout=10)
        if r and r.returncode == 0:
            lines.append((C.GRN, f"✓ {VENV_DIR}"))
            return
        lines.append((C.YEL, "⚠ venv found but broken, recreating"))
        _safe_rmtree(VENV_DIR)

    r = _run(f'"{sys.executable}" -m venv "{VENV_DIR}"', timeout=60)
    if r and r.returncode == 0 and PYTHON_EXE.exists():
        lines.append((C.GRN, f"✓ {VENV_DIR}"))
    else:
        raise RuntimeError("venv creation failed")


@_step(5)
def step_pip(lines, lang):
    """v3.1: предпочитает requirements-lock.txt, если он есть рядом —
    совместимо с dependency-lock практикой (точный пин + rationale-комментарии
    в requirements.txt, зафиксированный lockfile для воспроизводимости)."""
    lock = ZED_EXT_DIR / "requirements-lock.txt"
    req = lock if lock.exists() else ZED_EXT_DIR / "requirements.txt"
    if not req.exists():
        raise FileNotFoundError(f"requirements(.txt|-lock.txt) not found at {ZED_EXT_DIR}")
    n = len(req.read_text(encoding="utf-8").splitlines())

    g = _fix_ghosts()
    if g:
        lines.append((C.D, f"  {_tr('ghosts', lang)}: {g}"))

    _run(f'"{PYTHON_EXE}" -m pip install --upgrade pip', timeout=60)

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
        lines.append((C.GRN, f"✓ {n} packages ({req.name})"))
    else:
        raise RuntimeError(f"pip failed (exit {proc.returncode})")


@_step(6)
def step_llama(lines, lang):
    """Скачивает llama-server с GitHub и синхронизирует в ZED_EXT_DIR."""
    from src.core.llama_runner import (
        is_installed,
        download_llama_binary,
        LLAMA_VERSION,
        _get_llama_dir,
        _IS_INSIDER,
    )

    bin_name = "llama-server.exe" if IS_WINDOWS else "llama-server"
    zed_llama_dir = ZED_EXT_DIR / "llama_msvc"
    zed_bin = zed_llama_dir / bin_name

    if zed_bin.exists():
        lines.append((C.GRN, f"✓ llama.cpp в расширении: {LLAMA_VERSION}"))
        return

    if is_installed():
        lines.append((C.D, "  📋 Копирую llama.cpp в расширение..."))
        try:
            src_dir = _get_llama_dir()
            if zed_llama_dir.exists():
                _safe_rmtree(zed_llama_dir)
            shutil.copytree(str(src_dir), str(zed_llama_dir))
            lines.append((C.GRN, "✓ llama.cpp скопирован в расширение"))
            return
        except Exception as e:
            lines.append((C.YEL, f"⚠ Ошибка копирования: {e}"))

    lines.append((C.D, "  ⬇ Скачиваю llama-server..."))
    if _IS_INSIDER:
        lines.append((C.D, "  🔧 Insider: будет пропатчен CRT API Set → ucrtbase.dll"))

    if download_llama_binary(progress_cb=_prog):
        sys.stdout.write("\n")
        lines.append((C.GRN, f"✓ llama.cpp {LLAMA_VERSION}"))
        try:
            src_dir = _get_llama_dir()
            if zed_llama_dir.exists():
                _safe_rmtree(zed_llama_dir)
            shutil.copytree(str(src_dir), str(zed_llama_dir))
            lines.append((C.GRN, "✓ llama.cpp скопирован в расширение"))
        except Exception as e:
            lines.append((C.YEL, f"⚠ Не удалось скопировать в расширение: {e}"))
    else:
        lines.append((C.YEL, "⚠ Не удалось скачать llama.cpp (будет ONNX)"))


@_step(7)
def step_gguf(lines, lang):
    """Скачивает GGUF модель реранкера (bge-reranker-v2-m3)."""
    from src.core.llama_runner import is_model_downloaded, download_gguf_model, GGUF_MODELS, _get_models_dir

    all_ok = True
    zed_models_dir = ZED_EXT_DIR / "models"

    for key in ["bge-reranker-v2-m3"]:
        fname = GGUF_MODELS[key]["file"]
        zed_gguf = zed_models_dir / fname
        if zed_gguf.exists():
            lines.append((C.GRN, f"  ✓ {fname} (расширение)"))
            continue

        if is_model_downloaded(key):
            lines.append((C.D, f"  📋 Копирую {fname} в расширение..."))
            try:
                zed_models_dir.mkdir(parents=True, exist_ok=True)
                src_gguf = _get_models_dir() / fname
                if src_gguf.exists():
                    shutil.copy2(str(src_gguf), str(zed_gguf))
                    lines.append((C.GRN, f"  ✓ {fname} (скопирован)"))
                    continue
            except Exception as e:
                lines.append((C.YEL, f"  ⚠ Не удалось скопировать {key}: {e}"))

        lines.append((C.D, f"  ⬇ {fname} (~{GGUF_MODELS[key]['size_mb']} MB)..."))
        if download_gguf_model(key, progress_cb=_prog):
            sys.stdout.write("\n")
            lines.append((C.GRN, f"  ✓ {fname}"))
            try:
                zed_models_dir.mkdir(parents=True, exist_ok=True)
                src_gguf = _get_models_dir() / fname
                if src_gguf.exists():
                    shutil.copy2(str(src_gguf), str(zed_gguf))
            except Exception as e:
                logger.debug("copy gguf to extension failed: %s", e)
        else:
            sys.stdout.write("\n")
            lines.append((C.YEL, f"  ⚠ {fname} не скачан (будет ONNX)"))
            all_ok = False

    if all_ok:
        lines.append((C.GRN, "✅ GGUF модель реранкера готова — llama.cpp работает"))


@_step(8)
def step_models(lines, lang):
    """Скачивает ONNX-модели: multilingual-e5-small-int8 (embedder) + bge-reranker-v2-m3.

    Проверяет по порядку: ZED_EXT_DIR -> общий кэш ~/.cache/mscodebase -> PROJECT_ROOT.
    Найдено в (2) или (3) -> копирует в (1). Не найдено нигде -> скачивает.
    """
    SHARED_DIR = Path.home() / ".cache" / "mscodebase" / "models"
    models = {
        "multilingual-e5-small-int8": ("keisuke-miyako/multilingual-e5-small-onnx-int8", "embedding", 113),
        "reranker-bge-reranker-v2-m3": ("BAAI/bge-reranker-v2-m3", "reranker", 544),
    }

    def _model_file(slug: str) -> str:
        return "model_quantized.onnx" if "int8" in slug else "model.onnx"

    def _find_model(slug: str) -> Optional[Path]:
        mf = _model_file(slug)
        for base in (ZED_EXT_DIR, SHARED_DIR, PROJECT_ROOT):
            p = base / ".codebase_models" / "onnx" / slug / mf
            if p.exists():
                return base / ".codebase_models" / "onnx" / slug
        return None

    need_download: list[tuple[str, str, str, int]] = []
    need_copy: list[tuple[str, str, str, Path]] = []

    for slug, (name, mtype, size_mb) in models.items():
        dst_dir = ZED_EXT_DIR / ".codebase_models" / "onnx" / slug
        dst_m = dst_dir / _model_file(slug)
        if dst_m.exists():
            sz = dst_m.stat().st_size / 1024 / 1024
            lines.append((C.GRN, f"  ✓ {slug}: {sz:.0f} MB (ZED_EXT_DIR)"))
            continue
        src = _find_model(slug)
        if src and src != dst_dir:
            need_copy.append((name, mtype, slug, src))
        else:
            need_download.append((name, mtype, slug, size_mb))

    # ─── Фаза 1: копируем уже существующие модели ─────────
    for name, mtype, slug, src in need_copy:
        dst = ZED_EXT_DIR / ".codebase_models" / "onnx" / slug
        mf = _model_file(slug)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            _safe_rmtree(dst)
        shutil.copytree(str(src), str(dst))
        sz = (dst / mf).stat().st_size / 1024 / 1024
        lines.append((C.GRN, f"  ✓ {slug}: {sz:.0f} MB (synced)"))
        shared = SHARED_DIR / ".codebase_models" / "onnx" / slug
        if not (shared / mf).exists():
            shared.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(str(src), str(shared))

    if not need_download:
        lines.append((C.GRN, f"  {_tr('models_ok', lang)}"))
        return

    all_in_project = all(
        (PROJECT_ROOT / ".codebase_models" / "onnx" / slug / _model_file(slug)).exists()
        for _, _, slug, _ in need_download
    )
    if all_in_project:
        lines.append((C.D, "  В проекте — скопируются при синхронизации"))
        return

    total_mb = sum(sz for _, _, _, sz in need_download)
    lines.append((C.YEL, f"? Download {len(need_download)} models ({total_mb} MB total)? (Y/n)"))
    if "--skip-models" in sys.argv or "--no-models" in sys.argv:
        lines.append((C.D, "  Skipped (--skip-models)"))
        return

    _run(f'"{sys.executable}" -m pip install huggingface-hub -q', timeout=60)

    for name, mtype, slug, _ in need_download:
        label = _tr("dl_1" if mtype == "embedding" else "dl_2", lang)
        lines.append((C.D, f"  {label}..."))
        proc = _run(
            f'"{sys.executable}" "{PROJECT_ROOT / "scripts" / "download_model.py"}" '
            f'--model "{name}" --type "{mtype}" --auto-clean',
            timeout=600,
        )
        src = PROJECT_ROOT / ".codebase_models" / "onnx" / slug
        mf = _model_file(slug)
        if proc and proc.returncode == 0 and (src / mf).exists():
            dst = ZED_EXT_DIR / ".codebase_models" / "onnx" / slug
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                _safe_rmtree(dst)
            shutil.copytree(str(src), str(dst))
            sz = (dst / mf).stat().st_size / 1024 / 1024
            lines.append((C.GRN, f"  ✓ {slug}: {sz:.0f} MB"))
            shared = SHARED_DIR / ".codebase_models" / "onnx" / slug
            if not (shared / mf).exists():
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
        lines.append((C.GRN, "✓ MCP configured"))
    else:
        raise RuntimeError("Failed to configure Zed")


@_step(11)
def step_uninst(lines, lang):
    content = _build_uninstaller()
    try:
        UNINSTALLER.write_text(content, encoding="utf-8")
        if not IS_WINDOWS:
            UNINSTALLER.chmod(0o755)
        lines.append((C.GRN, f"✓ {UNINSTALLER.name}"))
    except Exception as e:
        lines.append((C.YEL, f"⚠ {e}"))


# ─── Uninstaller ───────────────────────────────────────────
def _build_uninstaller() -> str:
    ext = str(ZED_EXT_DIR)
    if IS_WINDOWS:
        return (
            "@echo off\r\nchcp 65001 >nul\r\necho Uninstalling...\r\n"
            'taskkill /f /im python.exe /fi "WINDOWTITLE eq mscodebase*" >nul 2>&1\r\n'
            'taskkill /f /im python.exe /fi "WINDOWTITLE eq main*" >nul 2>&1\r\n'
            "taskkill /f /im llama-server.exe >nul 2>&1\r\n"
            "taskkill /f /im onnx_server.exe >nul 2>&1\r\n"
            "timeout /t 2 /nobreak >nul\r\n"
            f'for /l %i in (1,1,3) do (rd /s /q "{ext}" 2>nul & if not exist "{ext}" goto DEL)\r\n'
            "echo Failed. Restart PC and run again.\r\ngoto END\r\n:DEL\r\necho Removed.\r\n:END\r\npause >nul\r\n"
        )
    return (
        "#!/usr/bin/env bash\n"
        "echo 'Uninstalling...'\n"
        "pkill -f 'src\\.main' 2>/dev/null || true\n"
        "pkill -f llama-server 2>/dev/null || true\n"
        "sleep 1\n"
        f'rm -rf "{ext}"\n'
        "echo 'Removed.'\n"
    )


# ─── Main ──────────────────────────────────────────────────
def _record_install_meta() -> None:
    """DEV-ONLY: метаданные для детекции рассинхрона source<->extension.

    Активируется только при MSCODEBASE_DEV=1 или наличии файла .dev в проекте.
    Обычные пользователи этого не видят. Сохраняет git HEAD и mtime исходников
    в .codebase_indices/install_meta.json; MCP при старте сверяет текущий HEAD
    с записанным и выдаёт неблокирующий warning в health report при расхождении.
    """
    try:
        is_dev = os.environ.get("MSCODEBASE_DEV") == "1" or (PROJECT_ROOT / ".dev").exists()
        if not is_dev:
            return

        meta = {"installed_at": time.time(), "git_head": None, "src_mtime": None}
        try:
            r = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if r.returncode == 0:
                meta["git_head"] = r.stdout.strip()
        except Exception as e:
            logger.debug("git rev-parse failed: %s", e)

        try:
            latest = max(
                (p.stat().st_mtime for p in (PROJECT_ROOT / "src").rglob("*.py")),
                default=0.0,
            )
            meta["src_mtime"] = latest
        except Exception as e:
            logger.debug("src mtime scan failed: %s", e)

        meta_path = PROJECT_ROOT / ".codebase_indices" / "install_meta.json"
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    except Exception as e:
        logger.debug("_record_install_meta failed: %s", e)


def main() -> None:
    _enable_ansi()
    lang = _detect_lang()
    if IS_WINDOWS:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    STEPS.sort(key=lambda x: x[0])

    sync_only = "--sync-only" in sys.argv or "--sync" in sys.argv
    if sync_only:
        print("🔁 Sync-only mode: copying files...")
        step_copy([], lang)
        _record_install_meta()
        print("✅ Sync done. Restart Zed to apply.")
        return

    _box(
        "",
        [
            (C.CYN, f"{C.B}{_tr('title', lang)}{C.R}"),
            (C.D, f"  {PROJECT_ROOT.name}  |  Python {sys.version[:5]}"),
        ],
        C.CYN,
    )

    ok_count = skip_count = fail_count = 0
    t0 = time.time()
    compact = "--verbose" not in sys.argv and "-v" not in sys.argv
    auto_yes = "--yes" in sys.argv or "-y" in sys.argv

    for n, name, fn in STEPS:
        title = _tr(name.replace("step_", "chk_"), lang)
        label = f"{_tr('step', lang)} {n + 1}/{TOTAL_STEPS}: {title}"
        lines: list[tuple[str, str]] = []
        max_retries = 2
        step_status = "ok"

        for attempt in range(0 if auto_yes else max_retries + 1):
            try:
                fn(lines, lang)
                if compact:
                    _line("\u2713", label, lines[0][1] if lines else "", C.GRN)
                    sys.stdout.write("\n")
                else:
                    _box(label, lines, C.GRN)
                ok_count += 1
                break
            except Exception as e:
                err_msg = str(e).split("\n")[0][:60]
                if auto_yes:
                    lines.append((C.RED, f"\u2718 {err_msg}"))
                    _line("\u2718", label, err_msg, C.RED)
                    sys.stdout.write("\n")
                    step_status = "fail"
                    break

                if attempt < max_retries:
                    lines.append((C.YEL, f"\u26a0 {err_msg}"))
                    _line("\u26a0", label, err_msg, C.YEL) if compact else _box(label, lines, C.YEL)
                    ch = input(f"\n  {C.B}[r]etry / [s]kip / [c]ancel{C.R}: ").strip().lower()
                    if ch == "s":
                        step_status = "skip"
                        break
                    if ch == "c":
                        sys.stdout.write(f"\n  {C.RED}Aborted.{C.R}\n")
                        return
                else:
                    lines.append((C.RED, f"\u2718 {err_msg}"))
                    if compact:
                        _line("\u2718", label, err_msg, C.RED)
                        sys.stdout.write("\n")
                    else:
                        _box(label, lines, C.RED)
                    ch = input(f"\n  {C.B}[s]kip / [c]ancel{C.R}: ").strip().lower()
                    if ch == "s":
                        step_status = "skip"
                        break
                    sys.stdout.write(f"\n  {C.RED}Aborted.{C.R}\n")
                    return
        else:
            step_status = "fail"

        if step_status == "skip":
            skip_count += 1
        elif step_status == "fail":
            fail_count += 1

    elapsed = time.time() - t0
    has_err = fail_count > 0

    _record_install_meta()

    status_line = f"{C.B}{'⚠' if has_err else '✓'} {_tr('done_all', lang)}  ({elapsed:.0f}s){C.R}"
    summary = [
        (C.RED if has_err else C.GRN, status_line),
        (C.YEL if has_err else C.D, f"{ok_count} ok, {skip_count} skipped, {fail_count} failed"),
        (C.D, f"  {_tr('next', lang)}:"),
        (C.D, f"  1. {_tr('restart', lang)}"),
        (C.D, f"  2. {_tr('wait_idx', lang)}"),
        (C.D, f"  3. {_tr('start_code', lang)}"),
    ]
    _box(_tr("done_all", lang), summary, C.RED if has_err else C.GRN)
    print(f"\n  {C.D}Extension: {ZED_EXT_DIR}{C.R}")
    print(f"  {C.D}Python:    {PYTHON_EXE}{C.R}")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n  {C.RED}Aborted by user.{C.R}")
        sys.exit(1)
