"""
MSCodeBase LSP→MCP Project Bridge — временный файл для передачи корня проекта.

Архитектура:
  LSP получает project_root от Zed через LSP-протокол (root_uri).
  MCP не имеет доступа к root_uri, а current_dir не работает на Windows (баг #36019).
  Решение: LSP пишет project_root в temp-файл, MCP читает при старте.

Edge Cases (аудит Gemini):
  1. Stale PID reuse — таймстамп + UUID сессии
  2. psutil AccessDenied на Windows — fallback на хеш argv
  3. Race condition чтения-записи — атомарный os.replace()
"""

import json
import logging
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger("MSCodeBase.Bridge")

# ──────────────────────────────────────────────
# Константы
# ──────────────────────────────────────────────
_BRIDGE_DIR = Path.home() / ".mscodebase" / "bridge"
_MAX_WAIT_SEC = 3.0
_POLL_INTERVAL = 0.05  # 50ms
_STALE_AGE_SEC = 300  # 5 минут

# UUID сессии — генерируется при импорте, живёт пока жив процесс
_SESSION_ID = uuid.uuid4().hex[:12]


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
    Fallback-ключ когда psutil недоступен.

    Используем хеш от argv[0] и CWD — они уникальны для каждого окна Zed,
    так как MCP/LSP запускаются с PYTHONPATH = ext_root.
    """
    argv_hash = abs(hash(tuple(sys.argv))) & 0xFFFF_FFFF
    cwd_hash = abs(hash(str(Path.cwd().resolve()))) & 0xFFFF_FFFF
    return f"{argv_hash:x}_{cwd_hash:x}"


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
    Пишет корень проекта в temp-файл.

    Атомарность: пишем во временный файл → os.replace() (операция ОС).
    Это исключает race condition: MCP либо видит целый файл, либо не видит.

    Вызывается LSP в on_initialize().
    """
    try:
        data = {
            "session_id": _SESSION_ID,
            "parent_pid": _get_parent_pid(),
            "project_root": str(project_root.resolve()),
            "created_at": time.time(),
            "fallback_key": _get_fallback_key(),
        }
        target = _bridge_path()
        stale = _stale_path()

        # Пишем во временный файл
        with open(stale, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

        # Атомарное переименование (ОС гарантирует целостность)
        os.replace(stale, target)

        logger.info(
            f"[BRIDGE] project_root записан: {data['project_root']} "
            f"(session={_SESSION_ID}, pid={data['parent_pid']})"
        )
    except Exception as e:
        logger.warning(f"[BRIDGE] Ошибка записи project_root: {e}")


def read_active_project(max_wait: float = _MAX_WAIT_SEC) -> Optional[Path]:
    """
    Читает корень проекта из temp-файла.

    Polling до max_wait секунд — MCP может стартовать быстрее LSP.
    Валидация:
      - Файл должен быть не старше _STALE_AGE_SEC
      - session_id должен совпадать с текущим (защита от stale PID)

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

            # Валидация возраста
            created_at = data.get("created_at", 0)
            age = time.time() - created_at
            if age > _STALE_AGE_SEC:
                logger.warning(
                    f"[BRIDGE] Stale файл (возраст {age:.0f}с > {_STALE_AGE_SEC}с), "
                    f"ждём новую запись..."
                )
                time.sleep(_POLL_INTERVAL)
                continue

            # Валидация session_id (защита от reuse PID)
            file_session = data.get("session_id", "")
            if file_session and file_session != _SESSION_ID:
                logger.debug(
                    f"[BRIDGE] session_id не совпадает "
                    f"(файл={file_session}, мы={_SESSION_ID}), ждём..."
                )
                time.sleep(_POLL_INTERVAL)
                continue

            project_root_str = data.get("project_root", "")
            if not project_root_str:
                logger.debug("[BRIDGE] project_root пустой, ждём...")
                time.sleep(_POLL_INTERVAL)
                continue

            project_root = Path(project_root_str).resolve()
            if not project_root.exists():
                logger.debug(f"[BRIDGE] project_root не существует: {project_root}")
                time.sleep(_POLL_INTERVAL)
                continue

            logger.info(
                f"[BRIDGE] project_root прочитан: {project_root} "
                f"(session={_SESSION_ID}, ожидание={time.time() - (deadline - max_wait):.1f}с)"
            )
            return project_root

        except (json.JSONDecodeError, KeyError, OSError) as e:
            logger.debug(f"[BRIDGE] Ошибка чтения (ждём): {e}")
            time.sleep(_POLL_INTERVAL)
            continue

    # Таймаут — LSP не ответил вовремя
    logger.warning(
        f"[BRIDGE] Таймаут ожидания project_root ({max_wait}с). "
        f"Ключ сессии: {_session_key()}"
    )
    return None


def cleanup_stale() -> None:
    """
    Чистит bridge-файлы старше _STALE_AGE_SEC.

    Вызывается при старте MCP/LSP.
    """
    try:
        now = time.time()
        for f in _ensure_bridge_dir().iterdir():
            if f.suffix != ".json":
                continue
            try:
                age = now - f.stat().st_mtime
                if age > _STALE_AGE_SEC:
                    f.unlink(missing_ok=True)
                    logger.debug(f"[BRIDGE] Удалён stale файл: {f.name}")
            except OSError:
                pass
    except Exception as e:
        logger.debug(f"[BRIDGE] cleanup_stale ошибка: {e}")


# ──────────────────────────────────────────────
# Интеграция с существующей _resolve_project_path
# ──────────────────────────────────────────────

def read_project_from_bridge() -> Optional[Path]:
    """
    High-level API для _resolve_project_path в server.py.

    Пытается прочитать project_root через bridge.
    Возвращает Path или None.
    """
    # Сначала чистим старые файлы
    cleanup_stale()

    # Пробуем прочитать (с polling до 3 секунд)
    return read_active_project()
