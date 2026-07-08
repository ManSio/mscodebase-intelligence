"""
MSCodebase Intelligence — Installer & Updater
=============================================
  • TUI with fixed layout — no scrolling
  • Auto-detect language (en/ru/zh)
  • Step-by-step with live progress
  • 3 install methods: manual / script / agent
"""

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

logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).resolve().parent / "src" / "utils"))
from zed_config import SERVER_NAME, get_zed_config_dir, patch_zed_settings

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
W = 72
TOTAL_STEPS = 10

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
    "cancel": {"en": "Cancel", "ru": "Отмена", "zh": "取消"},
    "yes": {"en": "Yes", "ru": "Да", "zh": "是"},
    "no": {"en": "No", "ru": "Нет", "zh": "否"},
    "select": {"en": "Select", "ru": "Выберите", "zh": "选择"},
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
    "chk_models": {"en": "AI models", "ru": "AI-модели", "zh": "AI模型"},
    "chk_db": {"en": "Database", "ru": "База данных", "zh": "数据库"},
    "chk_zedcfg": {"en": "Zed integration", "ru": "Интеграция в Zed", "zh": "Zed集成"},
    "chk_skills": {"en": "Skills + locale", "ru": "Скиллы + язык", "zh": "技能+语言"},
    "chk_uninst": {"en": "Uninstaller", "ru": "Деинсталлятор", "zh": "卸载程序"},
    "done_all": {
        "en": "Installation complete!",
        "ru": "Установка завершена!",
        "zh": "安装完成！",
    },
    "done_fb": {
        "en": "Installed (fallback mode)",
        "ru": "Установлено (fallback)",
        "zh": "已安装（降级模式）",
    },
    "next": {"en": "Next steps", "ru": "Следующие шаги", "zh": "后续步骤"},
    "restart": {
        "en": "Restart Zed IDE",
        "ru": "Перезапустите Zed IDE",
        "zh": "重启Zed",
    },
    "wait_index": {
        "en": "Open project → wait for indexing",
        "ru": "Откройте проект → дождитесь индексации",
        "zh": "打开项目→等待索引",
    },
    "code": {"en": "Start coding!", "ru": "Начинайте кодить!", "zh": "开始编码！"},
    "lm_off": {
        "en": "LM Studio not found. Install models manually.",
        "ru": "LM Studio не найден. Установите модели вручную.",
        "zh": "未找到LM Studio。请手动安装模型。",
    },
    "dl_model": {
        "en": "Download models? (Y/n)",
        "ru": "Скачать модели? (Y/n)",
        "zh": "下载模型？(Y/n)",
    },
    "dl_emb": {
        "en": "Embedding model (bge-m3, 438 MB)",
        "ru": "Модель эмбеддинга (bge-m3, 438 МБ)",
        "zh": "嵌入模型(bge-m3, 438 MB)",
    },
    "dl_rerank": {
        "en": "Reranker model (bge-reranker, 636 MB)",
        "ru": "Модель реранкера (bge-reranker, 636 МБ)",
        "zh": "重排序模型(bge-reranker, 636 MB)",
    },
    "model_ok": {
        "en": "ONNX models installed, zero garbage",
        "ru": "ONNX модели установлены, мусора нет",
        "zh": "ONNX模型已安装，无垃圾",
    },
    "lm_ok": {
        "en": "LM Studio available",
        "ru": "LM Studio доступен",
        "zh": "LM Studio可用",
    },
    "killed": {
        "en": "Killed {} process(es)",
        "ru": "Остановлено {} процессов",
        "zh": "已终止 {} 个进程",
    },
    "no_proc": {
        "en": "No running processes",
        "ru": "Нет запущенных процессов",
        "zh": "没有运行中的进程",
    },
    "files_copied": {
        "en": "{} files copied",
        "ru": "{} файлов скопировано",
        "zh": "已复制 {} 个文件",
    },
    "copy_files": {
        "en": "Copying files ({} items)",
        "ru": "Копирование файлов ({})",
        "zh": "正在复制文件 ({})",
    },
    "inst_pkgs": {
        "en": "Installing packages",
        "ru": "Установка пакетов",
        "zh": "正在安装依赖",
    },
    "pkgs_ok": {
        "en": "{} packages installed",
        "ru": "{} пакетов установлено",
        "zh": "已安装 {} 个包",
    },
    "pip_fail": {
        "en": "pip install failed",
        "ru": "pip install не удался",
        "zh": "pip安装失败",
    },
    "db_notfound": {
        "en": "Not found — will create on first run",
        "ru": "Не найдена — будет создана при запуске",
        "zh": "未找到—首次运行时创建",
    },
    "db_tables": {
        "en": "{} table(s), {} fields",
        "ru": "{} таблиц(ы), {} полей",
        "zh": "{} 个表，{} 个字段",
    },
    "db_empty": {
        "en": "Empty — will populate on indexing",
        "ru": "Пуста — заполнится при индексации",
        "zh": "为空—索引时填充",
    },
    "mcp_cfg": {"en": "MCP configured", "ru": "MCP настроен", "zh": "MCP已配置"},
    "uninst_ok": {
        "en": "Uninstaller ready",
        "ru": "Деинсталлятор готов",
        "zh": "卸载程序已就绪",
    },
    "time": {"en": "Time", "ru": "Время", "zh": "用时"},
    "ext_dir": {"en": "Extension", "ru": "Расширение", "zh": "扩展目录"},
    "python": {"en": "Python", "ru": "Python", "zh": "Python"},
}


