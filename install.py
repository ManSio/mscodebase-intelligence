"""
MSCodebase Intelligence — Super Smart Installer & Updater
=========================================================
Features:
  • Auto-detect OS language (en/ru/zh), fallback to interactive menu
  • Beautiful box-drawing UI (╔═╗║╚═╝) — static layout, no scrolling
  • Progressive steps with in-place progress bar
  • Atomic updates, LM Studio check, venv isolation, Zed integration
  • Multi-language: English, Русский, 中文
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
from zed_config import (
    SERVER_NAME,
    get_zed_config_dir,
    patch_zed_settings,
)

# ─── Constants ──────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
ZED_EXT_DIR = (
    Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")))
    / "Zed"
    / "extensions"
    / "mscodebase-intelligence"
)
VENV_DIR = ZED_EXT_DIR / "venv"
if sys.platform == "win32":
    PYTHON_EXE = VENV_DIR / "Scripts" / "python.exe"
else:
    PYTHON_EXE = VENV_DIR / "bin" / "python3"
UNINSTALLER = ZED_EXT_DIR / "uninstall.bat"
LM_STUDIO_HOST = os.environ.get("LM_STUDIO_HOST", "127.0.0.1")
LM_STUDIO_PORT = int(os.environ.get("LM_STUDIO_PORT", "1234"))

TOTAL_STEPS = 9

# ─── Multi-language strings ────────────────────────────────
LANG = {
    "title": {
        "en": "MSCodeBase Intelligence — Installer & Updater v2.7.0",
        "ru": "MSCodeBase Intelligence — Установщик и Обновление v2.7.0",
        "zh": "MSCodeBase Intelligence — 安装与更新程序 v2.7.0",
    },
    "select_lang": {
        "en": "Select language",
        "ru": "Выберите язык",
        "zh": "选择语言",
    },
    "detected": {
        "en": "Detected",
        "ru": "Обнаружен",
        "zh": "检测到",
    },
    "skip": {
        "en": "Skip",
        "ru": "Пропустить",
        "zh": "跳过",
    },
    "unknown": {
        "en": "Unknown",
        "ru": "Неизвестно",
        "zh": "未知",
    },
    "step": {
        "en": "Step",
        "ru": "Шаг",
        "zh": "步骤",
    },
    "of": {
        "en": "of",
        "ru": "из",
        "zh": "的",
    },
    "check_zed": {
        "en": "Checking Zed IDE",
        "ru": "Проверка Zed IDE",
        "zh": "检查 Zed IDE",
    },
    "zed_found": {
        "en": "Zed config directory found",
        "ru": "Директория настроек Zed найдена",
        "zh": "找到 Zed 配置目录",
    },
    "zed_created": {
        "en": "Created Zed config directory",
        "ru": "Создана директория настроек Zed",
        "zh": "已创建 Zed 配置目录",
    },
    "zed_not_found": {
        "en": "Zed IDE not found. Install Zed first: https://zed.dev",
        "ru": "Zed IDE не найден. Установите Zed: https://zed.dev",
        "zh": "未找到 Zed IDE。请先安装 Zed：https://zed.dev",
    },
    "check_lm": {
        "en": "Checking LM Studio / Ollama",
        "ru": "Проверка LM Studio / Ollama",
        "zh": "检查 LM Studio / Ollama",
    },
    "lm_online": {
        "en": "LM Studio available on",
        "ru": "LM Studio доступен на",
        "zh": "LM Studio 可用在",
    },
    "lm_offline": {
        "en": "LM Studio / Ollama not running. Vector search will be unavailable.",
        "ru": "LM Studio / Ollama не запущен. Векторный поиск будет недоступен.",
        "zh": "LM Studio / Ollama 未运行。向量搜索将不可用。",
    },
    "stop_processes": {
        "en": "Stopping running MCP processes",
        "ru": "Остановка процессов MCP",
        "zh": "停止运行中的 MCP 进程",
    },
    "copy_files": {
        "en": "Copying project files to extension directory",
        "ru": "Копирование файлов проекта в расширение",
        "zh": "将项目文件复制到扩展目录",
    },
    "create_venv": {
        "en": "Creating Python Virtual Environment",
        "ru": "Создание Python Virtual Environment",
        "zh": "创建 Python 虚拟环境",
    },
    "install_deps": {
        "en": "Installing Python dependencies",
        "ru": "Установка Python-зависимостей",
        "zh": "安装 Python 依赖",
    },
    "check_db": {
        "en": "Checking LanceDB database",
        "ru": "Проверка базы данных LanceDB",
        "zh": "检查 LanceDB 数据库",
    },
    "integrate": {
        "en": "Integrating MCP into Zed IDE",
        "ru": "Интеграция MCP в Zed IDE",
        "zh": "将 MCP 集成到 Zed IDE",
    },
    "install_skills": {
        "en": "Installing agent skills and system rules",
        "ru": "Установка скиллов и системных правил",
        "zh": "安装代理技能和系统规则",
    },
    "gen_uninstall": {
        "en": "Generating uninstaller",
        "ru": "Генерация деинсталлятора",
        "zh": "生成卸载程序",
    },
    "complete_success": {
        "en": "INSTALLATION COMPLETE — All systems ready",
        "ru": "УСТАНОВКА ЗАВЕРШЕНА — Все системы готовы",
        "zh": "安装完成 — 所有系统就绪",
    },
    "complete_fallback": {
        "en": "INSTALLED IN FALLBACK MODE — Vector search requires LM Studio",
        "ru": "УСТАНОВЛЕНО В FALLBACK-РЕЖИМЕ — Векторный поиск требует LM Studio",
        "zh": "以降级模式安装 — 向量搜索需要 LM Studio",
    },
    "next_steps": {
        "en": "Next steps",
        "ru": "Следующие шаги",
        "zh": "后续步骤",
    },
    "restart_zed": {
        "en": "Restart Zed IDE",
        "ru": "Перезапустите Zed IDE",
        "zh": "重启 Zed IDE",
    },
    "open_project": {
        "en": "Open a project and wait for indexing",
        "ru": "Откройте проект и дождитесь индексации",
        "zh": "打开项目并等待索引",
    },
    "start_coding": {
        "en": "Start coding — the AI agent is ready!",
        "ru": "Начинайте кодить — AI-агент готов!",
        "zh": "开始编码 — AI 代理已就绪！",
    },
    "venv_exists": {
        "en": "Virtual environment already exists",
        "ru": "Виртуальное окружение уже существует",
        "zh": "虚拟环境已存在",
    },
    "venv_created": {
        "en": "Virtual environment created",
        "ru": "Виртуальное окружение создано",
        "zh": "虚拟环境已创建",
    },
    "deps_ok": {
        "en": "All dependencies installed",
        "ru": "Все зависимости установлены",
        "zh": "所有依赖已安装",
    },
    "deps_fail": {
        "en": "Failed to install Python packages",
        "ru": "Не удалось установить Python-пакеты",
        "zh": "安装 Python 包失败",
    },
    "mcp_ok": {
        "en": "MCP server configured in Zed",
        "ru": "MCP-сервер настроен в Zed",
        "zh": "MCP 服务器已在 Zed 中配置",
    },
    "skills_ok": {
        "en": "Agent skills installed",
        "ru": "Скиллы установлены",
        "zh": "代理技能已安装",
    },
    "select_option": {
        "en": "Select",
        "ru": "Выберите",
        "zh": "选择",
    },
    "cancel": {
        "en": "Cancel",
        "ru": "Отмена",
        "zh": "取消",
    },
    "install": {
        "en": "Install",
        "ru": "Установить",
        "zh": "安装",
    },
}


def _tr(key: str, lang: str = "en") -> str:
    """Translate key to selected language."""
    return LANG.get(key, {}).get(lang, LANG.get(key, {}).get("en", key))


# ─── ANSI Colors ───────────────────────────────────────────
class Color:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"


def _enable_ansi():
    if sys.platform == "win32":
        os.system("")


def _term_width() -> int:
    try:
        return os.get_terminal_size().columns
    except Exception:
        return 80


# ─── Box-drawing UI ────────────────────────────────────────
def _box_top(width: int) -> str:
    return f"  ┌{'─' * (width - 4)}┐"


def _box_bot(width: int) -> str:
    return f"  └{'─' * (width - 4)}┘"


def _box_line(text: str, width: int, color: str = "") -> str:
    """Render a line inside the box with proper padding."""
    # Strip ANSI for width calculation
    clean = re.sub(r"\033\[[0-9;]*m", "", text)
    pad = width - 4 - len(clean)
    if pad < 0:
        pad = 0
    return f"  {color}│ {text}{' ' * pad}│{Color.RESET}"


def _box_title(title: str, width: int, color: str = Color.CYAN) -> str:
    """Centered title line inside box."""
    clean = re.sub(r"\033\[[0-9;]*m", "", title)
    pad = width - 4 - len(clean)
    if pad < 1:
        pad = 1
    left = pad // 2
    right = pad - left
    return f"  {color}│{' ' * left}{Color.BOLD}{title}{Color.RESET}{color}{' ' * right}│{Color.RESET}"


def render_box(title: str, lines: list, width: int = None, color: str = Color.CYAN):
    """Render a complete box with title and content lines."""
    if width is None:
        width = min(_term_width(), 74)
    print()
    print(
        f"  {color}┌─ {Color.BOLD}{title}{Color.RESET}{color}{'─' * (width - 6 - len(title))}┐{Color.RESET}"
    )
    for line in lines:
        print(line)
    print(f"  {color}└{'─' * (width - 2)}┘{Color.RESET}")
    print()


def render_welcome_box(lang: str, width: int = None):
    """Render the welcome banner."""
    if width is None:
        width = min(_term_width(), 74)
    title = _tr("title", lang)
    print()
    print(f"  {'╔' + '═' * (width - 2) + '╗'}")
    print(f"  {'║' + ' ' * (width - 2) + '║'}")
    # Centered title
    clean = re.sub(r"\033\[[0-9;]*m", "", title)
    left = (width - 2 - len(clean)) // 2
    right = width - 2 - len(clean) - left
    print(
        f"  {'║' + ' ' * left + Color.BOLD + Color.CYAN + title + Color.RESET + ' ' * right + '║'}"
    )
    print(f"  {'║' + ' ' * (width - 2) + '║'}")
    print(f"  {'╚' + '═' * (width - 2) + '╝'}")
    print()


def render_step_box(
    step_num: int,
    total: int,
    title: str,
    status_lines: list,
    lang: str,
    width: int = None,
):
    """Render an operating step box with status content."""
    if width is None:
        width = min(_term_width(), 74)
    step_label = f"{_tr('step', lang)} {step_num}/{total}"
    header = f"{step_label}: {title}"
    print(
        f"  {'┌─'} {Color.BOLD}{header}{Color.RESET} {'─' * (width - 6 - len(header))}┐"
    )
    for line in status_lines:
        print(line)
    print(f"  {'└' + '─' * (width - 2) + '┘'}")
    print()


def render_progress_box(
    label: str,
    pct: int,
    detail: str = "",
    elapsed: float = 0,
    eta: float = 0,
    width: int = None,
):
    """Render a progress bar inside a mini-box (updates in-place)."""
    if width is None:
        width = min(_term_width(), 74)
    bar_w = width - 20
    filled = int(bar_w * pct / 100)
    bar = f"{Color.GREEN}{'█' * filled}{Color.DIM}{'░' * (bar_w - filled)}{Color.RESET}"

    lines = [
        f"  │ {bar} {pct:3d}%  {Color.DIM}{detail}{Color.RESET}",
    ]
    if elapsed > 0:
        eta_str = f"ETA: {eta:.0f}s" if eta > 0 else "done"
        lines.append(
            f"  │ {Color.DIM}Elapsed: {elapsed:.0f}s  |  {eta_str}{Color.RESET}"
        )

    # Clear previous and redraw
    print(f"\033[{len(lines) + 3}A", end="")  # Move up
    print(
        f"  {'┌─'} {Color.BOLD}{label}{Color.RESET} {'─' * (width - 6 - len(label))}┐"
    )
    for line in lines:
        print(line)
    print(f"  {'└' + '─' * (width - 2) + '┘'}")
    print()


# ─── Language detection ────────────────────────────────────
def detect_language() -> str:
    """Auto-detect OS language with interactive fallback."""
    detected = None
    try:
        full = locale.getdefaultlocale()[0]  # 'en_US', 'ru_RU', 'zh_CN'
        if full:
            prefix = full[:2].lower()
            lang_map = {
                "ru": "ru",
                "uk": "ru",
                "be": "ru",
                "zh": "zh",
                "cn": "zh",
                "en": "en",
                "de": "en",
                "fr": "en",
                "es": "en",
            }
            detected = lang_map.get(prefix, "en")
    except Exception:
        pass

    render_welcome_box(detected or "en")

    if detected:
        lang_names = {"en": "English", "ru": "Русский", "zh": "中文"}
        name = lang_names.get(detected, "English")
        print(
            f"  {Color.DIM}{_tr('detected', detected)}: {Color.GREEN}{name}{Color.RESET}  ({full if 'full' in dir() else detected})"
        )
        print()
        return detected

    # Interactive menu
    width = min(_term_width(), 74)
    print(f"  {Color.BOLD}{_tr('select_lang', 'en')}:{Color.RESET}")
    print()
    print(f"    {Color.CYAN}1.{Color.RESET}  English")
    print(f"    {Color.CYAN}2.{Color.RESET}  Русский")
    print(f"    {Color.CYAN}3.{Color.RESET}  中文")
    print()
    choice = input(f"  {Color.BOLD}[1-3]{Color.RESET}: ").strip()
    return {"1": "en", "2": "ru", "3": "zh"}.get(choice, "en")


# ─── Utilities ─────────────────────────────────────────────
def ok(text: str):
    print(f"  {Color.GREEN}✔{Color.RESET}  {text}")


def warn(text: str):
    print(f"  {Color.YELLOW}⚠{Color.RESET}  {text}")


def fail(text: str):
    print(f"  {Color.RED}✘{Color.RESET}  {text}")


def info(text: str):
    print(f"  {Color.DIM}·{Color.RESET}  {text}")


def hr():
    width = min(_term_width(), 74)
    print(f"  {'─' * (width - 2)}")


def check_lm_studio_available() -> bool:
    """Ping LM Studio / Ollama on configured port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(3)
    try:
        result = sock.connect_ex((LM_STUDIO_HOST, LM_STUDIO_PORT))
        return result == 0
    except Exception:
        return False
    finally:
        sock.close()


