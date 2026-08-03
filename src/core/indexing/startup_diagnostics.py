"""
Startup diagnostics — человекочитаемая диагностика индекса и PID-lock при старте.

Задача 3/5 «идеального кода» (владелец: «система должна говорить что происходит»):
вместо Rust-трейса (`lance-io-8.0.0\\src\\local.rs:133:40`) пользователь получает
1 человеческим текстом: ЧТО случилось и ЧТО ДЕЛАТЬ («Закройте второе окно Zed»).

Ключевое свойство: модуль STRICTLY READ-ONLY. Он никогда не захватывает lock,
не удаляет файлы, не пересоздаёт таблицы — только читает состояние. Любая
запись остаётся за LanceDBManager / intel_reset_index (семантика §5.13 / INC-6C62).

Состояния:
- PID-lock: free / self / held_alive / stale / corrupt
  (self = lock принадлежит ТЕКУЩЕМУ процессу — штатно, не ошибка)
- БД: missing / empty / healthy / corrupt
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("mscodebase_server.startup_diagnostics")

LOCK_FILENAME = ".write_lock"
DEFAULT_TABLE_NAME = "codebase_chunks"


@dataclass
class LockStatus:
    """Статус PID-lock-файла (read-only, без захвата)."""

    state: str  # free | self | held_alive | stale | corrupt
    holder_pid: Optional[int] = None
    holder_started: Optional[float] = None
    message: str = ""


@dataclass
class DbStatus:
    """Статус директории LanceDB и таблицы (read-only)."""

    state: str  # missing | empty | healthy | corrupt
    chunks: int = 0
    message: str = ""


@dataclass
class StartupReport:
    """Итоговый человекочитаемый отчёт о состоянии индекса при старте."""

    lock: LockStatus = field(default_factory=LockStatus)
    db: DbStatus = field(default_factory=DbStatus)
    issues: list = field(default_factory=list)

    def to_human(self) -> str:
        """Собирает отчёт в 1 человеческий текст с действиями."""
        lines = ["📋 **Диагностика индекса при старте**", "━" * 32]
        lines.append(f"• PID-lock: {self.lock.message or self.lock.state}")
        lines.append(f"• База данных: {self.db.message or self.db.state}")
        if self.issues:
            lines.append("━" * 32)
            lines.append("⚠️ **Что делать:**")
            for i, issue in enumerate(self.issues, 1):
                lines.append(f"  {i}. {issue}")
        return "\n".join(lines)


def _is_pid_alive(pid: int) -> bool:
    """Проверяет живость PID (переиспользует логику DatabaseLock)."""
    from src.core.indexing.database_lock import DatabaseLock

    return DatabaseLock._is_pid_alive(pid)


def inspect_pid_lock(lock_path: Path, current_pid: Optional[int] = None) -> LockStatus:
    """Читает lock-файл БЕЗ захвата/изменения.

    Args:
        lock_path: путь к `.write_lock` (обычно `db_path / ".write_lock"`).
        current_pid: PID текущего процесса (os.getpid()). Если lock-файл
            принадлежит этому PID — состояние `self` (собственный lock
            сервера, штатно), а НЕ `held_alive` (чужой экземпляр).

    Returns:
        LockStatus: состояние lock-файла.
    """
    lock_path = Path(lock_path)
    if not lock_path.exists():
        return LockStatus(
            state="free",
            message="свободен (другой процесс не пишет в эту БД)",
        )
    try:
        with open(lock_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        holder_pid = data.get("pid")
        holder_started = data.get("started")
    except (json.JSONDecodeError, OSError) as e:
        return LockStatus(
            state="corrupt",
            message=f"повреждён ({e}). Будет пересоздан при первом обращении к БД.",
        )

    if holder_pid is None:
        return LockStatus(
            state="corrupt",
            holder_pid=holder_pid,
            holder_started=holder_started,
            message="не содержит PID. Будет пересоздан при первом обращении к БД.",
        )

    started_str = ""
    if holder_started:
        try:
            started_str = time.strftime("%H:%M:%S", time.localtime(holder_started))
        except (ValueError, OSError):
            started_str = "?"

    if current_pid is not None and holder_pid == current_pid:
        # Собственный lock текущего MCP-процесса (сервер держит lock всю
        # сессию). Это штатно — НЕ «второй экземпляр» (см. INC-6C62 / задача 3/5).
        return LockStatus(
            state="self",
            holder_pid=holder_pid,
            holder_started=holder_started,
            message=(
                f"занят текущим процессом (PID {holder_pid}, с {started_str}) — "
                f"штатно, это собственный lock сервера"
            ),
        )

    if _is_pid_alive(holder_pid):
        return LockStatus(
            state="held_alive",
            holder_pid=holder_pid,
            holder_started=holder_started,
            message=(
                f"занят процессом PID {holder_pid} (с {started_str}) — "
                f"другой экземпляр MCP активно пишет в эту БД"
            ),
        )
    return LockStatus(
        state="stale",
        holder_pid=holder_pid,
        holder_started=holder_started,
        message=(
            f"оставлен мёртвым процессом PID {holder_pid} (с {started_str}). "
            f"Будет пересоздан при первом обращении к БД."
        ),
    )


def inspect_db(db_path: Path, table_name: str = DEFAULT_TABLE_NAME) -> DbStatus:
    """Читает директорию БД и таблицу read-only (без изменений).

    Последовательность: директория → connect → open_table → count_rows.
    Любая ошибка LanceDB трактуется как corrupt (человеческий текст вместо
    Rust-трейса). Директорию НЕ создаёт.
    """
    db_path = Path(db_path)
    if not db_path.exists() or not db_path.is_dir():
        return DbStatus(
            state="missing",
            message=(
                f"директория {db_path.name} не существует — будет создана "
                f"при первой индексации"
            ),
        )

    try:
        import lancedb

        db = lancedb.connect(str(db_path))
        # Если на диске есть директория таблицы — она должна открыться;
        # если нет — это новый/пустой индекс (LanceDB open_table бросит
        # "table not found", что НЕ является повреждением).
        table_dir = db_path / f"{table_name}.lance"
        try:
            table = db.open_table(table_name)
        except Exception as _open_err:
            if table_dir.exists():
                raise
            return DbStatus(
                state="empty",
                message=(
                    f"таблица '{table_name}' не найдена — индекс пуст, "
                    f"запустится автоиндексация"
                ),
            )
        count = table.count_rows()
        if count == 0:
            return DbStatus(
                state="empty",
                message="таблица существует, но пуста — запустится автоиндексация",
            )
        return DbStatus(
            state="healthy",
            chunks=count,
            message=f"таблица '{table_name}' открыта, {count} чанков",
        )
    except Exception as e:  # noqa: BLE001 — LanceDB API кидает разные типы ошибок
        err_str = str(e)
        # Не показываем Rust-пути пользователю — только суть + действие
        logger.debug(f"inspect_db: LanceDB read failed: {err_str}")
        return DbStatus(
            state="corrupt",
            message=(
                "индекс повреждён или залочен другим процессом "
                "(ошибка LanceDB при чтении). Выполните intel_reset_index "
                "или удалите папку индекса при полностью закрытом Zed."
            ),
        )


def build_startup_report(
    db_path: Path,
    table_name: str = DEFAULT_TABLE_NAME,
    lock_path: Optional[Path] = None,
    current_pid: Optional[int] = None,
) -> StartupReport:
    """Собирает полный отчёт: lock + БД + человеческие действия.

    Args:
        db_path: путь к директории LanceDB (например `<data_root>/projects/<hash>/lancedb_v2`).
        table_name: имя таблицы (по умолчанию `codebase_chunks`).
        lock_path: путь к lock-файлу; по умолчанию `db_path / ".write_lock"`.
        current_pid: PID текущего процесса; lock этого PID не считается
            «другим экземпляром» (см. inspect_pid_lock).

    Returns:
        StartupReport с заполненными issue-списком (что делать).
    """
    db_path = Path(db_path)
    if lock_path is None:
        lock_path = db_path / LOCK_FILENAME

    lock = inspect_pid_lock(lock_path, current_pid=current_pid)
    db = inspect_db(db_path, table_name)

    report = StartupReport(lock=lock, db=db)

    # ─── Формируем действия (человеческие, с конкретным шагом) ───
    if lock.state == "held_alive":
        report.issues.append(
            f"Обнаружен второй экземпляр MCP (PID {lock.holder_pid}), "
            f"пишущий в эту БД. Закройте второе окно Zed (или дождитесь "
            f"завершения его реиндекса) и повторите операцию."
        )
    elif lock.state == "corrupt":
        report.issues.append(
            "Lock-файл повреждён — это безопасно: при первом обращении "
            "к БД он будет пересоздан автоматически."
        )

    if db.state == "corrupt":
        report.issues.append(
            "Индекс повреждён. Порядок действий: 1) закройте Zed полностью; "
            "2) удалите папку индекса вручную; 3) откройте Zed — автоиндексация "
            "создаст чистый индекс. Либо вызовите intel_reset_index."
        )
    elif db.state == "empty":
        report.issues.append(
            "Индекс пуст — автоиндексация запустится автоматически "
            "в течение минуты после старта."
        )
    elif db.state == "missing":
        report.issues.append(
            "Индекс ещё не создан — автоиндексация запустится автоматически "
            "в течение минуты после старта."
        )
    return report


def log_startup_report(report: StartupReport) -> None:
    """Логирует отчёт целиком (для стартового пути MCP)."""
    text = report.to_human()
    if report.issues:
        logger.warning("\n" + text)
    else:
        logger.info("\n" + text)