def _tr(key, lang="en"):
    d = LANG.get(key, {})
    return d.get(lang, d.get("en", key))


# ─── ANSI ────────────────────────────────────────────────────
class C:
    R = "\033[0m"
    B = "\033[1m"
    D = "\033[2m"
    RED = "\033[91m"
    GRN = "\033[92m"
    YEL = "\033[93m"
    BLU = "\033[94m"
    CYN = "\033[96m"


def _ea():
    if sys.platform == "win32":
        os.system("")


def _tw():
    try:
        return os.get_terminal_size().columns
    except:
        return 80


# ─── TUI engine ─────────────────────────────────────────────
# The terminal is divided into 4 fixed regions:
#   Lines 0-3:   Title banner (static)
#   Lines 4-N:   Current step content (redrawn each step)
#   Last line:   Progress/status line (updated in-place)

_SCR = []  # stores last rendered lines for cursor math


def _clear():
    """Clear entire terminal and move to (0,0)."""
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def _cls(n=1):
    """Clear n lines upward."""
    if n > 0:
        sys.stdout.write(f"\033[{n}A\033[J")


def _goto(row=0):
    """Move cursor to absolute row (0 = top)."""
    sys.stdout.write(f"\033[{row};0H")


def _box(title, inner, color=C.CYN):
    """Draw a box with title and inner lines. inner = list of (color, text) pairs."""
    w = W
    sys.stdout.write(
        f"  {color}┌─ {C.B}{title}{C.R}{color} {'─' * (w - 6 - len(title))}┐{C.R}\n"
    )
    for col, txt in inner:
        clean = re.sub(r"\033\[[0-9;]*m", "", txt)
        pad = max(0, w - 4 - len(clean))
        sys.stdout.write(f"  {color}│ {col}{txt}{' ' * pad}{color} │{C.R}\n")
    sys.stdout.write(f"  {color}└{'─' * (w - 2)}┘{C.R}\n")
    sys.stdout.flush()


def _prog(label, pct, detail="", color=C.GRN):
    """Draw a single-line progress bar (replaces current line)."""
    w = W
    bar_w = w - 20
    fill = max(0, min(bar_w, int(bar_w * pct / 100)))
    bar = f"{color}{'█' * fill}{C.D}{'░' * (bar_w - fill)}{C.R}"
    line = f"  {bar} {pct:3d}%  {C.D}{detail}{C.R}"
    sys.stdout.write(f"\r{' ' * w}\r{line}")
    sys.stdout.flush()


def _stat(msg, color=C.GRN, symbol="✔", newline=True):
    """Status line: symbol + message."""
    c = C.GRN if symbol == "✔" else C.YEL if symbol == "⚠" else C.RED
    line = f"  {c}{symbol}{C.R}  {color}{msg}{C.R}"
    sys.stdout.write(line + ("\n" if newline else ""))
    sys.stdout.flush()


# ─── Language ────────────────────────────────────────────────
def _detect_lang():
    try:
        full = locale.getlocale(locale.LC_MESSAGES)[0] or ""
        prefix = full[:2].lower()
        m = {"ru": "ru", "uk": "ru", "zh": "zh", "cn": "zh"}
        return m.get(prefix, "en")
    except:
        return None


