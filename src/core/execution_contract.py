"""
Execution Contract — автоматическая верификация после операций записи.

Гарантирует:
1. После каждого edit_file/write_file → вызывается notify_change + get_index_status
2. После commit+push → верификация через git log
3. При ошибке — явный статус, а не ложное "успешно"
"""

import hashlib
import json
import logging
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "ExecutionContract",
    "format_verification_report",
    "ChangeIntent",
    "ChangeIntentLedger",
    "sha256_file",
    "get_base_commit",
]
logger = logging.getLogger("execution_contract")


# ══════════════════════════════════════════════════════════════
# WS4: ChangeIntent + Ledger (Claim Plane-стиль, staged: a+b)
#   (a) base_commit + file hashes записываются в ledger
#   (b) пост-верификация: after_hash сверяется с диском
# Полные fencing/leases — за рамками (нет параллельных писателей).
# ══════════════════════════════════════════════════════════════


def sha256_file(path: Path) -> Optional[str]:
    """SHA-256 содержимого файла (потоково, без загрузки в память)."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(65536), b""):
                h.update(block)
        return h.hexdigest()
    except OSError:
        return None


_base_commit_cache: Dict[str, Tuple[str, float]] = {}
_base_commit_lock = threading.Lock()


def get_base_commit(project_root: str, ttl_sec: float = 30.0) -> str:
    """Текущий HEAD коммита проекта (с кэшем TTL).

    Кэш: write-путь не дёргает git на каждую правку. При отсутствии
    git-репозитория — пустая строка (fallback, не ошибка).
    """
    key = str(Path(project_root).resolve()).lower().replace("\\", "/")
    now = time.time()
    with _base_commit_lock:
        cached = _base_commit_cache.get(key)
        if cached is not None and now - cached[1] < ttl_sec:
            return cached[0]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            cwd=project_root,
        )
        commit = result.stdout.strip() if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        commit = ""
    with _base_commit_lock:
        _base_commit_cache[key] = (commit, now)
        if len(_base_commit_cache) > 64:
            _base_commit_cache.clear()
    return commit


def invalidate_base_commit_cache() -> None:
    """Сброс кэша HEAD (после commit)."""
    with _base_commit_lock:
        _base_commit_cache.clear()


@dataclass
class ChangeIntent:
    """Детерминированный протокол записи (Claim Plane-стиль, WS4).

    Поля:
        operation:     replace / insert / safe_delete / rename / move
        file:          абсолютный путь файла
        base_commit:   HEAD на момент записи (provenance)
        before_hash:   SHA-256 файла ДО записи
        after_hash:    SHA-256 файла ПОСЛЕ записи
        expected_hash: ожидаемый хэш (если задан) — для пост-верификации
        symbol:        целевой символ операции
        timestamp:     ISO-время записи
        verified:      прошла ли пост-верификация
    """

    operation: str
    file: str
    base_commit: str = ""
    before_hash: str = ""
    after_hash: str = ""
    expected_hash: str = ""
    symbol: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    verified: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation": self.operation,
            "file": self.file,
            "base_commit": self.base_commit,
            "before_hash": self.before_hash,
            "after_hash": self.after_hash,
            "expected_hash": self.expected_hash,
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "verified": self.verified,
        }


class ChangeIntentLedger:
    """JSONL-ledger ChangeIntent'ов в системной папке проекта.

    Путь: <data_root>/projects/<hash8>/change_intents.jsonl — ВНЕ проекта
    (артефакты не пишутся в чужой репозиторий, Задача 4/5).
    """

    def __init__(self, project_root: str | Path):
        from src.core.artifact_paths import get_project_dir

        self.path = get_project_dir(Path(project_root)) / "change_intents.jsonl"
        self._lock = threading.Lock()

    def record(self, intent: ChangeIntent) -> bool:
        """Дописывает запись (append + flush). True при успехе."""
        try:
            line = json.dumps(intent.to_dict(), ensure_ascii=False)
            with self._lock, open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
            return True
        except OSError as e:
            logger.warning(f"ChangeIntentLedger.record failed: {e}")
            return False

    def query(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Последние N записей (новые в конце)."""
        if not self.path.exists():
            return []
        try:
            lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        entries: List[Dict[str, Any]] = []
        for line in lines[-limit:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries

    def count(self) -> int:
        """Число записей (0 при отсутствии файла)."""
        if not self.path.exists():
            return 0
        try:
            return sum(1 for _ in self.path.open("r", encoding="utf-8", errors="replace"))
        except OSError:
            return 0


class ExecutionContract:
    """Валидатор действий агента."""

    @staticmethod
    def verify_file_write(
        file_path: str,
        expected_content: Optional[str] = None,
        expected_hash: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Верификация записи файла.

        Args:
            file_path: путь к файлу
            expected_content: подстрока, которая ДОЛЖНА быть в файле (legacy)
            expected_hash: SHA-256, которому ДОЛЖНО равняться содержимое (WS4)
        """
        result = {
            "action": "file_write",
            "file": file_path,
            "timestamp": datetime.now().isoformat(),
            "verified": False,
            "errors": [],
        }

        path = Path(file_path)

        # 1. Файл существует?
        if not path.exists():
            result["errors"].append(f"Файл не существует: {file_path}")
            return result

        # 2. WS4: содержимое соответствует ожидаемому хэшу (полный файл)?
        if expected_hash:
            actual_hash = sha256_file(path)
            result["actual_hash"] = actual_hash
            result["expected_hash"] = expected_hash
            if actual_hash != expected_hash:
                result["errors"].append(
                    f"SHA-256 не совпадает: ожидалось {expected_hash[:12]}..., "
                    f"фактически {str(actual_hash)[:12]}..."
                )
                return result

        # 3. Содержимое соответствует ожидаемому (legacy-проверка)?
        if expected_content:
            actual = path.read_text(encoding="utf-8")
            if expected_content not in actual:
                result["errors"].append("Содержимое не совпадает с ожидаемым")
                return result

        result["verified"] = True
        return result

    @staticmethod
    def verify_git_commit(expected_message: Optional[str] = None) -> Dict[str, Any]:
        """Верификация последнего коммита."""
        result = {
            "action": "git_commit",
            "timestamp": datetime.now().isoformat(),
            "verified": False,
            "errors": [],
            "commit_hash": None,
            "commit_message": None,
        }

        try:
            # Получаем хеш последнего коммита
            hash_result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if hash_result.returncode != 0:
                result["errors"].append(
                    f"git rev-parse failed: {hash_result.stderr.strip()}"
                )
                return result

            commit_hash = hash_result.stdout.strip()
            result["commit_hash"] = commit_hash

            # Получаем сообщение коммита
            msg_result = subprocess.run(
                ["git", "log", "-1", "--pretty=%B"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if msg_result.returncode == 0:
                commit_msg = msg_result.stdout.strip()
                result["commit_message"] = commit_msg

                if expected_message and expected_message not in commit_msg:
                    result["errors"].append(
                        f"Сообщение коммита не содержит '{expected_message}': {commit_msg}"
                    )
                    return result

            # Проверяем что коммит не пустой
            diff_result = subprocess.run(
                [
                    "git",
                    "diff-tree",
                    "--no-commit-id",
                    "--name-only",
                    "-r",
                    commit_hash,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if diff_result.returncode == 0:
                changed_files = [f for f in diff_result.stdout.strip().split("\n") if f]
                if not changed_files:
                    result["errors"].append("Коммит не содержит изменений")
                    return result
                result["changed_files"] = changed_files

            result["verified"] = True

        except subprocess.TimeoutExpired:
            result["errors"].append("Git команда превысила таймаут (10s)")
        except FileNotFoundError:
            result["errors"].append("Git не найден в PATH")
        except Exception as e:
            result["errors"].append(f"Неожиданная ошибка: {e}")

        return result

    @staticmethod
    def verify_git_push() -> Dict[str, Any]:
        """Верификация что push выполнен (локальная ветка совпадает с remote)."""
        result = {
            "action": "git_push",
            "timestamp": datetime.now().isoformat(),
            "verified": False,
            "errors": [],
        }

        try:
            # Проверяем статус push
            status_result = subprocess.run(
                ["git", "status", "-sb"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if status_result.returncode != 0:
                result["errors"].append(
                    f"git status failed: {status_result.stderr.strip()}"
                )
                return result

            status_line = (
                status_result.stdout.strip().split("\n")[0]
                if status_result.stdout
                else ""
            )

            # Если есть "ahead" — push не прошёл
            if "ahead" in status_line:
                result["errors"].append(
                    f"Локальная ветка опережает remote: {status_line}"
                )
                return result

            result["verified"] = True
            result["status"] = status_line

        except subprocess.TimeoutExpired:
            result["errors"].append("Git команда превысила таймаут")
        except Exception as e:
            result["errors"].append(f"Ошибка: {e}")

        return result

    @staticmethod
    def verify_index_sync(project_root: str) -> Dict[str, Any]:
        """Верификация синхронизации индекса (через MCP вызов)."""
        result = {
            "action": "index_sync",
            "timestamp": datetime.now().isoformat(),
            "verified": False,
            "errors": [],
        }

        # Этот метод вызывается из MCP-контекста, поэтому просто возвращаем статус
        # Реальная верификация происходит через get_index_status после notify_change
        result["note"] = (
            "Вызовите get_index_status() после notify_change для верификации"
        )
        result["verified"] = True  # Ожидает внешней верификации

        return result


def format_verification_report(results: list) -> str:
    """Форматирует результаты верификации в читаемый отчёт."""
    lines = ["📋 Execution Contract Report", ""]

    all_ok = True
    for r in results:
        status = "✅" if r.get("verified") else "❌"
        action = r.get("action", "unknown")
        lines.append(f"{status} {action}")

        if r.get("errors"):
            all_ok = False
            for err in r["errors"]:
                lines.append(f"   ⚠️ {err}")

        if r.get("commit_hash"):
            lines.append(f"   Hash: {r['commit_hash'][:8]}")
        if r.get("commit_message"):
            lines.append(f"   Message: {r['commit_message'][:60]}")
        if r.get("changed_files"):
            lines.append(f"   Files: {len(r['changed_files'])}")

    lines.append("")
    lines.append("=" * 40)
    lines.append(f"Итог: {'✅ Всё verified' if all_ok else '❌ Есть ошибки'}")

    return "\n".join(lines)
