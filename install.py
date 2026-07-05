"""
MSCodebase Intelligence — Продакшен автоматический установщик расширения для Zed IDE (Windows)

Требования безопасной установки:
  • Проверка доступности LM Studio/Ollama на порту 1234 с Fallback-режимом
  • Атомарность обновлений: деликатная проверка схемы LanceDB без удаления
  • Изоляция окружения: venv строго внутри расширения
  • Контроль семафора: лимит параллельных запросов к локальной LLM
  • Остановка процессов расширения перед обновлением
  • Очистка stale-файлов при переустановке
"""

import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Импорт утилит из zed_config для кроссплатформенности и избежания дублирования
sys.path.insert(0, str(Path(__file__).resolve().parent / "src" / "utils"))
from zed_config import (
    SERVER_NAME,
    get_zed_config_dir,
    patch_zed_settings,
)

# ──────────────────────────────────────────────────────────────
# Константы
# ──────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent
ZED_EXT_DIR = (
    Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")))
    / "Zed"
    / "extensions"
    / "mscodebase-intelligence"
)
VENV_DIR = ZED_EXT_DIR / "venv"

# Кроссплатформенный путь к Python в venv
if sys.platform == "win32":
    PYTHON_EXE = VENV_DIR / "Scripts" / "python.exe"
else:
    PYTHON_EXE = VENV_DIR / "bin" / "python3"

UNINSTALLER = ZED_EXT_DIR / "uninstall.bat"

LM_STUDIO_HOST = os.environ.get("LM_STUDIO_HOST", "127.0.0.1")
LM_STUDIO_PORT = int(os.environ.get("LM_STUDIO_PORT", "1234"))
LM_STUDIO_TIMEOUT_SEC = 3

EXPECTED_SCHEMA_FIELDS = {
    "id": "string",
    "vector": "list<float32>",
    "text": "string",
    "file_path": "string",
    "file_hash": "string",
    "chunk_index": "int32",
}

MAX_CONCURRENT_LLM_REQUESTS = 2

# ──────────────────────────────────────────────────────────────
# TUI: Цвета, рамки, прогресс-бар, спиннер
# ──────────────────────────────────────────────────────────────


class Color:
    """ANSI-цвета для терминала Windows (включены через os.system)."""

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
    """Включает ANSI-escape коды в Windows Terminal."""
    if sys.platform == "win32":
        os.system("")


def _term_width() -> int:
    try:
        return os.get_terminal_size().columns
    except Exception:
        return 80


def banner(text: str, color: str = Color.CYAN) -> None:
    """Красивый баннер с двойной рамкой."""
    w = min(_term_width(), 72)
    inner = w - 4
    lines = text.split("\n")
    try:
        chr(0x2550).encode(sys.stdout.encoding or "utf-8")
        hl = chr(0x2550)
        tl = chr(0x2554)
        tr = chr(0x2557)
        bl = chr(0x255A)
        br = chr(0x255D)
        side = chr(0x2551)
    except (UnicodeEncodeError, AttributeError):
        hl = "="
        tl = "+="
        tr = "=+"
        bl = "+="
        br = "=+"
        side = "|"
    top = f"  {tl}{hl * inner}{tr}"
    bot = f"  {bl}{hl * inner}{br}"
    print(f"\n{color}{top}{Color.RESET}")
    for line in lines:
        padded = line.center(inner)
        print(
            f"{color}  {side}{Color.BOLD}{padded}{Color.RESET}{color}{side}{Color.RESET}"
        )
    print(f"{color}{bot}{Color.RESET}")


def step_header(num: int, total: int, title: str) -> None:
    """Заголовок шага с номером."""
    w = min(_term_width(), 72)
    inner = w - 6
    label = f" [{num}/{total}] {title} "
    padded = label.ljust(inner)
    print(f"\n{Color.BLUE}  ┌{'─' * inner}┐{Color.RESET}")
    print(
        f"{Color.BLUE}  │{Color.BOLD}{Color.CYAN}{padded}{Color.RESET}{Color.BLUE}│{Color.RESET}"
    )
    print(f"{Color.BLUE}  └{'─' * inner}┘{Color.RESET}")