def _ask_lang():
    _clear()
    print(f"\n  {C.B}{C.CYN}{_tr('select', 'en')}:{C.R}\n")
    print(f"    {C.CYN}1.{C.R}  English")
    print(f"    {C.CYN}2.{C.R}  Русский")
    print(f"    {C.CYN}3.{C.R}  中文\n")
    ch = input(f"  {C.B}[1-3]{C.R}: ").strip()
    return {"1": "en", "2": "ru", "3": "zh"}.get(ch, "en")


# ─── Steps ───────────────────────────────────────────────────
STEPS = [
    "chk_zed",
    "chk_lm",
    "chk_proc",
    "chk_copy",
    "chk_venv",
    "chk_pip",
    "chk_models",
    "chk_db",
    "chk_zedcfg",
    "chk_uninst",
]


def _run_step(n, lang, fn):
    """Run a step function, render its output in a box, return result."""
    title = _tr(STEPS[n], lang)
    lines = []
    fn(lines, lang)
    _box(f"{_tr('step', lang)} {n + 1}/{TOTAL_STEPS}: {title}", lines)
    return lines


# ══════════════════════════════════════════════════════════════
# Step implementations
# ══════════════════════════════════════════════════════════════


def step_zed(lines, lang):
    zcd = get_zed_config_dir()
    try:
        zcd.mkdir(parents=True, exist_ok=True)
        lines.append((C.GRN, f"✔ {_tr('ok', lang)}: {C.D}{zcd}{C.R}"))
    except Exception as e:
        lines.append((C.RED, f"✘ {e}"))


def step_lm(lines, lang):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(3)
    ok = False
    try:
        ok = sock.connect_ex((LM_HOST, LM_PORT)) == 0
    except:
        pass
    finally:
        sock.close()
    if ok:
        lines.append((C.GRN, f"✔ {_tr('lm_ok', lang)} {LM_HOST}:{LM_PORT}"))
        try:
            import urllib.request

            resp = urllib.request.urlopen(
                f"http://{LM_HOST}:{LM_PORT}/v1/models", timeout=3
            )
            models = [m.get("id", "?") for m in json.loads(resp.read())["data"]]
            for m in models[:3]:
                lines.append((C.D, f"  · {m}"))
        except:
            pass
    else:
        lines.append((C.YEL, f"⚠ {_tr('lm_off', lang)}"))


def step_proc(lines, lang):
    if sys.platform == "win32":
        import signal

        out = subprocess.run(
            ["tasklist", "/FO", "CSV"], capture_output=True, text=True, timeout=5
        ).stdout
        killed = 0
        for line in out.split("\n"):
            if "mscodebase" in line.lower() or (
                "python" in line.lower() and "mcp" in line.lower()
            ):
                try:
                    pid = line.split(",")[1].strip('"')
                    os.kill(int(pid), signal.SIGTERM)
                    killed += 1
                except:
                    pass
        if killed:
            time.sleep(1)
            lines.append((C.GRN, f"✔ {_tr('killed', lang).format(killed)}"))
        else:
            lines.append((C.D, f"· {_tr('no_proc', lang)}"))
    ZED_EXT_DIR.mkdir(parents=True, exist_ok=True)


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
    }
    items = [i for i in PROJECT_ROOT.iterdir() if i.name not in skip]
    # Clean stale
    if ZED_EXT_DIR.exists():
        for item in ZED_EXT_DIR.iterdir():
            if item.name in skip:
                continue
            if not (PROJECT_ROOT / item.name).exists():
                try:
                    if item.is_dir():
                        shutil.rmtree(str(item), ignore_errors=True)
                    else:
                        item.unlink()
                except:
                    pass
    # Copy with simple progress
    for idx, item in enumerate(items):
        dst = ZED_EXT_DIR / item.name
        try:
            if dst.exists():
                if dst.is_dir():
                    shutil.rmtree(str(dst), ignore_errors=True)
                else:
                    dst.unlink()
            if item.is_dir():
                shutil.copytree(str(item), str(dst))
            else:
                shutil.copy2(str(item), str(dst))
        except:
            pass
        pct = int((idx + 1) / len(items) * 100)
        _prog(_tr("copy_files", lang).format(len(items)), pct, item.name, C.BLU)
    _prog("", 100, "", C.R)
    sys.stdout.write("\n")
    lines.append((C.GRN, f"✔ {_tr('files_copied', lang).format(len(items))}"))


