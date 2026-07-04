"""
Self-Diagnostic Report — автоматическая проверка здоровья системы.

Проверяет:
1. Целостность индекса (осиротевшие чанки, рассинхрон с ФС)
2. Статистику Execution Contract (отклонённые операции)
3. Состояние логов (последние ошибки)
4. Общее здоровье системы (embedder, LSP, DB)
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("mscodebase_server")


class HealthReport:
    """Генератор диностического отчёта."""

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
        import threading
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
                    "message": "Indexer недоступен для диагностики",
                }
            )
            return

        try:
            status = self.indexer.get_status()
            total_chunks = status.get("total_chunks", 0)
            unique_files = status.get("unique_files", 0)

            self.metrics["total_chunks"] = total_chunks
            self.metrics["unique_files"] = unique_files
            self.metrics["db_status"] = status.get("status", "unknown")

            if total_chunks == 0:
                self.issues.append(
                    {
                        "component": "index",
                        "severity": "critical",
                        "message": "Индекс пуст (0 чанков). Требуется index_project_dir().",
                    }
                )
            elif total_chunks < 10:
                self.warnings.append(
                    {
                        "component": "index",
                        "message": f"Мало чанков ({total_chunks}). Возможно индексация не завершена.",
                    }
                )

            # Проверка orphan chunks (чанки от удалённых файлов)
            try:
                if hasattr(self.indexer, "table") and self.indexer.table is not None:
                    import pandas as pd

                    if self._df_cache is None:
                        self._df_cache = self.indexer.table.to_pandas()
                    df = self._df_cache
                    if not df.empty and "file_path" in df.columns:
                        indexed_files = set(df["file_path"].unique())
                        existing_files = set()
                        for f in indexed_files:
                            full = self.project_path / f
                            if full.exists():
                                existing_files.add(f)

                        orphan_files = indexed_files - existing_files
                        if orphan_files:
                            self.warnings.append(
                                {
                                    "component": "index",
                                    "message": f"Осиротевшие чанки: {len(orphan_files)} файлов в индексе но не на диске",
                                    "files": list(orphan_files)[:10],
                                }
                            )
                            self.metrics["orphan_files_count"] = len(orphan_files)
            except Exception as e:
                self.warnings.append(
                    {
                        "component": "index",
                        "message": f"Ошибка проверки orphan chunks: {e}",
                    }
                )

        except Exception as e:
            self.issues.append(
                {
                    "component": "index",
                    "severity": "error",
                    "message": f"Ошибка чтения индекса: {e}",
                }
            )

    def _check_logs(self):
        """Проверка логов на ошибки."""
        log_dir = self.project_path / ".codebase_indices" / "logs"

        if not log_dir.exists():
            self.warnings.append(
                {"component": "logs", "message": "Директория логов не найдена"}
            )
            return

        try:
            log_files = sorted(
                log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True
            )

            if not log_files:
                self.warnings.append(
                    {"component": "logs", "message": "Лог-файлы не найдены"}
                )
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
                self.issues.append(
                    {
                        "component": "logs",
                        "severity": "critical",
                        "message": f"CRITICAL ошибок в логах: {critical_count}",
                    }
                )
            if error_count > 10:
                self.warnings.append(
                    {
                        "component": "logs",
                        "message": f"Много ошибок в логах: {error_count}",
                    }
                )

        except Exception as e:
            self.warnings.append(
                {"component": "logs", "message": f"Ошибка чтения логов: {e}"}
            )

    def _check_filesystem_sync(self):
        """Проверка синхронизации ФС и индекса."""
        if not self.indexer:
            return

        try:
            # Считаем .py файлы на диске (только src/, tests/, scripts/)
            disk_files = set()
            scan_dirs = ["src", "tests", "scripts", "install.py"]
            for d in scan_dirs:
                p = self.project_path / d
                if p.is_file():
                    disk_files.add(str(p.relative_to(self.project_path)))
                elif p.is_dir():
                    for f in p.rglob("*.py"):
                        if "__pycache__" not in str(f):
                            try:
                                rel = f.relative_to(self.project_path)
                                disk_files.add(str(rel))
                            except ValueError:
                                pass

            self.metrics["disk_py_files"] = len(disk_files)

            # Сравниваем с индексом (используем кэш из _check_index_integrity)
            if self._df_cache is not None:
                try:
                    df = self._df_cache
                    if not df.empty and "file_path" in df.columns:
                        indexed_files = set(df["file_path"].unique())
                        self.metrics["indexed_files"] = len(indexed_files)

                        # Файлы на диске но не в индексе
                        unindexed = disk_files - indexed_files
                        if unindexed:
                            self.warnings.append(
                                {
                                    "component": "sync",
                                    "message": f"Не проиндексировано: {len(unindexed)} файлов",
                                    "files": list(unindexed)[:10],
                                }
                            )
                            self.metrics["unindexed_count"] = len(unindexed)
                except Exception:
                    pass

        except Exception as e:
            self.warnings.append(
                {"component": "sync", "message": f"Ошибка проверки синхронизации: {e}"}
            )

    def _check_components(self):
        """Проверка состояния компонентов."""
        # Embedder
        if self.embedder:
            mode = getattr(self.embedder, "mode", "unknown")
            self.metrics["embedder_mode"] = mode
            if mode == "fallback":
                self.issues.append(
                    {
                        "component": "embedder",
                        "severity": "warning",
                        "message": "Embedder в режиме fallback. Проверь LM Studio/Ollama.",
                    }
                )
        else:
            self.warnings.append(
                {"component": "embedder", "message": "Embedder недоступен"}
            )

        # SymbolIndex
        if self.symbol_index:
            try:
                if hasattr(self.symbol_index, "get_symbol_count"):
                    count = self.symbol_index.get_symbol_count()
                    self.metrics["total_symbols"] = count
                    if count == 0 and self.metrics.get("total_chunks", 0) > 0:
                        self.warnings.append(
                            {
                                "component": "symbol_index",
                                "message": "Символов 0 при непустом индексе. Проблема парсинга.",
                            }
                        )
            except Exception as e:
                self.warnings.append(
                    {"component": "symbol_index", "message": f"Ошибка: {e}"}
                )
        else:
            self.warnings.append(
                {"component": "symbol_index", "message": "SymbolIndex недоступен"}
            )

    def _check_execution_contract(self):
        """Верификация Execution Contract: git state.

        На Windows subprocess.run(timeout=X) не всегда убивает git
        (git порождает дочерние процессы git-remote-https.exe / CredentialManager,
        которые остаются висеть, блокируя stdout/stderr).

        Решение: daemon-поток + join(timeout). Если git завис — бросаем поток
        и продолжаем диагностику. Потери: 1 daemon-поток на зависший git.
        """
        import subprocess
        import os as _os
        import threading as _threading

        _env = _os.environ.copy()
        _env["GIT_TERMINAL_PROMPT"] = "0"
        _env["GIT_PAGER"] = "cat"
        _env["PAGER"] = "cat"

        def _git_worker(args, out):
            """Запускает git в изолированном daemon-потоке."""
            try:
                res = subprocess.run(args, capture_output=True, text=True, env=_env, cwd=str(self.project_path))
                out["rc"] = res.returncode
                out["out"] = res.stdout
                out["err"] = res.stderr
            except FileNotFoundError:
                out["rc"] = -2  # git not found
            except Exception as e:
                out["rc"] = -1
                out["err"] = str(e)

        def _run_git_safe(args, timeout=4):
            """Запускает git с жёстким таймаутом через daemon-поток."""
            out = {"rc": -1, "out": "", "err": ""}
            t = _threading.Thread(target=_git_worker, args=(args, out), daemon=True)
            t.start()
            t.join(timeout=timeout)
            if t.is_alive():
                # Git завис — бросаем поток, продолжаем диагностику
                return -3, "", f"git timeout after {timeout}s"
            return out["rc"], out["out"], out["err"]

        # 1. git status --porcelain
        rc, out, err = _run_git_safe(["git", "--no-pager", "status", "--porcelain"], timeout=4)
        if rc == 0:
            dirty = [f for f in out.strip().split("\n") if f]
            if dirty:
                self.warnings.append({
                    "component": "execution_contract",
                    "message": f"Незакоммиченные изменения: {len(dirty)} файлов",
                    "files": dirty[:5],
                })
            self.metrics["git_dirty_files"] = len(dirty)
        elif rc == -3:
            self.warnings.append({"component": "execution_contract", "message": "Git status timeout (Windows I/O lock)"})
        elif rc == -2:
            self.warnings.append({"component": "execution_contract", "message": "Git not found"})
        elif rc != 0:
            self.warnings.append({"component": "execution_contract", "message": f"Git status error: {err[:60]}"})

        # 2. git status -sb (без remote — только --no-ahead-behind)
        rc, out, err = _run_git_safe(["git", "--no-pager", "status", "-sb", "--no-ahead-behind"], timeout=4)
        if rc == 0:
            line = out.strip().split("\n")[0] if out else ""
            self.metrics["git_synced"] = "ahead" not in line
        elif rc == -3:
            self.warnings.append({"component": "execution_contract", "message": "Git status -sb timeout"})

        # 3. git log -1
        rc, out, err = _run_git_safe(["git", "--no-pager", "log", "-1", "--oneline"], timeout=4)
        if rc == 0:
            self.metrics["last_commit"] = out.strip()
        elif rc == -3:
            self.warnings.append({"component": "execution_contract", "message": "Git log timeout"})

    def _check_search_quality(self):
        """Synthetic monitoring: проверка качества семантического поиска.

        Только 1 тестовый запрос (вместо 3) с таймаутом 8с.
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
            return

        try:
            searcher = self.indexer.searcher

            # 1 тестовый поиск с таймаутом
            import threading as _t
            _out = {"results": None, "error": None}

            def _search():
                try:
                    _out["results"] = searcher.search("index file", 3)
                except Exception as e:
                    _out["error"] = str(e)

            t = _t.Thread(target=_search, daemon=True)
            t.start()
            t.join(timeout=8)

            if _out["error"]:
                self.warnings.append({"component": "search_quality", "message": f"Search error: {_out['error'][:60]}"})
                return

            if t.is_alive():
                self.warnings.append({"component": "search_quality", "message": "Search timeout (>8s)"})
                self.metrics["search_quality_passed"] = 0
                self.metrics["search_quality_total_tests"] = 1
                return

            results = _out["results"]
            passed = 1 if results and len(results) > 0 else 0
            self.metrics["search_quality_passed"] = passed
            self.metrics["search_quality_total_tests"] = 1

            if passed == 0:
                self.warnings.append({"component": "search_quality", "message": "Search returned no results"})

        except Exception as e:
            self.warnings.append({"component": "search_quality", "message": f"Synthetic monitoring error: {e}"})

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
    health_emoji = {"healthy": "🟢", "warning": "🟡", "critical": "🔴"}

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
            lines.append(
                f"  [{severity}] {issue.get('component', '?')}: {issue.get('message', '')}"
            )

    if report.get("warnings"):
        lines.append("")
        lines.append(f"⚠️ Предупреждения ({report['warnings_count']}):")
        for warn in report["warnings"]:
            msg = warn.get("message", "")
            lines.append(f"  [{warn.get('component', '?')}] {msg}")

    if not report.get("issues") and not report.get("warnings"):
        lines.append("")
        lines.append("✅ Всё в порядке. Проблем не обнаружено.")

    # Execution Contract section
    metrics = report.get("metrics", {})
    if metrics.get("last_commit") or metrics.get("git_synced") is not None:
        lines.append("")
        lines.append("🔒 Execution Contract:")
        if metrics.get("last_commit"):
            lines.append(f"  • Last commit: {metrics['last_commit']}")
        if metrics.get("git_synced") is not None:
            sync_status = "✅ Synced" if metrics["git_synced"] else "⚠️ Ahead of remote"
            lines.append(f"  • Git: {sync_status}")
        if metrics.get("git_dirty_files", 0) > 0:
            lines.append(f"  • Dirty files: {metrics['git_dirty_files']}")

    # Search Quality section
    if metrics.get("search_quality_total_tests") is not None:
        lines.append("")
        lines.append("🔍 Search Quality (Synthetic Monitoring):")
        passed = metrics.get("search_quality_passed", 0)
        total = metrics.get("search_quality_total_tests", 0)
        quality_emoji = "✅" if passed == total else "⚠️" if passed > 0 else "❌"
        lines.append(f"  {quality_emoji} Tests passed: {passed}/{total}")

    lines.append("")
    lines.append("=" * 50)

    return "\n".join(lines)
