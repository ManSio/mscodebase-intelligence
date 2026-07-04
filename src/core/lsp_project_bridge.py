"""
MSCodeBase LSP→MCP Project Bridge — временный файл для передачи корня проекта.

Архитектура:
  LSP получает project_root от Zed через LSP-протокол (root_uri).
  MCP не имеет доступа к root_uri, а current_dir не работает на Windows (баг #36019).
  Решение: LSP пишет project_root в temp-файл, MCP читает при старте.

Исправления:
  - Удалена изоляция по UUID процесса (так как у LSP и MCP разные UUID).
  - Привязка сессий жестко зафиксирована на общем Parent PID (Zed Workspace).
"""

import json
import logging
import os
import sys
import time
import hashlib
from pathlib import Path
from typing import Optional

logger = logging.getLogger("MSCodeBase.Bridge")

# ──────────────────────────────────────────────
# Константы
# ──────────────────────────────────────────────
_BRIDGE_DIR = Path.home() / ".mscodebase" / "bridge"
_MAX_WAIT_SEC = 10.0
_POLL_INTERVAL = 0.05  # 50ms базовый интервал
_STALE_AGE_SEC = 300   # 5 минут


def _ensure_bridge_dir() -> Path:
    """Создаёт директорию для bridge-файлов."""
    _BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    return _BRIDGE_DIR


def _get_parent_pid() -> Optional[int]:
    """
    Возвращает PID родительского процесса (дедушку).

    Схема: MCP/LSP → Zed workspace process → Zed main
    Нам нужен Zed workspace process — PID дедушки.

    На Windows psutil может выдать AccessDenied.
    Fallback: None, используем хеш argv как ключ.
    """
    try:
        import psutil
        current = psutil.Process()
        parent = current.parent()
        if parent is not None:
            grandparent = parent.parent()
            if grandparent is not None:
                return grandparent.pid
            return parent.pid
        return None
    except (ImportError, AttributeError):
        pass
    except Exception as e:
        logger.debug(f"psutil parent PID недоступен: {e}")
    return None


def _get_fallback_key() -> str:
    """
    Fallback-ключ, когда psutil недоступен или выдает AccessDenied.

    Базируется на аргументах командной строки процесса. Поскольку Zed запускает
    LSP и MCP серверы с предсказуемыми путями окружения, хеш их базовых путей
    позволит им найти общую точку соприкосновения.
    """
    hash_input = "".join(sys.argv).encode("utf-8")
    return hashlib.sha256(hash_input).hexdigest()[:16]


def _session_key() -> str:
    """Уникальный ключ сессии: parent PID или fallback-хеш."""
    pid = _get_parent_pid()
    if pid is not None and pid > 0:
        return str(pid)
    return _get_fallback_key()


def _bridge_path() -> Path:
    """Путь к temp-файлу для текущей сессии."""
    return _ensure_bridge_dir() / f"session_{_session_key()}.json"


def _stale_path() -> Path:
    """Путь к временному файлу (для атомарной записи)."""
    return _ensure_bridge_dir() / f".stale_{_session_key()}.tmp"


# ──────────────────────────────────────────────
# ПУБЛИЧНЫЙ API
# ──────────────────────────────────────────────