def step_venv(lines, lang):
    if VENV_DIR.exists():
        lines.append((C.GRN, f"✔ {_tr('ok', lang)}: {C.D}{VENV_DIR}{C.R}"))
        return
    r = subprocess.run(
        f'"{sys.executable}" -m venv "{VENV_DIR}"',
        shell=True,
        timeout=60,
        capture_output=True,
    )
    if r.returncode == 0:
        lines.append((C.GRN, f"✔ {_tr('ok', lang)}: {C.D}{VENV_DIR}{C.R}"))
    else:
        lines.append((C.RED, f"✘ {r.stderr.decode()[:200]}"))


def step_pip(lines, lang):
    # Upgrade pip
    subprocess.run(
        f'"{PYTHON_EXE}" -m pip install --upgrade pip',
        shell=True,
        timeout=60,
        capture_output=True,
    )
    # Install deps
    req = ZED_EXT_DIR / "requirements.txt"
    if not req.exists():
        lines.append((C.RED, "✘ requirements.txt not found"))
        return
    n_pkgs = len(req.read_text().splitlines())
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
            last = line[:50]
        _prog(_tr("inst_pkgs", lang), 50, last, C.BLU)
    proc.wait()
    if proc.returncode == 0:
        _prog("", 100, "", C.R)
        sys.stdout.write("\n")
        lines.append((C.GRN, f"✔ {_tr('pkgs_ok', lang).format(n_pkgs)}"))
    else:
        _prog("", 0, "FAILED", C.RED)
        sys.stdout.write("\n")
        lines.append((C.RED, f"✘ {_tr('pip_fail', lang)}"))


def step_models(lines, lang):
    """Download ONNX models with user choice of size."""
    emb_types = {
        "light": ("BAAI/bge-small-en-v1.5", 384, "~50 MB"),
        "balanced": ("BAAI/bge-base-en-v1.5", 768, "~150 MB"),
        "full": ("BAAI/bge-m3", 1024, "~1.3 GB"),
    }
    # Check what's already downloaded
    for size, (name, dim, sz) in emb_types.items():
        slug = name.split("/")[-1].lower()
        p = PROJECT_ROOT / ".codebase_models" / "onnx" / slug / "model.onnx"
        if p.exists():
            real_sz = p.stat().st_size / 1024 / 1024
            lines.append(
                (C.GRN, f"✔ Embedded model: {name} ({dim}dim, {real_sz:.0f} MB)")
            )
            return  # already have one

    # No model found — ask user
    lines.append((C.YEL, f"⚠ No embedding model found. Choose size:"))
    # Print options inline
    print(
        f"  {C.CYN}1.{C.R} Light   (bge-small-en-v1.5,  384dim,  ~50 MB,  good quality)"
    )
    print(
        f"  {C.CYN}2.{C.R} Balanced(bge-base-en-v1.5,  768dim, ~150 MB,  high quality) [default]"
    )
    print(
        f"  {C.CYN}3.{C.R} Full    (bge-m3,           1024dim, ~1.3 GB,  best quality)"
    )
    choice = input(f"  {C.B}Select [1-3]{C.R}: ").strip()
    size_map = {"1": "light", "2": "balanced", "3": "full"}
    chosen = size_map.get(choice, "balanced")
    model_name, dim, _ = emb_types[chosen]
    lines.append((C.D, f"  Downloading {model_name} ({dim}dim)..."))

    # Install deps + download
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "huggingface-hub",
            "torch",
            "onnxruntime",
            "transformers",
        ],
        capture_output=True,
        timeout=120,
    )
    proc = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "download_model.py"),
            "--model",
            model_name,
            "--type",
            "embedding",
            "--auto-clean",
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    slug = model_name.split("/")[-1].lower()
    p = PROJECT_ROOT / ".codebase_models" / "onnx" / slug / "model.onnx"
    if proc.returncode == 0 and p.exists():
        real_sz = p.stat().st_size / 1024 / 1024
        lines.append((C.GRN, f"✔ {model_name} ready: {dim}dim, {real_sz:.0f} MB"))


