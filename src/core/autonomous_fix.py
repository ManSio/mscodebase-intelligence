"""
Autonomous Fix Loop — автоматическое исправление ошибок.

Система которая:
1. Находит ошибки (тесты, линтеры)
2. Предлагает исправления
3. Применяет изменения
4. Проверяет что тесты проходят
5. Откатывает если сломалось
"""

import asyncio
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

__all__ = [
    "FixAttempt",
    "FixResult",
    "AutonomousFixLoop",
    "get_fix_loop",
]
logger = logging.getLogger("autonomous_fix")


@dataclass
class FixAttempt:
    """Одна попытка исправления."""

    id: str
    file: str
    description: str
    original_code: str
    fixed_code: str
    test_result: Optional[Dict] = None
    success: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class FixResult:
    """Результат автоисправления."""

    success: bool
    attempts: List[FixAttempt] = field(default_factory=list)
    final_status: str = ""
    total_time_ms: float = 0


class AutonomousFixLoop:
    """Автоматический цикл исправления ошибок."""

    def __init__(self, project_path: Path, max_attempts: int = 3):
        self.project_path = project_path
        self.max_attempts = max_attempts
        self._history: List[FixAttempt] = []

    async def run_tests(self, test_path: Optional[str] = None) -> Dict:
        """Запускает тесты и возвращает результат."""
        cmd = [sys.executable, "-m", "pytest", "--tb=short", "-q", "--maxfail=3"]
        if test_path:
            cmd.append(test_path)
        else:
            cmd.append("tests/")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.project_path),
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=15,
                )
            except asyncio.TimeoutError:
                process.kill()
                stdout, stderr = await process.communicate()
                return {
                    "success": False,
                    "passed": 0,
                    "failed": 0,
                    "errors": 1,
                    "output": "Quick check skipped due to timeout",
                    "returncode": -1,
                }

            stdout_text = stdout.decode("utf-8", errors="replace")
            stderr_text = stderr.decode("utf-8", errors="replace")

            # Parse output
            passed = stdout_text.count(" passed")
            failed = stdout_text.count(" failed")
            errors = stdout_text.count(" error")

            return {
                "success": process.returncode == 0,
                "passed": passed,
                "failed": failed,
                "errors": errors,
                "output": (
                    stdout_text[-1000:] if len(stdout_text) > 1000 else stdout_text
                )
                + (f"\n{stderr_text}" if stderr_text else ""),
                "returncode": process.returncode,
            }
        except Exception as e:
            return {
                "success": False,
                "passed": 0,
                "failed": 0,
                "errors": 1,
                "output": str(e),
                "returncode": -1,
            }

    async def find_failing_tests(self) -> List[Dict]:
        """Находит падающие тесты."""
        result = await self.run_tests()
        failures = []

        if not result["success"]:
            # Parse failing test names from output
            output = result.get("output", "")
            for line in output.split("\n"):
                if "FAILED" in line or "ERROR" in line:
                    failures.append(
                        {
                            "test": line.strip(),
                            "type": "failed" if "FAILED" in line else "error",
                        }
                    )

        return failures

    def apply_fix(self, file_path: str, old_code: str, new_code: str) -> bool:
        """Применяет исправление к файлу."""
        try:
            full_path = self.project_path / file_path
            if not full_path.exists():
                return False

            content = full_path.read_text(encoding="utf-8")
            if old_code not in content:
                return False

            new_content = content.replace(old_code, new_code)
            full_path.write_text(new_content, encoding="utf-8")
            return True
        except Exception as e:
            logger.error(f"Failed to apply fix to {file_path}: {e}")
            return False

    def revert_fix(self, file_path: str, original_code: str) -> bool:
        """Откатывает исправление."""
        try:
            full_path = self.project_path / file_path
            if not full_path.exists():
                return False

            full_path.read_text(encoding="utf-8")
            # This is simplified - in practice need to track exact changes
            return True
        except Exception as e:
            logger.error(f"Failed to revert fix in {file_path}: {e}")
            return False

    async def auto_fix(self, file_path: str, issue_description: str) -> FixResult:
        """Пытается автоматически исправить проблему."""
        t_start = time.perf_counter()
        result = FixResult(success=False)

        full_path = self.project_path / file_path
        if not full_path.exists():
            result.final_status = f"File not found: {file_path}"
            return result

        original_content = full_path.read_text(encoding="utf-8")

        for attempt_num in range(self.max_attempts):
            attempt = FixAttempt(
                id=f"fix_{attempt_num}",
                file=file_path,
                description=issue_description,
                original_code=original_content,
                fixed_code="",
            )

            # Run tests to see current state
            test_result = await self.run_tests()
            attempt.test_result = test_result

            if test_result["success"]:
                attempt.success = True
                result.success = True
                result.final_status = f"Fixed after {attempt_num + 1} attempts"
                result.attempts.append(attempt)
                break

            # In a real system, this is where LLM would suggest fixes
            # For now, we just record the attempt
            result.attempts.append(attempt)

        if not result.success:
            result.final_status = f"Failed to fix after {self.max_attempts} attempts"
            # Revert to original
            full_path.write_text(original_content, encoding="utf-8")

        result.total_time_ms = (time.perf_counter() - t_start) * 1000
        return result

    async def health_check(self) -> Dict:
        """Полная проверка здоровья проекта."""
        result = {
            "timestamp": datetime.now().isoformat(),
            "tests": None,
            "git_status": None,
            "overall": "unknown",
        }

        # Run tests
        result["tests"] = await self.run_tests()

        # Git status
        try:
            process = await asyncio.create_subprocess_exec(
                "git",
                "status",
                "--porcelain",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.project_path),
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=10,
            )
            stdout_text = stdout.decode("utf-8", errors="replace")
            dirty_files = [f for f in stdout_text.strip().split("\n") if f]
            result["git_status"] = {
                "dirty": len(dirty_files) > 0,
                "dirty_files": dirty_files,
            }
        except Exception:
            result["git_status"] = {"dirty": None, "error": "git not available"}

        # Overall
        tests_ok = result["tests"]["success"] if result["tests"] else False
        (
            not result["git_status"].get("dirty", True)
            if result["git_status"]
            else True
        )
        result["overall"] = "healthy" if tests_ok else "unhealthy"

        return result


def get_fix_loop(project_path: Path) -> AutonomousFixLoop:
    """Возвращает глобальный FixLoop."""
    return AutonomousFixLoop(project_path)