def write_active_project(project_root: Path) -> None:
    """
    Пишет корень проекта в temp-файл сессии.

    Атомарность: пишем во временный файл → os.replace() (операция ОС).
    Это исключает race condition: MCP либо видит целый файл, либо не видит.

    Вызывается LSP в on_initialize().
    """
    try:
        pid = _get_parent_pid()
        data = {
            "parent_pid": pid,
            "project_root": str(project_root.resolve()),
            "created_at": time.time(),
            "fallback_key": _get_fallback_key(),
        }
        target = _bridge_path()
        stale = _stale_path()

        # Пишем во временный файл
        with open(stale, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # Атомарное переименование (ОС гарантирует целостность файла)
        os.replace(stale, target)

        logger.info(
            f"[BRIDGE] project_root успешно сохранен: {data['project_root']} "
            f"(session_key={_session_key()}, pid={pid})"
        )
    except Exception as e:
        logger.warning(f"[BRIDGE] Ошибка записи project_root: {e}")


def read_active_project(max_wait: float = _MAX_WAIT_SEC) -> Optional[Path]:
    """
    Читает корень проекта из temp-файла сессии с использованием Polling.

    Защита:
      - Файл должен быть не старше _STALE_AGE_SEC.
      - Если файл занят ОС или перезаписывается, срабатывает обработка OSError.

    Вызывается MCP в _resolve_project_path().
    """
    target = _bridge_path()
    deadline = time.time() + max_wait
    first = True

    while time.time() < deadline:
        if not target.exists():
            if first:
                logger.debug(
                    f"[BRIDGE] Ожидание project_root от LSP... "
                    f"(key={_session_key()}, max_wait={max_wait}s)"
                )
                first = False
            time.sleep(_POLL_INTERVAL)
            continue

        try:
            with open(target, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Валидация возраста файла
            created_at = data.get("created_at", 0)
            age = time.time() - created_at

            # Если файл из прошлого застрял, игнорируем его
            if age > _STALE_AGE_SEC:
                logger.warning(
                    f"[BRIDGE] Обнаружен устаревший файл сессии (возраст {age:.0f}s > {_STALE_AGE_SEC}s), "
                    f"ожидаем актуальное обновление от LSP..."
                )
                time.sleep(_POLL_INTERVAL)
                continue

            project_root_str = data.get("project_root", "")
            if not project_root_str:
                time.sleep(_POLL_INTERVAL)
                continue

            project_root = Path(project_root_str).resolve()
            if not project_root.exists():
                logger.debug(f"[BRIDGE] Указанный project_root не существует на диске: {project_root}")
                time.sleep(_POLL_INTERVAL)
                continue

            logger.info(
                f"[BRIDGE] project_root успешно прочитан: {project_root} "
                f"(задержка старта = {time.time() - (deadline - max_wait):.2f}s)"
            )
            return project_root

        except (json.JSONDecodeError, KeyError, OSError) as e:
            # Предотвращает падение, если файл считывается во время модификации
            logger.debug(f"[BRIDGE] Временная ошибка чтения (повтор): {e}")
            time.sleep(_POLL_INTERVAL)
            continue

    # Выход по таймауту
    logger.warning(
        f"[BRIDGE] Не удалось получить project_root от LSP за {max_wait}с. "
        f"Ключ сессии: {_session_key()}"
    )
    return None


def cleanup_stale() -> None:
    """
    Очищает временные файлы и файлы сессий, которые старше чем _STALE_AGE_SEC.

    Вызывается автоматически при инициализации моста.
    """
    try:
        now = time.time()
        bridge_dir = _ensure_bridge_dir()
        for f in bridge_dir.iterdir():
            if f.suffix not in (".json", ".tmp"):
                continue
            try:
                age = now - f.stat().st_mtime
                if age > _STALE_AGE_SEC:
                    f.unlink(missing_ok=True)
                    logger.debug(f"[BRIDGE] Удален устаревший файл моста: {f.name}")
            except OSError:
                pass
    except Exception as e:
        logger.debug(f"[BRIDGE] Ошибка при очистке устаревших файлов сессий: {e}")


# ──────────────────────────────────────────────
# Интеграция с существующей _resolve_project_path
# ──────────────────────────────────────────────

def read_project_from_bridge(max_wait: float = 0.5) -> Optional[Path]:
    """
    High-level API для _resolve_project_path в server.py.

    Выполняет предварительную очистку директории и пытается дождаться
    актуального пути к корню разрабатываемого проекта.

    ВАЖНО (INC-6BCB): max_wait по умолчанию 0.5s (НЕ 10s), иначе
    create_mcp_server() зависает на старте и Zed убивает процесс по
    таймауту. LSP обычно стартует ДО MCP и записывает bridge почти
    сразу, поэтому 0.5s достаточно. Если нужен больший — вызывающий
    код может передать явно.
    """
    cleanup_stale()
    return read_active_project(max_wait=max_wait)