def step_db(lines, lang):
    db_path = PROJECT_ROOT / ".codebase_indices" / "lancedb_v2"
    if not db_path.exists():
        lines.append((C.D, f"· {_tr('db_notfound', lang)}"))
        return
    try:
        import lancedb

        db = lancedb.connect(str(db_path))
        tables = db.list_tables()
        if tables:
            t = db.open_table(tables[0])
            fields = [f.name for f in t.schema]
            lines.append(
                (C.GRN, f"✔ {_tr('db_tables', lang).format(len(tables), len(fields))}")
            )
        else:
            lines.append((C.D, f"· {_tr('db_empty', lang)}"))
    except Exception as e:
        lines.append((C.YEL, f"⚠ {e}"))


def step_zedcfg(lines, lang):
    cmd = f"{PYTHON_EXE} -u -m src.main"
    if patch_zed_settings(
        cmd,
        mode="global",
        lsp_config=None,
        languages_config=None,
        install_path=str(ZED_EXT_DIR),
    ):
        lines.append((C.GRN, f"✔ {_tr('mcp_cfg', lang)}: {C.D}{cmd}{C.R}"))
    else:
        lines.append((C.RED, "✘ Failed to configure"))


def step_uninst(lines, lang):
    content = _build_uninstall_bat()
    try:
        UNINSTALLER.write_text(content, encoding="utf-8")
        lines.append(
            (C.GRN, f"✔ {_tr('uninst_ok', lang)}: {C.D}{UNINSTALLER.name}{C.R}")
        )
    except Exception as e:
        lines.append((C.YEL, f"⚠ {e}"))


# ─── Utils ───────────────────────────────────────────────────
def _build_uninstall_bat():
    py = str(PYTHON_EXE)
    ext = str(ZED_EXT_DIR)
    lines = [
        "@echo off",
        "chcp 65001 >nul",
        "echo ================================================",
        "echo  Uninstalling MSCodebase Intelligence...",
        "echo ================================================",
        "echo.",
        "echo [1/3] Stopping processes...",
        'taskkill /f /im python.exe /fi "WINDOWTITLE eq mscodebase*" >nul 2>&1',
        'taskkill /f /im python.exe /fi "WINDOWTITLE eq main*" >nul 2>&1',
        "timeout /t 2 /nobreak >nul",
        "echo.",
        "echo [2/3] Removing Zed settings...",
        # Python inline script — must avoid braces that confuse batch + f-strings
        # We write a temp .py file instead of inline -c to avoid quoting hell
        'if exist "%TEMP%\\_mscodebase_uninstall.py" del "%TEMP%\\_mscodebase_uninstall.py"',
        'echo import json, pathlib, os, re > "%TEMP%\\_mscodebase_uninstall.py"',
        'echo import sys; p = pathlib.Path(os.environ.get("APPDATA", "")) / "Zed" / "settings.json" >> "%TEMP%\\_mscodebase_uninstall.py"',
        'echo if not p.exists(): p = pathlib.Path.home() / ".config" / "zed" / "settings.json" >> "%TEMP%\\_mscodebase_uninstall.py"',
        'echo if p.exists(): >> "%TEMP%\\_mscodebase_uninstall.py"',
        'echo     content = p.read_text(encoding="utf-8") >> "%TEMP%\\_mscodebase_uninstall.py"',
        'echo     content = re.sub(r"^\\s*//.*$", "", content, flags=re.MULTILINE) >> "%TEMP%\\_mscodebase_uninstall.py"',
        'echo     import json as j; d = j.loads(content) >> "%TEMP%\\_mscodebase_uninstall.py"',
        'echo     d.get("context_servers", {}).pop("mscodebase-intelligence", None) >> "%TEMP%\\_mscodebase_uninstall.py"',
        'echo     d.get("lsp", {}).pop("mscodebase-lsp", None) >> "%TEMP%\\_mscodebase_uninstall.py"',
        'echo     d.pop("mscodebase", None) >> "%TEMP%\\_mscodebase_uninstall.py"',
        'echo     p.write_text(j.dumps(d, indent=2), encoding="utf-8") >> "%TEMP%\\_mscodebase_uninstall.py"',
        f'"{py}" "%TEMP%\\_mscodebase_uninstall.py"',
        'del "%TEMP%\\_mscodebase_uninstall.py"',
        "echo.",
        "echo [3/3] Removing files...",
        f'for /l %%i in (1,1,3) do (rd /s /q "{ext}" 2>nul & if not exist "{ext}" goto :DEL)',
        "echo Failed to remove. Try restarting your PC.",
        "goto :END",
        ":DEL",
        "echo Removed.",
        ":END",
        "echo.",
        "echo Restart Zed IDE. Press any key to exit.",
        "pause >nul",
    ]
    return "\r\n".join(lines)


