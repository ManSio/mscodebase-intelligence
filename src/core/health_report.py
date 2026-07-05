"""
Self-Diagnostic Report — автоматическая проверка здоровья системы.

Проверяет:
1. Целостность индекса (осиротевшие чанки, рассинхрон с ФС)
2. Статистику Execution Contract (отклонённые операции)
3. Состояние логов (последние ошибки)
4. Общее здоровье системы (embedder, LSP, DB)
"""

import concurrent.futures
import logging
import os
import subprocess
import threading
import time
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
        """Выполняет функцию с таймаутом через ThreadPoolExecutor.

        В отличие от старой реализации (threading.Thread + join),
        использует executor с shutdown(wait=False) для гарантированного
        освобождения ресурсов при таймауте.
        """
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(func)
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            # Future не завершилась за timeout — отменяем + чистим
            future.cancel()
            return TimeoutError(f"Функция превысила таймаут {timeout} секунд")
        finally:
            # shutdown(wait=False) — не ждём зависший поток
            executor.shutdown(wait=False)

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

        # 4b. Проверка ресурсов (multi-window, INC-6BCB)
        logger.warning("[diag] _check_resources...")
        self._check_resources()
        logger.warning("[diag] _check_resources OK")

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

            # Метрики для отчёта (см. INC-6BCB: ранее не попадали в metrics).
            self.metrics["total_chunks"] = total_chunks
            self.metrics["unique_files"] = unique_files
            self.metrics["indexer_status"] = indexer_status

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

            # Метрики для отчёта (см. INC-6BCB).
            self.metrics["total_chunks"] = total_chunks
            self.metrics["unique_files"] = unique_files

            if total_chunks == 0 and unique_files == 0:
                self.warnings.append(
                    {
                        "component": "filesystem_sync",
                        "message": "Индекс пуст",
                    }
                )
                return

            # Детекция осиротевших файлов: в индексе есть, на диске нет.
            # (См. INC-6BCB: фича была в docstring, но не реализована.)
            try:
                files_in_index = set()
                if hasattr(self.indexer, "table") and self.indexer.table is not None:
                    try:
                        files_in_index = set(
                            self.indexer.table.to_pandas()["file_path"].unique()
                        )
                    except Exception:
                        # LanceDB фильтр (быстрее, не грузит всю таблицу в память)
                        try:
                            df = self.indexer.table.search().limit(100000).to_pandas()
                            files_in_index = set(df["file_path"].unique())
                        except Exception:
                            pass

                if files_in_index:
                    files_on_disk = set()
                    rglob_count = 0
                    for p in self.project_path.rglob("*"):
                        rglob_count += 1
                        # Защита: не сканируем больше 10000 файлов
                        if rglob_count > 10000:
                            self.warnings.append(
                                {
                                    "component": "filesystem_sync",
                                    "message": f"Проект >10000 файлов — rglob прерван после {rglob_count}",
                                }
                            )
                            break
                        if p.is_file():
                            try:
                                rel = str(p.relative_to(self.project_path))
                                rel = rel.replace(os.sep, "/")
                                files_on_disk.add(rel)
                            except ValueError:
                                pass
                    orphans = files_in_index - files_on_disk
                    if orphans:
                        # Удаляем мёртвые записи из индекса
                        deleted_count = 0
                        for orphan_path in orphans:
                            if hasattr(self.indexer, "delete_file"):
                                try:
                                    if self.indexer.delete_file(orphan_path):
                                        deleted_count += 1
                                except Exception:
                                    pass
                        self.warnings.append(
                            {
                                "component": "filesystem_sync",
                                "message": (
                                    f"Осиротевшие файлы в индексе "
                                    f"({len(orphans)}): удалены с диска, "
                                    f"очищено {deleted_count} из индекса"
                                ),
                                "count": len(orphans),
                            }
                        )
                        self.metrics["orphan_files_count"] = len(orphans)
                        self.metrics["orphan_files_cleaned"] = deleted_count
            except Exception as orph_err:
                logger.debug(f"Orphan detection skipped: {orph_err}")

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
                embedder_mode = getattr(self.embedder, "mode", "unknown")
                self.metrics["embedder_status"] = embedder_mode
                self.metrics["embedder_mode"] = embedder_mode  # алиас (INC-6BCB)
                self.metrics["embedder_available"] = embedder_mode not in (
                    "unknown",
                    "fallback",
                )
                # Fallback = degraded (warning), не critical — восстанавливается запуском LM Studio.
                if embedder_mode == "fallback":
                    self.warnings.append(
                        {
                            "component": "embedder",
                            "message": "Embedder в fallback-режиме: векторный поиск недоступен",
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
                if hasattr(self.symbol_index, "get_symbol_count"):
                    symbol_count = self.symbol_index.get_symbol_count()
                elif hasattr(self.symbol_index, "_definitions"):
                    symbol_count = len(self.symbol_index._definitions)
                else:
                    symbol_count = "unknown"
                self.metrics["symbol_index_count"] = symbol_count
                # Алиас для обратной совместимости с тестами (см. INC-6BCB).
                self.metrics["total_symbols"] = symbol_count
                # Символов 0 при непустом индексе = аномалия (см. INC-6BCB).
                if symbol_count == 0 and self.metrics.get("total_chunks", 0) > 0:
                    self.warnings.append(
                        {
                            "component": "symbol_index",
                            "message": "Символов 0 при непустом индексе — требуется переиндексация",
                        }
                    )
            except Exception as e:
                self.issues.append(
                    {
                        "component": "symbol_index",
                        "message": f"Ошибка проверки symbol_index: {e}",
                    }
                )

    def _check_resources(self):
        """Проверка ресурсов процесса (RAM/CPU) и registry (multi-window).

        (См. INC-6BCB / multi-window: добавлено для отслеживания adaptive
        throttling и LRU eviction.)
        """
        try:
            from src.core.project_indexer_registry import get_global_registry
            from src.core.resource_monitor import get_global_resource_monitor

            monitor = get_global_resource_monitor()
            summary = monitor.get_summary()
            self.metrics["process_rss_mb"] = summary["rss_mb"]
            self.metrics["process_cpu_percent"] = summary["cpu_percent"]
            self.metrics["process_threads"] = summary["num_threads"]

            if summary["under_hard_pressure"]:
                self.issues.append(
                    {
                        "component": "resources",
                        "message": (
                            f"Жёсткое давление: RAM={summary['rss_mb']:.0f}MB / "
                            f"CPU={summary['cpu_percent']:.0f}%. "
                            f"LRU eviction активен."
                        ),
                    }
                )
            elif summary["under_soft_pressure"]:
                self.warnings.append(
                    {
                        "component": "resources",
                        "message": (
                            f"Мягкое давление: RAM={summary['rss_mb']:.0f}MB / "
                            f"CPU={summary['cpu_percent']:.0f}%. "
                            f"Throttling индексации активен."
                        ),
                    }
                )

            registry = get_global_registry()
            reg_stats = registry.get_stats()
            self.metrics["registry_cached_projects"] = reg_stats["cached_projects"]
            self.metrics["registry_max_cached"] = reg_stats["max_cached"]
            self.metrics["registry_cache_hits"] = reg_stats["cache_hits"]
            self.metrics["registry_cache_misses"] = reg_stats["cache_misses"]
            self.metrics["registry_evictions"] = reg_stats["evictions"]
            self.metrics["registry_pressure_evicts"] = reg_stats[
                "evictions_for_pressure"
            ]

            if reg_stats["cached_projects"] >= reg_stats["max_cached"]:
                self.warnings.append(
                    {
                        "component": "registry",
                        "message": (
                            f"Кэш ProjectIndexerRegistry заполнен "
                            f"({reg_stats['cached_projects']}/{reg_stats['max_cached']}). "
                            f"Следующее окно вытеснит LRU."
                        ),
                    }
                )
        except Exception as e:
            self.warnings.append(
                {
                    "component": "resources",
                    "message": f"Ошибка проверки ресурсов: {e}",
                }
            )

    def _check_execution_contract(self):
        """Проверка Execution Contract (git operations, timeout=30s)."""

        def _git_worker():
            try:
                _env = os.environ.copy()
                _env["GIT_TERMINAL_PROMPT"] = "0"
                _env["GIT_ASKPASS"] = "echo"
                _env["GIT_PAGER"] = "cat"
                _env["PAGER"] = "cat"
                out = subprocess.check_output(
                    ["git", "log", "--oneline", "-1"],
                    cwd=str(self.project_path),
                    stderr=subprocess.DEVNULL,
                    timeout=15,
                    env=_env,
                )
                return out.strip().decode("utf-8")
            except subprocess.TimeoutExpired:
                return -3
            except Exception:
                return -2

        try:
            # Вызов оригинального _run_with_timeout из первой части кода
            last_commit = self._run_with_timeout(_git_worker, timeout=30)

            # Если вернулось исключение или TimeoutError
            if isinstance(last_commit, (Exception, TimeoutError)):
                self.warnings.append(
                    {
                        "component": "execution_contract",
                        "message": f"Git операция не удалась: {last_commit}",
                    }
                )
            elif last_commit == -2:
                # Git не инициализирован в проекте — это нормально для
                # не-git-проектов и тестовых окружений (см. INC-6BCB).
                # Понижаем severity с issue до warning.
                self.warnings.append(
                    {
                        "component": "execution_contract",
                        "message": "Git не инициализирован или ошибка команды",
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

        Три тестовых запроса с таймаутом 30с каждый.
        LM Studio может отвечать до 25с на поиск — не блокируем диагностику.
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

                # Используем оригинальный враппер через твой _run_with_timeout с лимитом 30 секунд
                res = self._run_with_timeout(_search, timeout=30.0)

                if isinstance(res, (Exception, TimeoutError)):
                    self.warnings.append(
                        {
                            "component": "search_quality",
                            "message": f"Тест поиска #{i + 1} завершился с ошибкой/таймаутом: {res}",
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
                            "message": f"Search вернул пустой результат на шаге #{i + 1}",
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
    """Форматирование отчёта для читаемого вывода.

    Поддерживаемые статусы: healthy / degraded / warning / critical.
    (См. INC-6BCB: добавлен 'degraded' для отличия обратимых warnings
    от жёстких 'critical' issues.)
    """
    # Эмодзи-индикатор статуса
    health_emoji = {
        "healthy": "🟢",
        "degraded": "🟡",
        "warning": "🟡",
        "critical": "🔴",
    }.get(report.get("overall_health", ""), "⚪")

    health_msg = {
        "healthy": "Всё в порядке",
        "degraded": "Работает, но есть предупреждения",
        "warning": "Есть предупреждения",
        "critical": "Обнаружены критические проблемы",
    }.get(report.get("overall_health", ""), "")

    lines = []
    lines.append("=" * 60)
    lines.append("Self-Diagnostic Report")
    lines.append("=" * 60)
    lines.append(f"Timestamp: {report['timestamp']}")
    lines.append(f"Overall Health: {health_emoji} {report['overall_health'].upper()}")
    if health_msg:
        lines.append(f"Message: {health_msg}")
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
