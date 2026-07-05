"""
MSCodebase Intelligence — Централизованное логирование с привязкой к проекту и времени.

Функции:
  • Ротируемый файловый лог в .codebase_indices/logs/
  • Привязка записей к проекту (имя + хэш пути)
  • Лёгкий формат: [время] [УРОВЕНЬ] [проект] модуль: сообщение
  • Автоочистка логов старше 7 дней
  • Минимальный overhead — FileHandler с задержкой записи
"""

import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

_MAX_LOG_BYTES = 2 * 1024 * 1024  # 2 MB на файл
_MAX_LOG_FILES = 3  # 3 файла ротации
_LOG_RETENTION_DAYS = 7  # Удалять логи старше 7 дней

_initialized_projects: set = set()


def get_log_dir(project_path: Path) -> Path:
    """Возвращает единую центральную директорию логов.

    Все логи пишутся в один каталог при расширении (ext_root),
    а НЕ per-project — чтобы не засорять проекты.
    Если project_path указывает на ext_root — используем его.
    Если project_path — пользовательский проект, то всё равно
    пишем в ext_root (централизация).
    """
    # Всегда используем ext_root для центрального лога
    # Если project_path похож на ext_root (содержит 'extensions'), берём его
    # Иначе ищем ext_root через стандартный путь установки
    path_str = str(project_path.resolve()).lower()
    if "extensions" in path_str and "zed" in path_str:
        log_dir = project_path / ".codebase_indices" / "logs"
    else:
        # Централизованный лог в директории расширения
        if sys.platform == "win32":
            base = Path(os.environ.get("LOCALAPPDATA", ""))
        else:
            base = Path.home() / ".local" / "share"
        ext_root = base / "Zed" / "extensions" / "mscodebase-intelligence"
        log_dir = ext_root / ".codebase_indices" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def setup_project_logging(
    project_path: Path,
    level: str = "INFO",
    project_label: Optional[str] = None,
) -> logging.Logger:
    """Настраивает файловое логирование для конкретного проекта.

    Создаёт RotatingFileHandler в .codebase_indices/logs/<project>.log
    с привязкой каждой записи к проекту.

    Args:
        project_path: Корневая директория проекта
        level: Уровень логирования (DEBUG, INFO, WARNING, ERROR)
        project_label: Метка проекта (если None — имя директории)

    Returns:
        Корневой логгер проекта
    """
    if project_label is None:
        project_label = project_path.name

    # Защита от повторной инициализации
    project_key = str(project_path.resolve())
    if project_key in _initialized_projects:
        return logging.getLogger("mscodebase")

    _initialized_projects.add(project_key)

    log_dir = get_log_dir(project_path)
    log_file = log_dir / f"{project_label}.log"

    # Формат с привязкой к проекту
    formatter = logging.Formatter(
        fmt=f"%(asctime)s [%(levelname)s] [{project_label}] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # RotatingFileHandler — ротация по размеру
    handler = RotatingFileHandler(
        str(log_file),
        maxBytes=_MAX_LOG_BYTES,
        backupCount=_MAX_LOG_FILES,
        encoding="utf-8",
    )
    handler.setFormatter(formatter)

    # Уровень
    log_level = getattr(logging, level.upper(), logging.INFO)
    handler.setLevel(log_level)

    # Подключаем к корневому логгеру mscodebase
    root_logger = logging.getLogger("mscodebase")
    root_logger.setLevel(log_level)

    # Избегаем дублирования хендлеров
    if not any(
        isinstance(h, RotatingFileHandler) and h.baseFilename == handler.baseFilename
        for h in root_logger.handlers
    ):
        root_logger.addHandler(handler)

    # Также подключаем к mscodebase_server (MCP логгер)
    mcp_logger = logging.getLogger("mscodebase_server")
    mcp_logger.setLevel(log_level)
    if not any(
        isinstance(h, RotatingFileHandler) and h.baseFilename == handler.baseFilename
        for h in mcp_logger.handlers
    ):
        mcp_logger.addHandler(handler)

    # Очистка старых логов
    _cleanup_old_logs(log_dir)
    _cleanup_stale_project_logs()

    root_logger.info(f"📋 Логирование инициализировано: {log_file}")

    return root_logger


def _cleanup_old_logs(log_dir: Path) -> int:
    """Удаляет логи старше _LOG_RETENTION_DAYS. Возвращает число удалённых."""
    if not log_dir.exists():
        return 0

    cutoff = time.time() - (_LOG_RETENTION_DAYS * 86400)
    deleted = 0

    for log_file in log_dir.glob("*.log*"):
        try:
            if log_file.stat().st_mtime < cutoff:
                log_file.unlink()
                deleted += 1
        except Exception:
            pass

    return deleted


def _cleanup_stale_project_logs() -> int:
    """Удаляет stale per-project логи из пользовательских проектов.

    Раньше логи писались в .codebase_indices/logs/ внутри каждого проекта.
    Теперь они централизованы в ext_root. Старые файлы удаляем.
    """
    deleted = 0
    try:
        if sys.platform == "win32":
            base = Path(os.environ.get("LOCALAPPDATA", ""))
        else:
            base = Path.home() / ".local" / "share"
        ext_root = base / "Zed" / "extensions" / "mscodebase-intelligence"
        ext_log_dir = ext_root / ".codebase_indices" / "logs"

        # Ищем .codebase_indices/logs в пользовательских проектах
        # (рядом с ext_root или в common locations)
        for search_root in [Path.home() / "Project", Path("D:\\Project")]:
            if not search_root.exists():
                continue
            for proj_dir in search_root.iterdir():
                if not proj_dir.is_dir():
                    continue
                log_dir = proj_dir / ".codebase_indices" / "logs"
                if log_dir.exists() and log_dir != ext_log_dir:
                    for f in log_dir.glob("*.log*"):
                        try:
                            f.unlink()
                            deleted += 1
                        except Exception:
                            pass
                    # Удаляем пустую директорию
                    try:
                        if not any(log_dir.iterdir()):
                            log_dir.rmdir()
                    except Exception:
                        pass
        if deleted > 0:
            logging.getLogger("mscodebase").info(
                f"🧹 Удалено {deleted} stale per-project лог-файлов"
            )
    except Exception:
        pass
    return deleted


def get_recent_errors(project_path: Path, limit: int = 20) -> list[dict]:
    """Читает последние ошибки из лога проекта. Не грузит систему — читает только хвост файла.

    Args:
        project_path: Корневая директория проекта
        limit: Максимальное число ошибок

    Returns:
        Список словарей с полями: timestamp, level, module, message
    """
    log_dir = get_log_dir(project_path)
    log_file = log_dir / f"{project_path.name}.log"

    if not log_file.exists():
        return []

    errors = []

    try:
        # Читаем только последние 64KB — не грузим весь файл
        file_size = log_file.stat().st_size
        read_size = min(file_size, 64 * 1024)

        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            if file_size > read_size:
                f.seek(file_size - read_size)
                f.readline()  # Пропускаем неполную первую строку

            for line in f:
                line = line.strip()
                if not line:
                    continue

                # Ищем ERROR и WARNING строки
                if "[ERROR]" in line or "[WARNING]" in line:
                    errors.append(_parse_log_line(line))

        # Оставляем только последние `limit` ошибок
        return errors[-limit:]

    except Exception:
        return []


def get_log_summary(project_path: Path) -> str:
    """Возвращает краткую сводку логов для MCP-инструмента.

    Лёгковесная — читает только хвост лога, не парсит весь файл.
    """
    errors = get_recent_errors(project_path, limit=10)

    from src.utils.i18n import _

    if not errors:
        return _("📋 Логи чисты — ошибок и предупреждений не обнаружено.")

    lines = [_("📋 Последние {count} ошибок/предупреждений:\n", count=len(errors))]

    for err in errors:
        level_icon = "🔴" if err.get("level") == "ERROR" else "🟡"
        ts = err.get("timestamp", "?")
        module = err.get("module", "?")
        msg = err.get("message", "?")[:120]
        lines.append(f"  {level_icon} [{ts}] {module}: {msg}")

    return "\n".join(lines)


def _parse_log_line(line: str) -> dict:
    """Парсит строку лога в словарь. Формат: 2026-06-27 15:30:00 [ERROR] [project] module: msg"""
    result = {
        "timestamp": "",
        "level": "",
        "module": "",
        "message": line,
    }

    try:
        # 2026-06-27 15:30:00 [ERROR] [project] module: message
        parts = line.split(" ", 3)
        if len(parts) >= 2:
            result["timestamp"] = f"{parts[0]} {parts[1]}"

        # Извлекаем уровень
        if "[ERROR]" in line:
            result["level"] = "ERROR"
        elif "[WARNING]" in line:
            result["level"] = "WARNING"
        elif "[CRITICAL]" in line:
            result["level"] = "CRITICAL"

        # Извлекаем модуль и сообщение (после последней ']')
        bracket_end = line.rfind("]")
        if bracket_end > 0 and bracket_end < len(line) - 2:
            rest = line[bracket_end + 1 :].strip()
            if ": " in rest:
                module, message = rest.split(": ", 1)
                result["module"] = module
                result["message"] = message
            else:
                result["message"] = rest

    except Exception:
        pass

    return result