def _ensure_onnx_deps():
    """Install torch/onnxruntime/transformers if not present."""
    for mod in ["torch", "onnxruntime", "transformers", "huggingface-hub"]:
        r = subprocess.run([sys.executable, "-c", f"import {mod}"], capture_output=True)
        if r.returncode != 0:
            _prog("Installing ML dependencies", 0, mod, C.BLU)
            subprocess.run(
                [sys.executable, "-m", "pip", "install", mod, "-q"],
                capture_output=True,
                timeout=120,
            )
    _prog("", 100, "", C.R)
    sys.stdout.write("\n")


# ══════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════
def main():
    _ea()
    lang = _detect_lang() or _ask_lang()
    _clear()

    # ── Render top banner (static, never moves) ──
    banner_lines = [
        (C.CYN, f"{C.B}{_tr('title', lang)}{C.R}"),
        (C.D, f"  {PROJECT_ROOT.name}  |  {sys.executable}"),
    ]
    _box("", banner_lines, C.CYN)

    # ── Run each step ──
    results = []
    start_t = time.time()

    for n in range(TOTAL_STEPS):
        # Each step redraws ONLY the step box area
        title = _tr(STEPS[n], lang)
        label = f"{_tr('step', lang)} {n + 1}/{TOTAL_STEPS}: {title}"

        lines = []  # will be filled by step fn

        # Collect output
        if n == 0:
            step_zed(lines, lang)
        elif n == 1:
            step_lm(lines, lang)
        elif n == 2:
            step_proc(lines, lang)
        elif n == 3:
            step_copy(lines, lang)
        elif n == 4:
            step_venv(lines, lang)
        elif n == 5:
            step_pip(lines, lang)
        elif n == 6:
            step_models(lines, lang)
        elif n == 7:
            step_db(lines, lang)
        elif n == 8:
            step_zedcfg(lines, lang)
        elif n == 9:
            step_uninst(lines, lang)

        # Draw the step box (overwrites previous step area)
        # Each box title + inner lines + bottom = 3 + len(lines)
        # Move cursor to line 5 (after banner) and draw
        _goto(5)
        _box(label, lines)

        results.append(lines)

    # ── Summary ──
    lm_ok = any("LM Studio available" in str(r) for r in results[1])
    models_ok = any("ONNX models installed" in str(r) for r in results[6])
    has_err = any(any(col == C.RED for col, _ in r) for r in results)

    _goto(5 + 3 + max(len(r) for r in results) + 1)
    summary = [
        (
            C.GRN if not has_err else C.YEL,
            f"{C.B}{'✔' if not has_err else '⚠'} {_tr('done_all' if not has_err else 'done_fb', lang)}{C.R}",
        ),
        (C.D, f"  {_tr('next', lang)}:"),
        (C.D, f"  {C.CYN}1.{C.R} {_tr('restart', lang)}"),
        (C.D, f"  {C.CYN}2.{C.R} {_tr('wait_index', lang)}"),
        (C.D, f"  {C.CYN}3.{C.R} {_tr('code', lang)}"),
    ]
    if not models_ok:
        summary.append((C.YEL, f"  {_tr('lm_off', lang)}"))
    if not lm_ok and models_ok:
        summary.append((C.GRN, f"  {_tr('model_ok', lang)}"))

    elapsed = time.time() - start_t
    summary.insert(1, (C.D, f"  {_tr('time', lang)}: {elapsed:.0f}s"))

    _box(f"{_tr('done_all', lang)}", summary, C.GRN if not has_err else C.YEL)

    # Footer
    print(f"\n  {C.D}{_tr('ext_dir', lang)}: {ZED_EXT_DIR}{C.R}")
    print(f"  {C.D}{_tr('python', lang)}:    {PYTHON_EXE}{C.R}")
    print()


if __name__ == "__main__":
    main()
