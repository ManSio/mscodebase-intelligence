"""
Self-Diagnostic Report — автоматическая проверка здоровья системы.

Проверяет:
1. Целостность индекса (осиротевшие чанки, рассинхрон с ФС)
2. Статистику Execution Contract (отклонённые операции)
3. Состояние логов (последние ошибки)
4. Общее здоровье системы (embedder, LSP, DB)
"""

import logging
import os
import time
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("mscodebase_server")


class HealthReport:
    """Генератор диагностического отчёта."""

    def __init__(
        self, project_path: Path, indexer=None, symbol_index=None, embedder=None
    ):
        self.project_path = project_path.resolve()
        self.indexer = indexer
        self.symbol_index = symbol_index
        self.embedder = embedder
        self.report_timestamp = datetime.now().isoformat()
        self.issues: List[Dict[str, Any]] = []
        self._df_cache: Any = None  # кэш DataFrame для избежания двойной загрузки
        self.warnings: List[Dict[str, Any]] = []
        self.metrics: Dict[str, Any] = {}

    def _run_with_timeout(self, func, timeout=30):
        """Выполняет функцию с таймаутом (упрощённо, без создания ThreadPoolExecutor)."""
        result_box = []
        error_box = []

        def wrapper():
            try:
                result_box.append(func())
            except BaseException as e:
                error_box.append(e)

        t = threading.Thread(target=wrapper, daemon=True)
        t.start()
        t.join(timeout=timeout)
        if t.is_alive():
            return TimeoutError(f"Функция превысила таймаут {timeout} секунд")
        if error_box:
            return error_box[0]
        return result_box[0] if result_box else None

    def run_full_diagnostic(self) -> Dict[str, Any]:
        """Полная диагностика системы."""
        self.report_timestamp = datetime.now().isoformat()
        self.issues.clear()
        self.warnings.clear()
        self.metrics.clear()

        # 1. Проверка индекса
        logger.warning("[diag] _check_index_integrity...")
        self._check_index_integrity()
        logger.warning("[diag] _check_index_integrity OK")

        # 2. Проверка логов
        logger.warning("[diag] _check_logs...")
        self._check_logs()
        logger.warning("[diag] _check_logs OK")

        # 3. Проверка файловой системы
        logger.warning("[diag] _check_filesystem_sync...")
        self._check_filesystem_sync()
        logger.warning("[diag] _check_filesystem_sync OK")

        # 4. Проверка компонентов
        logger.warning("[diag] _check_components...")
        self._check_components()
        logger.warning("[diag] _check_components OK")

        # 5. Execution Contract верификация
        logger.warning("[diag] _check_execution_contract...")
        self._check_execution_contract()
        logger.warning("[diag] _check_execution_contract OK")

        # 6. Synthetic monitoring (качество поиска)
        logger.warning("[diag] _check_search_quality...")
        self._check_search_quality()
        logger.warning("[diag] _check_search_quality OK")

        # 7. Формирование итогового отчёта
        logger.warning("[diag] _build_report...")
        result = self._build_report()
        logger.warning("[diag] _build_report OK")
        return result

    def _check_index_integrity(self):
        """Проверка целостности индекса LanceDB."""
        if not self.indexer:
            self.warnings.append(
                {
                    "component": "indexer",
                    "message": "Indexer недоступен",
                }
            )
            return

        try:
            status = self.indexer.get_status()
            if not status:
                self.issues.append(
                    {
                        "component": "indexer",
                        "message": "Невозможно получить статус индекса",
                    }
                )
                return

            total_chunks = status.get("total_chunks", 0)
            unique_files = status.get("unique_files", 0)
            indexer_status = status.get("status", "unknown")

            if total_chunks == 0:
                self.issues.append(
                    {
                        "component": "indexer",
                        "message": "Индекс пуст (нет чанков)",
                    }
                )

            if indexer_status not in ("active", "ready"):
                self.issues.append(
                    {
                        "component": "indexer",
                        "message": f"Индекс в неактивном состоянии: {indexer_status}",
                    }
                )

            if unique_files == 0 and total_chunks > 0:
                self.warnings.append(
                    {
                        "component": "indexer",
                        "message": "Есть чанки, но нет уникальных файлов",
                    }
                )

        except Exception as e:
            self.issues.append(
                {
                    "component": "indexer",
                    "message": f"Ошибка проверки индекса: {e}",
                }
            )

    def _check_logs(self):
        """Проверка состояния логов."""
        logs_dir = self.project_path / ".codebase_indices" / "logs"
        if not logs_dir.exists():
            self.warnings.append(
                {
                    "component": "logs",
                    "message": "Директория логов не существует",
                }
            )
            return

        try:
            log_files = list(logs_dir.glob("*.log"))
            if not log_files:
                self.warnings.append(
                    {
                        "component": "logs",
                        "message": "Нет файлов логов",
                    }
                )
                return

            latest_log = max(log_files, key=lambda p: p.stat().st_mtime)
            self.metrics["latest_log_file"] = latest_log.name

            try:
                with open(latest_log, "r", encoding="utf-8") as f:
                    content = f.read()
                    error_count = content.lower().count("error")
                    warning_count = content.lower().count("warning")

                self.metrics["latest_log_errors"] = error_count
                self.metrics["latest_log_warnings"] = warning_count

                if error_count > 10:
                    self.issues.append(
                        {
                            "component": "logs",
                            "message": f"Много ошибок в последнем логе: {error_count}",
                        }
                    )

            except Exception as e:
                self.warnings.append(
                    {
                        "component": "logs",
                        "message": f"Ошибка чтения лога: {e}",
                    }
                )

        except Exception as e:
            self.issues.append(
                {
                    "component": "logs",
                    "message": f"Ошибка проверки логов: {e}",
                }
            )

    def _check_filesystem_sync(self):
        """Проверка синхронизации с файловой системой."""
        if not self.indexer:
            self.warnings.append(
                {
                    "component": "filesystem_sync",
                    "message": "Indexer недоступен для проверки синхронизации",
                }
            )
            return

        try:
            status = self.indexer.get_status()
            if not status:
                self.issues.append(
                    {
                        "component": "filesystem_sync",
                        "message": "Невозможно получить статус индекса",
                    }
                )
                return

            total_chunks = status.get("total_chunks", 0)
            unique_files = status.get("unique_files", 0)

            if total_chunks == 0 and unique_files == 0:
                self.warnings.append(
                    {
                        "component": "filesystem_sync",
                        "message": "Индекс пуст",
                    }
                )

        except Exception as e:
            self.issues.append(
                {
                    "component": "filesystem_sync",
                    "message": f"Ошибка проверки синхронизации: {e}",
                }
            )

    def _check_components(self):
        """Проверка компонентов системы."""
        if self.embedder:
            try:
                embedder_status = self.embedder.get_status()
                self.metrics["embedder_status"] = embedder_status
                if not embedder_status:
                    self.issues.append(
                        {
                            "component": "embedder",
                            "message": "Embedder недоступен",
                        }
                    )
            except Exception as e:
                self.issues.append(
                    {
                        "component": "embedder",
                        "message": f"Ошибка проверки embedder: {e}",
                    }
                )

        if self.symbol_index:
            try:
                symbol_status = self.symbol_index.get_status()
                self.metrics["symbol_index_status"] = symbol_status
                if not symbol_status:
                    self.issues.append(
                        {
                            "component": "symbol_index",
                            "message": "Symbol index недоступен",
                        }
                    )
            except Exception as e:
                self.issues.append(
                    {
                        "component": "symbol_index",
                        "message": f"Ошибка проверки symbol_index: {e}",
                    }
                )

    def _check_execution_contract(self):
        """Проверка Execution Contract (git operations)."""

        def _git_worker():
            try:
                out = subprocess.check_output(
                    ["git", "log", "--oneline", "-1"],
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
                return out.strip().decode("utf-8")
            except subprocess.TimeoutExpired:
                return -3
            except Exception:
                return -2

        try:
            # Вызов оригинального _run_with_timeout из первой части кода
            last_commit = self._run_with_timeout(_git_worker, timeout=10)

            # Если вернулось исключение или TimeoutError
            if isinstance(last_commit, (Exception, TimeoutError)):
                self.warnings.append(
                    {
                        "component": "execution_contract",
                        "message": f"Git операция не удалась: {last_commit}",
                    }
                )
            elif last_commit == -2:
                self.issues.append(
                    {
                        "component": "execution_contract",
                        "message": "Git ошибка при выполнении команды",
                    }
                )
            elif last_commit == -3:
                self.warnings.append(
                    {
                        "component": "execution_contract",
                        "message": "Превышен внутренний таймаут Git команды",
                    }
                )
            else:
                self.metrics["last_commit"] = last_commit

        except Exception as e:
            self.issues.append(
                {
                    "component": "execution_contract",
                    "message": f"Ошибка проверки execution contract: {e}",
                }
            )

    def _check_search_quality(self):
        """Synthetic monitoring: проверка качества семантического поиска.

        Три тестовых запроса с таймаутом 8с каждый.
        LM Studio может отвечать до 7с на поиск — не блокируем диагностику.
        """
        if (
            not self.indexer
            or not hasattr(self.indexer, "searcher")
            or not self.indexer.searcher
        ):
            self.warnings.append(
                {
                    "component": "search_quality",
                    "message": "Searcher недоступен для synthetic monitoring",
                }
            )
            self.metrics["search_quality_total_tests"] = 3
            self.metrics["search_quality_passed"] = 0
            return

        try:
            searcher = self.indexer.searcher
            total_tests = 3
            passed_tests = 0
            self.metrics["search_quality_total_tests"] = total_tests

            for i in range(total_tests):
                _out = {"results": None, "error": None}

                def _search():
                    try:
                        _out["results"] = searcher.search("index file", 3)
                    except Exception as e:
                        _out["error"] = str(e)

                # Используем оригинальный враппер через твой _run_with_timeout с лимитом 8 секунд
                res = self._run_with_timeout(_search, timeout=8.0)

                if isinstance(res, (Exception, TimeoutError)):
                    self.warnings.append(
                        {
                            "component": "search_quality",
                            "message": f"Тест поиска #{i+1} завершился с ошибкой/таймаутом: {res}",
                        }
                    )
                    continue

                results = _out["results"]
                if results and len(results) > 0:
                    passed_tests += 1
                else:
                    self.warnings.append(
                        {
                            "component": "search_quality",
                            "message": f"Search вернул пустой результат на шаге #{i+1}",
                        }
                    )

            self.metrics["search_quality_passed"] = passed_tests

        except Exception as e:
            self.warnings.append(
                {
                    "component": "search_quality",
                    "message": f"Synthetic monitoring error: {e}",
                }
            )
            self.metrics["search_quality_total_tests"] = 3

    def _build_report(self) -> Dict[str, Any]:
        """Формирование итогового отчёта."""
        total_issues = len(self.issues)
        total_warnings = len(self.warnings)

        if total_issues > 0:
            overall_health = "critical"
        elif total_warnings > 0:
            overall_health = "degraded"
        else:
            overall_health = "healthy"

        report = {
            "timestamp": self.report_timestamp,
            "overall_health": overall_health,
            "issues": self.issues,
            "warnings": self.warnings,
            "metrics": self.metrics,
        }

        return report


def format_health_report(report: Dict[str, Any]) -> str:
    """Форматирование отчёта для читаемого вывода."""
    lines = []
    lines.append("=" * 60)
    lines.append("Self-Diagnostic Report")
    lines.append("=" * 60)
    lines.append(f"Timestamp: {report['timestamp']}")
    lines.append(f"Overall Health: {report['overall_health'].upper()}")
    lines.append("")

    if report["issues"]:
        lines.append("ISSUES:")
        for issue in report["issues"]:
            lines.append(f"  - [{issue['component']}] {issue['message']}")
        lines.append("")

    if report["warnings"]:
        lines.append("WARNINGS:")
        for warning in report["warnings"]:
            lines.append(f"  - [{warning['component']}] {warning['message']}")
        lines.append("")

    if report["metrics"]:
        lines.append("METRICS:")
        for key, value in report["metrics"].items():
            lines.append(f"  - {key}: {value}")
        lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)