def _stop_extension_processes():
    """Kill any running MCP extension processes."""
    if sys.platform != "win32":
        return
    import signal

    for proc in subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV"],
        capture_output=True,
        text=True,
        timeout=5,
    ).stdout.split("\n"):
        if "mscodebase" in proc.lower() or "mcp_main" in proc.lower():
            try:
                parts = proc.split(",")
                if len(parts) >= 2:
                    pid = parts[1].strip('"')
                    os.kill(int(pid), signal.SIGTERM)
                    time.sleep(0.2)
            except (ValueError, OSError):
                pass


def _clean_stale_files(src: Path, dst: Path) -> int:
    """Remove files from dst that no longer exist in src."""
    count = 0
    if not dst.exists():
        return 0
    for item in dst.iterdir():
        if item.name in (
            ".git",
            "__pycache__",
            "venv",
            ".venv",
            ".codebase_indices",
            ".codebase_models",
            ".pytest_cache",
            ".ruff_cache",
            ".mypy_cache",
            ".zed",
            ".idea",
            ".vscode",
        ):
            continue
        src_item = src / item.name
        if not src_item.exists():
            try:
                if item.is_dir():
                    shutil.rmtree(str(item))
                else:
                    item.unlink()
                count += 1
            except Exception:
                pass
    return count


