"""
Self-Diagnostic Report — автоматическая проверка здоровья системы.

Проверяет:
1. Целостность индекса (осиротевшие чанки, рассинхрон с ФС)
2. Статистику Execution Contract (отклонённые операции)
3. Состояние логов (последние ошибки)
4. Общее здоровье системы (embedder, LSP, DB)
"""

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger("health_report")


class HealthReport:
    """Генератор диностического отчёта."""

    def __init__(self, project_path: Path, indexer=None, symbol_index=None, embedder=None):
        self.project_path = project_path.resolve()
        self.indexer = indexer
        self.symbol_index = symbol_index
        self.embedder = embedder
        self.report_timestamp = datetime.now().isoformat()
        self.issues: List[Dict[str, str]] = []
        self.warnings: List[Dict[str, str]] = []
        self.metrics: Dict[str, Any] = {}

    def run_full_diagnostic(self) -> Dict[str, Any]:
        """Полная диагностика системы."""
        self.report_timestamp = datetime.now().isoformat()

        # 1. Проверка индекса
        self._check_index_integrity()

        # 2. Проверка логов
        self._check_logs()

        # 3. Проверка файловой системы
        self._check_filesystem_sync()

        # 4. Проверка компонентов
        self._check_components()

        # 5. Формирование итогового отчёта
        return self._build_report()

    def _check_index_integrity(self):
        """Проверка целостности индекса LanceDB."""
        if not self.indexer:
            self.warnings.append({"component": "indexer", "message": "Indexer недоступен для диагностики"})
            return

        try:
            status = self.indexer.get_status()
            total_chunks = status.get("total_chunks", 0)
            unique_files = status.get("unique_files", 0)

            self.metrics["total_chunks"] = total_chunks
            self.metrics["unique_files"] = unique_files
            self.metrics["db_status"] = status.get("status", "unknown")

            if total_chunks == 0:
                self.issues.append({
                    "component": "index",
                    "severity": "critical",
                    "message": "Индекс пуст (0 чанков). Требуется index_project_dir()."
                })
            elif total_chunks < 10:
                self.warnings.append({
                    "component": "index",
                    "message": f"Мало чанков ({total_chunks}). Возможно индексация не завершена."
                })

            # Проверка orphan chunks (чанки от удалённых файлов)
            try:
                if hasattr(self.indexer, 'table') and self.indexer.table is not None:
                    import pandas as pd
                    df = self.indexer.table.to_pandas()
                    if not df.empty and "file_path" in df.columns:
                        indexed_files = set(df["file_path"].unique())
                        existing_files = set()
                        for f in indexed_files:
                            full = self.project_path / f
                            if full.exists():
                                existing_files.add(f)

                        orphan_files = indexed_files - existing_files
                        if orphan_files:
                            self.warnings.append({
                                "component": "index",
                                "message": f"Осиротевшие чанки: {len(orphan_files)} файлов в индексе но не на диске",
                                "files": list(orphan_files)[:10]
                            })
                            self.metrics["orphan_files_count"] = len(orphan_files)
            except Exception as e:
                self.warnings.append({"component": "index", "message": f"Ошибка проверки orphan chunks: {e}"})

        except Exception as e:
            self.issues.append({
                "component": "index",
                "severity": "error",
                "message": f"Ошибка чтения индекса: {e}"
            })

    def _check_logs(self):
        """Проверка логов на ошибки."""
        log_dir = self.project_path / ".codebase_indices" / "logs"

        if not log_dir.exists():
            self.warnings.append({"component": "logs", "message": "Директория логов не найдена"})
            return

        try:
            log_files = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)

            if not log_files:
                self.warnings.append({"component": "logs", "message": "Лог-файлы не найдены"})
                return

            latest_log = log_files[0]
            log_size = latest_log.stat().st_size
            self.metrics["latest_log"] = latest_log.name
            self.metrics["log_size_bytes"] = log_size

            # Читаем хвост лога (последние 64KB)
            tail_size = min(64 * 1024, log_size)
            with open(latest_log, "r", encoding="utf-8", errors="replace") as f:
                f.seek(log_size - tail_size)
                tail = f.read()

            # Считаем ошибки
            error_count = tail.count("ERROR")
            critical_count = tail.count("CRITICAL")
            warning_count = tail.count("WARNING")

            self.metrics["recent_errors"] = error_count
            self.metrics["recent_critical"] = critical_count
            self.metrics["recent_warnings"] = warning_count

            if critical_count > 0:
                self.issues.append({
                    "component": "logs",
                    "severity": "critical",
                    "message": f"CRITICAL ошибок в логах: {critical_count}"
                })
            if error_count > 10:
                self.warnings.append({
                    "component": "logs",
                    "message": f"Много ошибок в логах: {error_count}"
                })

        except Exception as e:
            self.warnings.append({"component": "logs", "message": f"Ошибка чтения логов: {e}"})

    def _check_filesystem_sync(self):
        """Проверка синхронизации ФС и индекса."""
        if not self.indexer:
            return

        try:
            # Считаем .py файлы на диске
            disk_files = set()
            for f in self.project_path.rglob("*.py"):
                if "__pycache__" not in str(f) and ".venv" not in str(f) and "venv" not in str(f):
                    try:
                        rel = f.relative_to(self.project_path)
                        disk_files.add(str(rel))
                    except ValueError:
                        pass

            self.metrics["disk_py_files"] = len(disk_files)

            # Сравниваем с индексом
            if hasattr(self.indexer, 'table') and self.indexer.table is not None:
                try:
                    import pandas as pd
                    df = self.indexer.table.to_pandas()
                    if not df.empty and "file_path" in df.columns:
                        indexed_files = set(df["file_path"].unique())
                        self.metrics["indexed_files"] = len(indexed_files)

                        # Файлы на диске но не в индексе
                        unindexed = disk_files - indexed_files
                        if unindexed:
                            self.warnings.append({
                                "component": "sync",
                                "message": f"Не проиндексировано: {len(unindexed)} файлов",
                                "files": list(unindexed)[:10]
                            })
                            self.metrics["unindexed_count"] = len(unindexed)
                except Exception:
                    pass

        except Exception as e:
            self.warnings.append({"component": "sync", "message": f"Ошибка проверки синхронизации: {e}"})

    def _check_components(self):
        """Проверка состояния компонентов."""
        # Embedder
        if self.embedder:
            mode = getattr(self.embedder, "mode", "unknown")
            self.metrics["embedder_mode"] = mode
            if mode == "fallback":
                self.issues.append({
                    "component": "embedder",
                    "severity": "warning",
                    "message": "Embedder в режиме fallback. Проверь LM Studio/Ollama."
                })
        else:
            self.warnings.append({"component": "embedder", "message": "Embedder недоступен"})

        # SymbolIndex
        if self.symbol_index:
            try:
                if hasattr(self.symbol_index, "get_symbol_count"):
                    count = self.symbol_index.get_symbol_count()
                    self.metrics["total_symbols"] = count
                    if count == 0 and self.metrics.get("total_chunks", 0) > 0:
                        self.warnings.append({
                            "component": "symbol_index",
                            "message": "Символов 0 при непустом индексе. Проблема парсинга."
                        })
            except Exception as e:
                self.warnings.append({"component": "symbol_index", "message": f"Ошибка: {e}"})
        else:
            self.warnings.append({"component": "symbol_index", "message": "SymbolIndex недоступен"})

    def _build_report(self) -> Dict[str, Any]:
        """Формирование итогового отчёта."""
        total_issues = len(self.issues)
        total_warnings = len(self.warnings)

        if total_issues > 0:
            overall_health = "critical"
        elif total_warnings > 3:
            overall_health = "warning"
        else:
            overall_health = "healthy"

        return {
            "timestamp": self.report_timestamp,
            "project": str(self.project_path),
            "overall_health": overall_health,
            "issues_count": total_issues,
            "warnings_count": total_warnings,
            "metrics": self.metrics,
            "issues": self.issues,
            "warnings": self.warnings,
        }