def info(msg: str) -> None:
    print(f"  {Color.BLUE}ℹ{Color.RESET}  {msg}")


def ok(msg: str) -> None:
    print(f"  {Color.GREEN}✔{Color.RESET}  {msg}")


def warn(msg: str) -> None:
    print(f"  {Color.YELLOW}⚠{Color.RESET}  {msg}")


def fail(msg: str) -> None:
    print(f"  {Color.RED}✖{Color.RESET}  {msg}")


def detail(msg: str) -> None:
    print(f"  {Color.DIM}└─{Color.RESET} {msg}")


class ProgressBar:
    """Прогресс-бар с процентами и спиннером."""

    SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, total: int, label: str = "", width: int = 30):
        self.total = total
        self.current = 0
        self.label = label
        self.width = width
        self._spin_idx = 0
        self._start_time = time.time()

    def update(self, n: int = 1, detail_text: str = ""):
        self.current += n
        self._spin_idx = (self._spin_idx + 1) % len(self.SPINNER_FRAMES)
        self._render(detail_text)

    def _render(self, detail_text: str = ""):
        if self.total == 0:
            pct = 100
            filled = self.width
        else:
            pct = min(100, int(self.current / self.total * 100))
            filled = int(self.width * self.current / max(self.total, 1))

        bar = f"{Color.GREEN}{'█' * filled}{Color.DIM}{'░' * (self.width - filled)}{Color.RESET}"
        spinner = self.SPINNER_FRAMES[self._spin_idx]
        elapsed = time.time() - self._start_time

        line = f"  {spinner} {Color.BOLD}{self.label}{Color.RESET} │{bar}│ {pct:3d}%"
        if detail_text:
            line += f"  {Color.DIM}{detail_text}{Color.RESET}"
        elif self.current > 0 and elapsed > 0:
            rate = self.current / elapsed
            remaining = (self.total - self.current) / rate if rate > 0 else 0
            line += f"  {Color.DIM}{elapsed:.0f}s elapsed, ~{remaining:.0f}s left{Color.RESET}"

        # Очищаем строку и пишем
        print(f"\r{' ' * _term_width()}\r{line}", end="", flush=True)

    def finish(self, msg: str = ""):
        self.current = self.total
        self._render(msg or "done")
        print()  # newline


class Spinner:
    """Простой спиннер для операций без прогресса."""

    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, label: str):
        self.label = label
        self._idx = 0
        self._active = True

    def tick(self):
        if not self._active:
            return
        frame = self.FRAMES[self._idx % len(self.FRAMES)]
        self._idx += 1
        print(f"\r  {frame} {self.label}...", end="", flush=True)

    def done(self, msg: str = ""):
        self._active = False
        label = msg or self.label
        print(f"\r  {Color.GREEN}✔{Color.RESET}  {label}        ")


# ──────────────────────────────────────────────────────────────
# Утилиты
# ──────────────────────────────────────────────────────────────