def check_lm_studio_models() -> list:
    """Get list of loaded models from LM Studio."""
    try:
        import urllib.request

        url = f"http://{LM_STUDIO_HOST}:{LM_STUDIO_PORT}/v1/models"
        resp = urllib.request.urlopen(url, timeout=3)
        data = json.loads(resp.read().decode())
        return [m.get("id", "?") for m in data.get("data", [])]
    except Exception:
        return []


def validate_lancedb_schema(db_path: Path) -> str:
    """Check LanceDB schema health."""
    if not db_path.exists():
        return "not_found"
    expected = {"id", "text", "file_path"}
    try:
        import lancedb

        db = lancedb.connect(str(db_path))
        tables = db.list_tables()
        if not tables:
            return "empty"
        table = db.open_table(tables[0])
        fields = {f.name for f in table.schema}
        if fields.issuperset(expected):
            return "ok"
        return "mismatch"
    except Exception:
        return "empty"


def _build_uninstall_bat(python_exe: str, zed_ext_dir: str) -> str:
    lines = [
        "@echo off",
        "chcp 65001 >nul",
        "echo =================================================",
        "echo  Uninstalling MSCodebase Intelligence...",
        "echo =================================================",
        "echo [1/3] Removing Zed IDE settings...",
        f'"{python_exe}" -c "',
        "import json, pathlib, os, re, sys",
        "if sys.platform == 'win32':",
        "    p = pathlib.Path(os.environ.get('APPDATA', '')) / 'Zed' / 'settings.json'",
        "    if not p.exists():",
        "        p = pathlib.Path(os.environ.get('USERPROFILE', pathlib.Path.home())) / '.config' / 'zed' / 'settings.json'",
        "else:",
        "    p = pathlib.Path.home() / '.config' / 'zed' / 'settings.json'",
        "if p.exists():",
        "    content = p.read_text(encoding='utf-8')",
        "    clean = re.sub(r'^\\s*//.*$', '', content, flags=re.MULTILINE)",
        "    clean = re.sub(r',\\s*}', '}', clean)",
        "    clean = re.sub(r',\\s*]', ']', clean)",
        "    d = json.loads(clean)",
        "    if 'context_servers' in d and 'mscodebase-intelligence' in d['context_servers']:",
        "        del d['context_servers']['mscodebase-intelligence']",
        "        if not d['context_servers']:",
        "            del d['context_servers']",
        "    if 'lsp' in d and 'mscodebase-lsp' in d['lsp']:",
        "        del d['lsp']['mscodebase-lsp']",
        "        if not d['lsp']:",
        "            del d['lsp']",
        "    if 'languages' in d:",
        "        for lang in list(d['languages'].keys()):",
        "            lang_cfg = d['languages'][lang]",
        "            if 'language_servers' in lang_cfg and 'mscodebase-lsp' in lang_cfg['language_servers']:",
        "                lang_cfg['language_servers'].remove('mscodebase-lsp')",
        "                if not lang_cfg['language_servers']:",
        "                    del lang_cfg['language_servers']",
        "            if not lang_cfg:",
        "                del d['languages'][lang]",
        "        if not d['languages']:",
        "            del d['languages']",
        "    if 'mscodebase' in d:",
        "        del d['mscodebase']",
        "    p.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding='utf-8')",
        '"',
        "echo [2/3] Removing extension files...",
        "timeout /t 2 >nul",
        f'rd /s /q "{zed_ext_dir}"',
        "echo Done! Restart Zed IDE.",
        "pause",
    ]
    return "\n".join(lines) + "\n"