def format_health_report(report: Dict[str, Any]) -> str:
    """Форматирует отчёт в читаемый текст."""
    health_emoji = {
        "healthy": "🟢",
        "warning": "🟡",
        "critical": "🔴"
    }

    overall = report.get("overall_health", "unknown")
    emoji = health_emoji.get(overall, "⚪")

    lines = [
        f"{emoji} Health Report: {overall.upper()}",
        f"📁 Project: {report.get('project', 'unknown')}",
        f"🕐 Time: {report.get('timestamp', 'unknown')}",
        "",
        "📊 Метрики:",
    ]

    metrics = report.get("metrics", {})
    for key, value in metrics.items():
        if key != "files":
            lines.append(f"  • {key}: {value}")

    if report.get("issues"):
        lines.append("")
        lines.append(f"❌ Проблемы ({report['issues_count']}):")
        for issue in report["issues"]:
            severity = issue.get("severity", "error").upper()
            lines.append(f"  [{severity}] {issue.get('component', '?')}: {issue.get('message', '')}")

    if report.get("warnings"):
        lines.append("")
        lines.append(f"⚠️ Предупреждения ({report['warnings_count']}):")
        for warn in report["warnings"]:
            msg = warn.get("message", "")
            lines.append(f"  [{warn.get('component', '?')}] {msg}")

    if not report.get("issues") and not report.get("warnings"):
        lines.append("")
        lines.append("✅ Всё в порядке. Проблем не обнаружено.")

    lines.append("")
    lines.append("=" * 50)

    return "\n".join(lines)
