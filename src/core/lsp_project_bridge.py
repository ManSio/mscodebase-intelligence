"""
MSCodeBase LSP→MCP Project Bridge — временный файл для передачи корня проекта.

Архитектура:
  LSP получает project_root от Zed через LSP-протокол (root_uri / workspaceFolders).
  MCP не имеет доступа к root_uri, а current_dir не работает на Windows (баг #36019).
  Решение: LSP пишет project_root в temp-файл, MCP читает при старте.

Multi-root (INC-6BCB-v3): LSP 3.6+ присылает массив workspaceFolders.
  LSP пишет ВСЕ корни в JSON, MCP выбирает первый non-self-indexing.

Исправления:
  - Удалена изоляция по UUID процесса (так как у LSP и MCP разные UUID).
  - Привязка сессий жестко зафиксирована на общем Parent PID (Zed Workspace).
  - Self-indexing guard: is_zed_install_dir() пропускает Zed-установку.
"""

import json
import logging
import os
import sys
import time
import hashlib
from pathlib import Path
from typing import Optional, List, Iterable

logger = logging.getLogger("MSCodeBase.Bridge")

# ──────────────────────────────────────────────
# Константы
# ──────────────────────────────────────────────
_BRIDGE_DIR = Path.home() / ".mscodebase" / "bridge"
_MAX_WAIT_SEC = 10.0
_POLL_INTERVAL = 0.05  # 50ms базовый интервал


def get_bridge_dir() -> Path:
    """Публичный геттер для директории bridge-файлов."""
    return _BRIDGE_DIR
_STALE_AGE_SEC = 300   # 5 минут


def _ensure_bridge_dir() -> Path:
    """Создаёт директорию для bridge-файлов."""
    _BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    return _BRIDGE_DIR


# ──────────────────────────────────────────────
# Self-indexing detection (Zed install dir)
# ──────────────────────────────────────────────

# Маркеры директории установки Zed. Если в Path встречается любой из них —
# это self-indexing (индексируем саму установку), и нужно пропустить.
# ВАЖНО: маркеры НЕ должны требовать trailing path separator, иначе
# path типа `D:\AI\Zed` (корень Zed-установки) не будет опознан.
_ZED_INSTALL_MARKERS = (
    os.sep + "Zed" + os.sep,                # .../Zed/... (nested)
    os.sep + "Zed.exe",                      # .../Zed.exe
    os.sep + "Zed",                          # .../Zed (корень установки!)
    os.sep + "zed" + os.sep,                 # lowercase вариант (nested)
    os.sep + "zed",                          # lowercase корень
    os.sep + "Local" + os.sep + "Zed" + os.sep,  # %LOCALAPPDATA%/Zed/...
    os.sep + "Local" + os.sep + "Zed",            # %LOCALAPPDATA%/Zed (root)
    os.sep + "Local" + os.sep + "Programs" + os.sep + "Zed" + os.sep,
    os.sep + "Local" + os.sep + "Programs" + os.sep + "Zed",
)


def is_zed_install_dir(path: Path) -> bool:
    """Возвращает True если path выглядит как директория установки Zed.

    Используется для self-indexing guard: не индексируем саму установку
    (там .exe, .dll, конфиги, обновления — мусор для семантического поиска).

    Нормализует оба слэша ('/' и '\\') перед сравнением, так как в зависимости
    от ОС Python Path может вернуть mixed slashes.
    """
    if path is None:
        return False
    s = str(path.resolve()) if path.exists() else str(path)
    # Нормализуем все backslashes → forward slashes для кросс-платформенного
    # сравнения (на Windows Path может вернуть mixed slashes в .resolve()).
    s_normalized = s.replace("\\", "/").lower()
    for marker in _ZED_INSTALL_MARKERS:
        marker_normalized = marker.replace("\\", "/").lower()
        if marker_normalized in s_normalized:
            return True
    # Дополнительная эвристика: если в path есть Zed.exe рядом — это install.
    if path.is_dir():
        try:
            for candidate in ("Zed.exe", "zed.exe", "Zed", "zed"):
                if (path / candidate).exists():
                    return True
        except (OSError, PermissionError):
            pass
    return False


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


def write_active_project(
    project_root: Path,
    all_workspaces: Optional[Iterable[str]] = None,
) -> None:
    """
    Пишет корень проекта в temp-файл сессии.

    Атомарность: пишем во временный файл → os.replace() (операция ОС).
    Это исключает race condition: MCP либо видит целый файл, либо не видит.

    Multi-root (INC-6BCB-v3): all_workspaces содержит URI всех открытых
    воркспейсов (LSP 3.6+ workspaceFolders). MCP использует их для выбора
    правильного project_root (исключая self-indexing Zed install dir).

    Вызывается LSP в on_initialize().
    """
    try:
        pid = _get_parent_pid()
        data = {
            "parent_pid": pid,
            "project_root": str(project_root.resolve()),
            "all_workspaces": (
                list(all_workspaces) if all_workspaces else [str(project_root.resolve())]
            ),
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
            f"[BRIDGE] project_root сохранен: {data['project_root']} "
            f"({len(data['all_workspaces'])} workspace(s), "
            f"session_key={_session_key()}, pid={pid})"
        )
    except Exception as e:
        logger.warning(f"[BRIDGE] Ошибка записи project_root: {e}")


def read_active_project(max_wait: float = _MAX_WAIT_SEC) -> Optional[Path]:
    """
    Читает корень проекта из temp-файла сессии с использованием Polling.

    Multi-root (INC-6BCB-v3): если в JSON есть `all_workspaces`, выбираем
    первый workspace, который НЕ является Zed-установкой (self-indexing guard).
    Fallback на `project_root` если фильтрация не дала результата.

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

            # Multi-root: фильтруем self-indexing (Zed install dir)
            all_workspaces: List[str] = data.get("all_workspaces", [])
            if not all_workspaces:
                all_workspaces = [project_root_str]

            chosen = None
            for uri_or_path in all_workspaces:
                # URI могут быть "file:///D:/path" или просто "D:\path"
                p_str = uri_or_path
                if p_str.startswith("file://"):
                    from urllib.parse import urlparse
                    p_str = urlparse(p_str).path
                    if sys.platform == "win32" and p_str.startswith("/"):
                        p_str = p_str.lstrip("/")
                try:
                    p = Path(p_str)
                    if p.exists() and p.is_dir() and not is_zed_install_dir(p):
                        chosen = p
                        break
                except Exception:
                    continue

            if chosen is None:
                # Все workspaces = Zed install. Fallback на primary project_root.
                logger.warning(
                    f"[BRIDGE] Все {len(all_workspaces)} workspace(s) — Zed install. "
                    f"Использую primary project_root (возможно self-indexing)."
                )
                chosen = Path(project_root_str)
            else:
                logger.info(
                    f"[BRIDGE] Выбран workspace (multi-root, отфильтрован self-indexing): "
                    f"{chosen} (из {len(all_workspaces)} вариантов)"
                )

            if not chosen.exists():
                logger.debug(f"[BRIDGE] project_root не существует на диске: {chosen}")
                time.sleep(_POLL_INTERVAL)
                continue

            logger.info(
                f"[BRIDGE] project_root успешно прочитан: {chosen} "
                f"(задержка старта = {time.time() - (deadline - max_wait):.2f}s)"
            )
            return chosen

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
