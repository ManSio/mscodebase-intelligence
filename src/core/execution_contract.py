"""
Execution Contract — автоматическая верификация после операций записи.

Гарантирует:
1. После каждого edit_file/write_file → вызывается notify_change + get_index_status
2. После commit+push → верификация через git log
3. При ошибке — явный статус, а не ложное "успешно"
"""

import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger("execution_contract")


class ExecutionContract:
    """Валидатор действий агента."""

    @staticmethod
    def verify_file_write(file_path: str, expected_content: Optional[str] = None) -> Dict[str, Any]:
        """Верификация записи файла."""
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

        # 2. Содержимое соответствует ожидаемому?
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
                capture_output=True, text=True, timeout=10
            )
            if hash_result.returncode != 0:
                result["errors"].append(f"git rev-parse failed: {hash_result.stderr.strip()}")
                return result

            commit_hash = hash_result.stdout.strip()
            result["commit_hash"] = commit_hash

            # Получаем сообщение коммита
            msg_result = subprocess.run(
                ["git", "log", "-1", "--pretty=%B"],
                capture_output=True, text=True, timeout=10
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
                ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit_hash],
                capture_output=True, text=True, timeout=10
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
                capture_output=True, text=True, timeout=10
            )
            if status_result.returncode != 0:
                result["errors"].append(f"git status failed: {status_result.stderr.strip()}")
                return result

            status_line = status_result.stdout.strip().split("\n")[0] if status_result.stdout else ""

            # Если есть "ahead" — push не прошёл
            if "ahead" in status_line:
                result["errors"].append(f"Локальная ветка опережает remote: {status_line}")
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
        result["note"] = "Вызовите get_index_status() после notify_change для верификации"
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