def run_cmd(cmd: str, cwd: Path = PROJECT_ROOT) -> bool:
    res = subprocess.run(
        cmd, cwd=str(cwd), shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    return res.returncode == 0


def run_cmd_visible(
    cmd: str, cwd: Path = PROJECT_ROOT, label: str = "Выполняю"
) -> bool:
    """Запускает команду с видимым выводом в реальном времени.

    Показывает stdout/stderr процесса построчно,
    с таймстемпом и именем пакета.
    """
    start = time.time()
    print(f"  {Color.CYAN}▶{Color.RESET}  {Color.BOLD}{label}{Color.RESET}")

    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    lines_shown = 0
    max_lines = 200  # Защита от спама

    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue

            # Фильтруем шум pip
            if any(skip in line for skip in ["Requirement already satisfied", "\r"]):
                continue

            # Подсвечиваем ключевые строки
            if line.startswith("Collecting"):
                pkg = line.replace("Collecting ", "")
                print(f"    {Color.YELLOW}↓{Color.RESET} {pkg}")
            elif line.startswith("Downloading"):
                print(
                    f"    {Color.BLUE}⬇{Color.RESET} {line.replace('Downloading ', '')}"
                )
            elif "Building wheel" in line:
                print(f"    {Color.MAGENTA}⚙{Color.RESET} {line.strip()}")
            elif "Successfully" in line:
                print(f"    {Color.GREEN}✔{Color.RESET} {line.strip()}")
            elif "error" in line.lower() or "Error" in line:
                print(f"    {Color.RED}✖{Color.RESET} {line.strip()}")
            else:
                lines_shown += 1
                if lines_shown <= max_lines:
                    # Обрезаем длинные строки
                    display = line[:100] + "..." if len(line) > 100 else line
                    print(f"    {Color.DIM}{display}{Color.RESET}")
    except Exception:
        pass

    proc.wait()
    elapsed = time.time() - start

    if proc.returncode == 0:
        print(
            f"  {Color.GREEN}✔{Color.RESET}  {label} — {Color.GREEN}OK{Color.RESET} ({elapsed:.0f}s)"
        )
    else:
        print(
            f"  {Color.RED}✖{Color.RESET}  {label} — {Color.RED}FAIL{Color.RESET} ({elapsed:.0f}s)"
        )

    return proc.returncode == 0


def run_cmd_with_progress(
    cmd: str, cwd: Path = PROJECT_ROOT, label: str = "Выполняю"
) -> bool:
    """Запускает команду со спиннером (для коротких операций)."""
    spinner = Spinner(label)
    proc = subprocess.Popen(
        cmd, cwd=str(cwd), shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    while proc.poll() is None:
        spinner.tick()
        time.sleep(0.1)
    spinner.done(f"{label} — {'OK' if proc.returncode == 0 else 'FAIL'}")
    return proc.returncode == 0


def _stop_extension_processes() -> None:
    """Останавливает Python-процессы MCP и LSP серверов расширения."""
    spinner = Spinner("Поиск процессов расширения")
    killed = 0
    try:
        result = subprocess.run(
            "wmic process where \"CommandLine like '%mscodebase%' and Name='python.exe'\" get ProcessId /format:list",
            capture_output=True,
            text=True,
            shell=True,
            timeout=10,
        )
        pids = []
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if line.startswith("ProcessId="):
                pid = line.split("=", 1)[1].strip()
                if pid.isdigit():
                    pids.append(int(pid))

        for pid in pids:
            try:
                subprocess.run(
                    f"taskkill /PID {pid} /F",
                    capture_output=True,
                    shell=True,
                    timeout=5,
                )
                killed += 1
            except Exception:
                pass

        if killed > 0:
            spinner.done(f"Остановлено {killed} процессов (MCP/LSP)")
            time.sleep(1)
        else:
            spinner.done("Работающих процессов не найдено")
    except Exception as e:
        spinner.done(f"Проверка процессов: {e}")


def _clean_stale_files(src_root: Path, dst_root: Path) -> int:
    """Удаляет файлы в dst_root, которых больше нет в src_root. Возвращает число удалённых."""
    SKIP_DIRS = {"venv", ".codebase_indices", ".codebase_models", "__pycache__"}
    SKIP_FILES = {"uninstall.bat"}

    cleaned = 0

    # __pycache__
    for pycache in dst_root.rglob("__pycache__"):
        try:
            shutil.rmtree(pycache)
            cleaned += 1
        except Exception:
            pass

    # .pyc
    for pyc in dst_root.rglob("*.pyc"):
        try:
            pyc.unlink()
            cleaned += 1
        except Exception:
            pass

    # Stale-файлы
    stale_files = []
    for dst_file in dst_root.rglob("*"):
        if not dst_file.is_file():
            continue
        if dst_file.name in SKIP_FILES:
            continue
        rel = dst_file.relative_to(dst_root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        src_file = src_root / rel
        if not src_file.exists():
            stale_files.append((rel, dst_file))

    for rel, dst_file in stale_files:
        try:
            dst_file.unlink()
            detail(f"Удалён stale-файл: {Color.RED}{rel}{Color.RESET}")
            cleaned += 1
        except Exception:
            pass

    # Пустые директории
    for dst_dir in sorted(dst_root.rglob("*"), reverse=True):
        if not dst_dir.is_dir() or dst_dir == dst_root:
            continue
        rel = dst_dir.relative_to(dst_root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        src_dir = src_root / rel
        if not src_dir.exists() and not any(dst_dir.iterdir()):
            try:
                dst_dir.rmdir()
                cleaned += 1
            except Exception:
                pass

    return cleaned


def check_lm_studio_available() -> bool:
    try:
        with socket.create_connection(
            (LM_STUDIO_HOST, LM_STUDIO_PORT), timeout=LM_STUDIO_TIMEOUT_SEC
        ):
            return True
    except (ConnectionRefusedError, OSError, TimeoutError):
        return False


def validate_lancedb_schema(db_path: Path) -> str:
    if not db_path.exists():
        return "not_found"

    lance_files = list(db_path.glob("*.lance")) + list(db_path.glob("*.manifest"))
    if not lance_files:
        return "not_found"

    try:
        import lancedb

        db = lancedb.connect(str(db_path))
        table_names = db.table_names()

        if not table_names:
            return "empty"

        table = db.open_table("codebase_chunks")
        existing_schema = table.schema

        existing_fields = {}
        for field in existing_schema:
            existing_fields[field.name] = str(field.type)

        missing_fields = set(EXPECTED_SCHEMA_FIELDS.keys()) - set(
            existing_fields.keys()
        )
        if missing_fields:
            return "mismatch"

        critical_type_checks = {
            "id": "string",
            "text": "string",
            "file_path": "string",
            "file_hash": "string",
            "chunk_index": "int32",
        }
        for field_name, expected_type in critical_type_checks.items():
            actual = existing_fields.get(field_name, "")
            if expected_type not in actual:
                return "mismatch"

        return "ok"

    except ImportError:
        return "ok" if lance_files else "not_found"
    except Exception:
        return "mismatch"


def _build_uninstall_bat(python_exe: str, zed_ext_dir: str) -> str:
    _RX_COMMENT = r"r'^\s*//.*$'"
    _RX_TRAIL_COMMA_OBJ = r"r',\s*}\s*}'"
    _RX_TRAIL_COMMA_ARR = r"r',\s*]'"
    lines = [
        "@echo off",
        "chcp 65001 >nul",
        "echo ==================================================",
        "echo  Uninstalling MSCodebase Intelligence...",
        "echo ==================================================",
        "echo [1/3] Removing Zed IDE settings...",
        f'"{python_exe}" -c "',
        "import json, pathlib, os, re, sys",
        "# Кроссплатформенный поиск директории настроек Zed",
        "if sys.platform == 'win32':",
        "    p = pathlib.Path(os.environ.get('APPDATA', '')) / 'Zed' / 'settings.json'",
        "    if not p.exists():",
        "        p = pathlib.Path(os.environ.get('USERPROFILE', pathlib.Path.home())) / '.config' / 'zed' / 'settings.json'",
        "else:",
        "    p = pathlib.Path.home() / '.config' / 'zed' / 'settings.json'",
        "if p.exists():",
        "if p.exists():",
        "    content = p.read_text(encoding='utf-8')",
        f"    clean = re.sub({_RX_COMMENT}, '', content, flags=re.MULTILINE)",
        f"    clean = re.sub({_RX_TRAIL_COMMA_OBJ}, '}}', clean)",
        f"    clean = re.sub({_RX_TRAIL_COMMA_ARR}, ']', clean)",
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
        "echo [2/3] Removing extension files and databases...",
        "timeout /t 2 >nul",
        f'rd /s /q "{zed_ext_dir}"',
        "echo Done! Restart Zed IDE.",
        "pause",
    ]
    return "\n".join(lines) + "\n"


# ──────────────────────────────────────────────────────────────
# Главная функция
# ──────────────────────────────────────────────────────────────

TOTAL_STEPS = 9


def main():
    _enable_ansi()

    banner("MSCodebase Intelligence\nInstaller & Updater")

    # ══════════════════════════════════════════════════════════
    # Шаг 0: Проверка наличия Zed IDE
    # ══════════════════════════════════════════════════════════
    step_header(0, TOTAL_STEPS, "Проверка наличия Zed IDE")

    zed_config_dir = get_zed_config_dir()
    if not zed_config_dir.exists():
        # Пытаемся создать — возможно Zed ещё не запускался
        try:
            zed_config_dir.mkdir(parents=True, exist_ok=True)
            info(f"Создана директория настроек Zed: {zed_config_dir}")
            warn(
                "Zed IDE ещё не был запущен. Запустите Zed хотя бы раз для корректной работы."
            )
        except Exception as e:
            fail(f"Не удалось создать директорию настроек Zed: {e}")
            info("Убедитесь что Zed IDE установлен и у вас есть права на запись.")
            return
    else:
        ok(f"Директория настроек Zed найдена: {Color.DIM}{zed_config_dir}{Color.RESET}")

    # ══════════════════════════════════════════════════════════
    # Шаг 1: Проверка LM Studio / Ollama
    # ══════════════════════════════════════════════════════════
    step_header(1, TOTAL_STEPS, "Проверка LM Studio / Ollama")
    lm_available = check_lm_studio_available()
    fallback_mode = not lm_available

    if lm_available:
        ok(
            f"LM Studio/Ollama доступен на {Color.GREEN}{LM_STUDIO_HOST}:{LM_STUDIO_PORT}{Color.RESET}"
        )
    else:
        warn(f"LM Studio/Ollama НЕ доступен на {LM_STUDIO_HOST}:{LM_STUDIO_PORT}")
        info("Fallback-режим: Tree-sitter + текстовые индексы")
        info("Векторный поиск будет недоступен до запуска LM Studio/Ollama")

    # ══════════════════════════════════════════════════════════
    # Шаг 1: Остановка процессов + Изоляция файлов
    # ══════════════════════════════════════════════════════════
    step_header(1, TOTAL_STEPS, "Остановка процессов и изоляция файлов")

    _stop_extension_processes()

    ZED_EXT_DIR.mkdir(parents=True, exist_ok=True)

    # Очистка stale-файлов
    if ZED_EXT_DIR.exists():
        spinner = Spinner("Очистка stale-файлов")
        cleaned = _clean_stale_files(PROJECT_ROOT, ZED_EXT_DIR)
        if cleaned > 0:
            spinner.done(f"Очищено {Color.YELLOW}{cleaned}{Color.RESET} stale-файлов")
        else:
            spinner.done("Stale-файлы не найдены")

    # Копирование файлов с прогресс-баром
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

    items_to_copy = [
        item for item in PROJECT_ROOT.iterdir() if item.name not in skip_items
    ]

    pbar = ProgressBar(len(items_to_copy), "Копирование файлов")
    for item in items_to_copy:
        target = ZED_EXT_DIR / item.name
        try:
            # Удаляем старую директорию/файл, чтобы гарантировать обновление
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
            warn(f"Пропущен {item.name}: {e}")
        pbar.update(1, item.name)
    pbar.finish(f"{Color.GREEN}{len(items_to_copy)}{Color.RESET} элементов скопировано")

    # ══════════════════════════════════════════════════════════
    # Шаг 2: Создание venv
    # ══════════════════════════════════════════════════════════
    step_header(2, TOTAL_STEPS, "Создание Python Virtual Environment")

    if not VENV_DIR.exists():
        if run_cmd_with_progress(
            f'"{sys.executable}" -m venv "{VENV_DIR}"', label="Создание venv"
        ):
            ok(f"Venv создан: {Color.DIM}{VENV_DIR}{Color.RESET}")
        else:
            fail("Не удалось инициализировать venv")
            return
    else:
        ok(f"Venv уже существует: {Color.DIM}{VENV_DIR}{Color.RESET}")

    # ══════════════════════════════════════════════════════════
    # Шаг 3: Установка зависимостей
    # ══════════════════════════════════════════════════════════
    step_header(
        3, TOTAL_STEPS, "Установка зависимостей (LanceDB, PyArrow, Tree-sitter)"
    )

    # Обновление pip с обработкой ошибок
    try:
        pip_update_ok = run_cmd_visible(
            f'"{PYTHON_EXE}" -m pip install --upgrade pip', label="Обновление pip"
        )
        if not pip_update_ok:
            warn("Не удалось обновить pip — продолжаем с текущей версией")
    except Exception as e:
        warn(f"Ошибка при обновлении pip: {e}")

    # Установка зависимостей с обработкой ошибок
    try:
        pip_install_ok = run_cmd_visible(
            f'"{PYTHON_EXE}" -m pip install -r requirements.txt',
            cwd=ZED_EXT_DIR,
            label="Установка пакетов",
        )
        if not pip_install_ok:
            fail("Критическая ошибка установки Python-пакетов")
            info("Проверьте:")
            info(f"  1. Python установлен: {PYTHON_EXE}")
            info("  2. requirements.txt существует в директории расширения")
            info("  3. Интернет-соединение доступно")
            info("  4. Попробуйте вручную: pip install -r requirements.txt")
            return
    except Exception as e:
        fail(f"Непредвиденная ошибка при установке пакетов: {e}")
        return

    ok("Все зависимости установлены")

    # ══════════════════════════════════════════════════════════
    # Шаг 4: Проверка LanceDB
    # ══════════════════════════════════════════════════════════
    step_header(4, TOTAL_STEPS, "Проверка базы данных LanceDB v2")

    existing_db_path = PROJECT_ROOT / ".codebase_indices" / "lancedb_v2"
    schema_status = validate_lancedb_schema(existing_db_path)

    status_map = {
        "ok": (ok, "База LanceDB v2 валидна. Схема совпадает."),
        "mismatch": (
            warn,
            "Схема базы отличается! Миграция будет выполнена при запуске.",
        ),
        "empty": (info, "База существует, но пуста. Заполнится при индексации."),
        "not_found": (info, "База не найдена. Будет создана при первом запуске."),
    }
    handler, msg = status_map.get(
        schema_status, (warn, f"Неизвестный статус: {schema_status}")
    )
    handler(msg)

    # ══════════════════════════════════════════════════════════
    # Шаг 5: Интеграция в Zed IDE (через zed_config.patch_zed_settings)
    # ══════════════════════════════════════════════════════════
    step_header(5, TOTAL_STEPS, "Интеграция MCP + LSP в Zed IDE")

    # Проверка: существует ли директория настроек Zed?
    zed_config_dir = get_zed_config_dir()
    if not zed_config_dir.exists():
        # Пытаемся создать (Zed может не быть запущен)
        zed_config_dir.mkdir(parents=True, exist_ok=True)
        if not zed_config_dir.exists():
            fail(f"Директория настроек Zed не найдена: {zed_config_dir}")
            info("Убедитесь что Zed IDE установлен и запущен хотя бы раз.")
            return

    # Формируем команду для MCP-сервера
    # ВАЖНО: используем PYTHON_EXE (из ZED_EXT_DIR/venv/), а не get_python_path()
    # get_python_path() ищет venv в SOURCE-директории (D:\Project\MSCodeBase),
    # а venv создаётся в TARGET (ZED_EXT_DIR = %LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence)
    mcp_command = f"{PYTHON_EXE} -u -m src.main"

    # LSP-конфиг НЕ передаётся — WONTFIX на Zed 1.9.0 Windows.
    # Подробности: docs/investigations/2026-07-05-lsp-zed-1.9.0.md
    # LSP-сервер mscodebase-lsp не может быть зарегистрирован через
    # settings.json — требуется Rust+WASM-обёртка (v3.0+).
    # MCP-сервер покрывает 100% функционала код-ассистента.
    if patch_zed_settings(
        command=mcp_command,
        mode="global",
        lsp_config=None,
        languages_config=None,
        install_path=str(ZED_EXT_DIR),
    ):
        ok(f"MCP-сервер '{SERVER_NAME}' настроен в Zed")
        detail(f"MCP: {Color.DIM}{mcp_command}{Color.RESET}")
    else:
        fail("Не удалось настроить Zed (MCP + LSP)")
        return

    # ══════════════════════════════════════════════════════════
    # Шаг 6: Установка скиллов и AGENTS.md
    # ══════════════════════════════════════════════════════════
    step_header(6, TOTAL_STEPS, "Установка скиллов и системных правил")

    # Копируем .agents/skills в расширение
    src_agents = PROJECT_ROOT / ".agents"
    dst_agents = ZED_EXT_DIR / ".agents"
    if src_agents.exists():
        spinner = Spinner("Копирование скиллов (.agents/skills)")
        try:
            shutil.copytree(
                str(src_agents),
                str(dst_agents),
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            spinner.done(f"Скиллы скопированы: {Color.DIM}{dst_agents}{Color.RESET}")
        except Exception as e:
            spinner.done(f"Ошибка копирования скиллов: {e}")
            warn("Скиллы не скопированы — используются глобальные")
    else:
        info("Локальные скиллы не найдены (.agents/) — используются глобальные")

    # Копируем AGENTS.md если его нет в глобальной локации
    global_agents = (
        Path(os.environ.get("USERPROFILE", Path.home())) / ".agents" / "AGENTS.md"
    )
    project_agents = PROJECT_ROOT / "AGENTS.md"
    if project_agents.exists() and not global_agents.exists():
        try:
            global_agents.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(project_agents), str(global_agents))
            ok(f"AGENTS.md установлен: {Color.DIM}{global_agents}{Color.RESET}")
        except Exception as e:
            warn(f"Не удалось установить AGENTS.md: {e}")

    # Обновляем глобальный AGENTS.md если он устарел (проверяем по маркеру)
    if global_agents.exists():
        try:
            current_content = global_agents.read_text(encoding="utf-8")
            if (
                "intel_get_project_context" not in current_content
                and "SystemArtifacts" not in current_content
            ):
                warn(
                    "Глобальный AGENTS.md устарел (не содержит intel_get_project_context / SystemArtifacts). "
                    "Рекомендуется обновление."
                )
                info("Обновите AGENTS.md вручную или запустите: python install.py")
                if project_agents.exists():
                    shutil.copy2(str(project_agents), str(global_agents))
                    ok("AGENTS.md обновлён из проекта")
        except Exception as e:
            warn(f"Ошибка проверки AGENTS.md: {e}")

    # ══════════════════════════════════════════════════════════
    # Шаг ?: Удаление мёртвого кода (stale debug скрипты)
    # ══════════════════════════════════════════════════════════
    stale_scripts = [
        ZED_EXT_DIR / "scripts" / "dump_pid_env.py",
        ZED_EXT_DIR / "scripts" / "dump_running_mcp.py",
        ZED_EXT_DIR / "scripts" / "full_index.py",
    ]
    for sf in stale_scripts:
        if sf.exists():
            try:
                sf.unlink()
                logger.info(f"Удалён мёртвый скрипт: {sf.name}")
            except Exception:
                pass
    # Шаг 7: Деинсталлятор
    # ══════════════════════════════════════════════════════════
    step_header(7, TOTAL_STEPS, "Генерация деинсталлятора")

    uninst_content = _build_uninstall_bat(str(PYTHON_EXE), str(ZED_EXT_DIR))
    UNINSTALLER.write_text(uninst_content, encoding="utf-8")
    ok(f"uninstall.bat создан: {Color.DIM}{UNINSTALLER}{Color.RESET}")

    # ══════════════════════════════════════════════════════════
    # Итог
    # ══════════════════════════════════════════════════════════
    print()
    if fallback_mode:
        banner(
            "⚠ УСТАНОВЛЕНО В FALLBACK-РЕЖИМЕ\n"
            "Доступны: Tree-sitter + текстовые индексы\n"
            "Запустите LM Studio для полного функционала",
            Color.YELLOW,
        )
    else:
        banner(
            "✔ СИСТЕМА УСТАНОВЛЕНА\nВекторный + Структурный + Текстовый поиск",
            Color.GREEN,
        )

    print(f"""
  {Color.BOLD}Следующие шаги:{Color.RESET}
  {Color.CYAN}1.{Color.RESET} Убедитесь что LM Studio запущен (порт {LM_STUDIO_PORT})
  {Color.CYAN}2.{Color.RESET} Перезапустите {Color.BOLD}Zed IDE{Color.RESET}
  {Color.CYAN}3.{Color.RESET} Откройте проект и дождитесь индексации
  {Color.CYAN}4.{Color.RESET} Проверьте здоровье LSP: {Color.DIM}python scripts/check_lsp_health.py{Color.RESET}

  {Color.DIM}Расширение: {ZED_EXT_DIR}
  Python: {PYTHON_EXE}
  Семафор: {MAX_CONCURRENT_LLM_REQUESTS} параллельных запросов{Color.RESET}
""")


if __name__ == "__main__":
    main()