def run_cmd(cmd: str, cwd: str = None, timeout: int = 120) -> bool:
    """Run command with real-time output."""
    try:
        subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            timeout=timeout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def run_pip_install(venv_python: Path, cwd: Path, lang: str) -> bool:
    """Install pip packages with progress indication."""
    # Upgrade pip
    info(f"{Color.DIM}Upgrading pip...{Color.RESET}")
    run_cmd(f'"{venv_python}" -m pip install --upgrade pip', timeout=60)

    # Install deps
    width = min(_term_width(), 74)
    label = _tr("install_deps", lang)
    print(
        f"  {'┌─'} {Color.BOLD}{label}{Color.RESET} {'─' * (width - 6 - len(label))}┐"
    )

    try:
        proc = subprocess.Popen(
            f'"{venv_python}" -m pip install -r requirements.txt',
            shell=True,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        last_line = ""
        for line in proc.stdout:
            line = line.strip()
            if line:
                last_line = line[:60]
                # Show last package being installed
                bar_w = width - 20
                pct = 50  # indeterminate during pip
                bar = f"{Color.YELLOW}{'█' * (bar_w // 2)}{Color.DIM}{'░' * (bar_w - bar_w // 2)}{Color.RESET}"
                sys.stdout.write(f"\033[2A\033[J")  # up 2, clear to end
                sys.stdout.write(
                    f"  │ {bar}  50%  {Color.DIM}{last_line}{' ' * 20}{Color.RESET}\n"
                )
                sys.stdout.write(f"  │\n")
                sys.stdout.flush()

        proc.wait()
        if proc.returncode == 0:
            sys.stdout.write(f"\033[2A\033[J")  # Clear progress lines
            ok(
                f"{_tr('deps_ok', lang)}  {Color.DIM}{len(open(cwd / 'requirements.txt').readlines())} packages{Color.RESET}"
            )
            print(f"  {'└' + '─' * (width - 2) + '┘'}")
            print()
            return True
        else:
            fail(_tr("deps_fail", lang))
            print(f"  {'└' + '─' * (width - 2) + '┘'}")
            print()
            return False
    except Exception as e:
        fail(f"{_tr('deps_fail', lang)}: {e}")
        print(f"  {'└' + '─' * (width - 2) + '┘'}")
        print()
        return False


# ─── Main install logic ────────────────────────────────────
def main():
    _enable_ansi()

    # ── Language ──────────────────────────────────────────
    lang = detect_language()
    width = min(_term_width(), 74)

    # ── Step 1: Zed IDE check ────────────────────────────
    title = _tr("check_zed", lang)
    zed_config_dir = get_zed_config_dir()
    try:
        zed_config_dir.mkdir(parents=True, exist_ok=True)
        lines = [
            ok(f"{_tr('zed_found', lang)}: {Color.DIM}{zed_config_dir}{Color.RESET}")
        ]
    except Exception as e:
        lines = [
            fail(f"{_tr('zed_not_found', lang)}"),
            info(f"  {Color.DIM}Error: {e}{Color.RESET}"),
        ]
    render_step_box(1, TOTAL_STEPS, title, lines, lang)

    # ── Step 2: LM Studio check ──────────────────────────
    title = _tr("check_lm", lang)
    lm_ok = check_lm_studio_available()
    lm_lines = []
    if lm_ok:
        models = check_lm_studio_models()
        model_str = ", ".join(models[:3]) if models else ""
        lm_lines.append(
            ok(
                f"{_tr('lm_online', lang)} {Color.GREEN}{LM_STUDIO_HOST}:{LM_STUDIO_PORT}{Color.RESET}"
            )
        )
        if model_str:
            lm_lines.append(info(f"{Color.DIM}Models: {model_str}{Color.RESET}"))
    else:
        lm_lines.append(warn(f"{_tr('lm_offline', lang)}"))
    render_step_box(2, TOTAL_STEPS, title, lm_lines, lang)

    # ── Step 3: Stop processes + copy files ──────────────
    title = _tr("stop_processes", lang)
    proc_lines = []
    _stop_extension_processes()
    ZED_EXT_DIR.mkdir(parents=True, exist_ok=True)

    cleaned = _clean_stale_files(PROJECT_ROOT, ZED_EXT_DIR)
    if cleaned > 0:
        proc_lines.append(
            info(f"Cleaned {Color.YELLOW}{cleaned}{Color.RESET} stale files")
        )
    else:
        proc_lines.append(info("No stale files found"))
    render_step_box(3, TOTAL_STEPS, title, proc_lines, lang)

    # ── Copy files ───────────────────────────────────────
    skip_items = {
        ".git",
        "__pycache__",
        "venv",
        ".venv",
        ".codebase_indices",
        ".codebase_models",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".zed",
        ".idea",
        ".vscode",
    }
    items = [item for item in PROJECT_ROOT.iterdir() if item.name not in skip_items]

    copy_lines = []
    copy_lines.append(info(f"{_tr('copy_files', lang)}..."))
    render_step_box(
        3,
        TOTAL_STEPS,
        f"{_tr('copy_files', lang)} ({len(items)} items)",
        copy_lines,
        lang,
    )

    for idx, item in enumerate(items):
        target = ZED_EXT_DIR / item.name
        try:
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(str(target))
                else:
                    target.unlink()
            if item.is_dir():
                shutil.copytree(str(item), str(target))
            else:
                shutil.copy2(str(item), str(target))
        except Exception as e:
            warn(f"Skip {item.name}: {e}")
        # Update progress
        pct = int((idx + 1) / len(items) * 100)
        if pct % 20 == 0 or idx == len(items) - 1:
            sys.stdout.write(f"\033[2A\033[J")
            copy_lines = [ok(f"{pct}% — {Color.DIM}{item.name}{Color.RESET}")]
            render_step_box(
                3,
                TOTAL_STEPS,
                f"{_tr('copy_files', lang)} ({len(items)} items)",
                copy_lines,
                lang,
            )

    copy_lines = [
        ok(f"{len(items)} items copied to {Color.DIM}{ZED_EXT_DIR}{Color.RESET}")
    ]
    render_step_box(
        3,
        TOTAL_STEPS,
        f"{_tr('copy_files', lang)} ({len(items)} items)",
        copy_lines,
        lang,
    )

    # ── Step 4: Create venv ──────────────────────────────
    title = _tr("create_venv", lang)
    venv_lines = []
    if not VENV_DIR.exists():
        try:
            subprocess.run(
                f'"{sys.executable}" -m venv "{VENV_DIR}"',
                shell=True,
                timeout=60,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            venv_lines.append(
                ok(f"{_tr('venv_created', lang)}: {Color.DIM}{VENV_DIR}{Color.RESET}")
            )
        except Exception as e:
            venv_lines.append(fail(f"Failed to create venv: {e}"))
            for l in venv_lines:
                print(l)
            print(f"  {'└' + '─' * (width - 2) + '┘'}")
            print()
            return
    else:
        venv_lines.append(
            ok(f"{_tr('venv_exists', lang)}: {Color.DIM}{VENV_DIR}{Color.RESET}")
        )
    render_step_box(4, TOTAL_STEPS, title, venv_lines, lang)

    # ── Step 5: Install deps ─────────────────────────────
    if not run_pip_install(PYTHON_EXE, ZED_EXT_DIR, lang):
        return

    # ── Step 6: Check LanceDB ────────────────────────────
    title = _tr("check_db", lang)
    db_path = PROJECT_ROOT / ".codebase_indices" / "lancedb_v2"
    db_status = validate_lancedb_schema(db_path)
    db_lines = []
    status_msgs = {
        "ok": ok("LanceDB schema valid"),
        "mismatch": warn("Schema differs — migration will run on startup"),
        "empty": info("Database empty — will populate during indexing"),
        "not_found": info("No database yet — will create on first run"),
    }
    db_lines.append(status_msgs.get(db_status, warn(f"Unknown status: {db_status}")))
    render_step_box(6, TOTAL_STEPS, title, db_lines, lang)

    # ── Step 7: Zed integration ──────────────────────────
    title = _tr("integrate", lang)
    mcp_command = f"{PYTHON_EXE} -u -m src.main"
    zed_lines = []
    if patch_zed_settings(
        command=mcp_command,
        mode="global",
        lsp_config=None,
        languages_config=None,
        install_path=str(ZED_EXT_DIR),
    ):
        zed_lines.append(ok(f"{_tr('mcp_ok', lang)}"))
        zed_lines.append(info(f"  {Color.DIM}MCP: {mcp_command}{Color.RESET}"))
    else:
        zed_lines.append(fail("Failed to configure Zed (MCP + LSP)"))
        for l in zed_lines:
            print(l)
        print(f"  {'└' + '─' * (width - 2) + '┘'}")
        print()
        return
    render_step_box(7, TOTAL_STEPS, title, zed_lines, lang)

    # ── Step 8: Skills + Locale ──────────────────────────
    title = _tr("install_skills", lang)
    skill_lines = []

    # Copy .agents
    src_agents = PROJECT_ROOT / ".agents"
    dst_agents = ZED_EXT_DIR / ".agents"
    if src_agents.exists():
        try:
            shutil.copytree(
                str(src_agents),
                str(dst_agents),
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            skill_lines.append(ok(f"{_tr('skills_ok', lang)}"))
        except Exception as e:
            skill_lines.append(warn(f"Skills copy failed: {e}"))
    else:
        skill_lines.append(info("No local skills — using global"))

    # Write locale to .env
    env_path = ZED_EXT_DIR / ".env"
    env_vars = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env_vars[k.strip()] = v.strip()
    env_vars["MSCODEBASE_LOCALE"] = lang
    if "LM_STUDIO_HOST" not in env_vars:
        env_vars["LM_STUDIO_HOST"] = LM_STUDIO_HOST
    if "LM_STUDIO_PORT" not in env_vars:
        env_vars["LM_STUDIO_PORT"] = str(LM_STUDIO_PORT)
    env_content = "\n".join(f"{k}={v}" for k, v in sorted(env_vars.items()))
    env_path.write_text(env_content, encoding="utf-8")

    lang_names = {"en": "English", "ru": "Русский", "zh": "中文"}
    skill_lines.append(
        info(
            f"Locale: {Color.GREEN}{lang_names.get(lang, 'English')}{Color.RESET} ({lang})"
        )
    )
    render_step_box(8, TOTAL_STEPS, title, skill_lines, lang)

    # ── Step 9: Uninstaller ──────────────────────────────
    title = _tr("gen_uninstall", lang)
    uninst_lines = []
    try:
        uninst_content = _build_uninstall_bat(str(PYTHON_EXE), str(ZED_EXT_DIR))
        UNINSTALLER.write_text(uninst_content, encoding="utf-8")
        uninst_lines.append(ok(f"uninstall.bat: {Color.DIM}{UNINSTALLER}{Color.RESET}"))
    except Exception as e:
        uninst_lines.append(warn(f"Uninstaller failed: {e}"))
    render_step_box(9, TOTAL_STEPS, title, uninst_lines, lang)

    # ── Final summary ────────────────────────────────────
    hr()
    print()
    if lm_ok:
        render_box(
            _tr("complete_success", lang),
            [
                ok(f"{_tr('mcp_ok', lang)}"),
                ok(f"{_tr('lm_online', lang)} {LM_STUDIO_HOST}:{LM_STUDIO_PORT}"),
                ok(f"{_tr('deps_ok', lang)}"),
                info(""),
                info(f"  {Color.BOLD}{_tr('next_steps', lang)}:{Color.RESET}"),
                info(f"  {Color.CYAN}1.{Color.RESET}  {_tr('restart_zed', lang)}"),
                info(f"  {Color.CYAN}2.{Color.RESET}  {_tr('open_project', lang)}"),
                info(f"  {Color.CYAN}3.{Color.RESET}  {_tr('start_coding', lang)}"),
            ],
            width=width,
            color=Color.GREEN,
        )
    else:
        render_box(
            _tr("complete_fallback", lang),
            [
                warn(f"{_tr('lm_offline', lang)}"),
                info(""),
                info(f"  {Color.BOLD}Next steps:{Color.RESET}"),
                info(f"  1. Start LM Studio on port {LM_STUDIO_PORT}"),
                info(f"  2. Load model: text-embedding-bge-m3"),
                info(f"  3. {_tr('restart_zed', lang)}"),
            ],
            width=width,
            color=Color.YELLOW,
        )
    print()
    info(f"   {Color.DIM}Extension: {ZED_EXT_DIR}{Color.RESET}")
    info(f"   {Color.DIM}Python:    {PYTHON_EXE}{Color.RESET}")
    print()


if __name__ == "__main__":
    main()
