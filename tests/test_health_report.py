"""
Тесты для Health Report — самодиагностика системы.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core.health_report import HealthReport, format_health_report


class TestHealthReportBasic:
    """Базовые тесты HealthReport."""

    def test_empty_report(self):
        """Отчёт без данных."""
        with tempfile.TemporaryDirectory() as tmp:
            report = HealthReport(Path(tmp))
            result = report.run_full_diagnostic()

            assert result["overall_health"] in ("healthy", "warning", "critical")
            assert "timestamp" in result
            assert "metrics" in result
            assert "issues" in result
            assert "warnings" in result

    def test_healthy_system(self):
        """Здоровая система — нет проблем."""
        with tempfile.TemporaryDirectory() as tmp:
            report = HealthReport(Path(tmp))
            result = report.run_full_diagnostic()

            # Пустой проект без индексатора = warning (нет данных)
            assert result["overall_health"] in ("healthy", "warning")

    def test_format_report_healthy(self):
        """Форматирование здорового отчёта."""
        report_data = {
            "timestamp": "2026-06-28T23:00:00",
            "project": "/test",
            "overall_health": "healthy",
            "issues_count": 0,
            "warnings_count": 0,
            "metrics": {"total_chunks": 100, "unique_files": 10},
            "issues": [],
            "warnings": [],
        }
        formatted = format_health_report(report_data)
        assert "🟢" in formatted
        assert "HEALTHY" in formatted
        assert "Всё в порядке" in formatted

    def test_format_report_critical(self):
        """Форматирование критического отчёта."""
        report_data = {
            "timestamp": "2026-06-28T23:00:00",
            "project": "/test",
            "overall_health": "critical",
            "issues_count": 2,
            "warnings_count": 1,
            "metrics": {"total_chunks": 0},
            "issues": [
                {"component": "index", "severity": "critical", "message": "Индекс пуст"},
            ],
            "warnings": [
                {"component": "logs", "message": "Много ошибок"},
            ],
        }
        formatted = format_health_report(report_data)
        assert "🔴" in formatted
        assert "CRITICAL" in formatted
        assert "Индекс пуст" in formatted

    def test_format_report_warning(self):
        """Форматирование предупреждения."""
        report_data = {
            "timestamp": "2026-06-28T23:00:00",
            "project": "/test",
            "overall_health": "warning",
            "issues_count": 0,
            "warnings_count": 2,
            "metrics": {},
            "issues": [],
            "warnings": [
                {"component": "sync", "message": "Не проиндексировано: 5 файлов"},
            ],
        }
        formatted = format_health_report(report_data)
        assert "🟡" in formatted
        assert "WARNING" in formatted


class TestHealthReportWithIndexer:
    """Тесты с реальным индексатором."""

    def test_empty_index_detected(self):
        """Обнаружение пустого индекса."""
        mock_indexer = MagicMock()
        mock_indexer.get_status.return_value = {
            "total_chunks": 0,
            "unique_files": 0,
            "status": "active",
        }

        with tempfile.TemporaryDirectory() as tmp:
            report = HealthReport(Path(tmp), indexer=mock_indexer)
            result = report.run_full_diagnostic()

            assert result["overall_health"] == "critical"
            assert any("0 чанков" in i["message"] for i in result["issues"])

    def test_normal_index(self):
        """Нормальный индекс."""
        mock_indexer = MagicMock()
        mock_indexer.get_status.return_value = {
            "total_chunks": 500,
            "unique_files": 50,
            "status": "active",
        }

        with tempfile.TemporaryDirectory() as tmp:
            report = HealthReport(Path(tmp), indexer=mock_indexer)
            result = report.run_full_diagnostic()

            assert result["metrics"]["total_chunks"] == 500
            assert result["metrics"]["unique_files"] == 50

    def test_fallback_embedder_warning(self):
        """Предупреждение о fallback embedder."""
        mock_embedder = MagicMock()
        mock_embedder.mode = "fallback"

        with tempfile.TemporaryDirectory() as tmp:
            report = HealthReport(Path(tmp), embedder=mock_embedder)
            result = report.run_full_diagnostic()

            assert any("fallback" in i.get("message", "") for i in result["issues"])


class TestHealthReportLogs:
    """Тесты проверки логов."""

    def test_no_logs_directory(self):
        """Нет директории логов."""
        with tempfile.TemporaryDirectory() as tmp:
            report = HealthReport(Path(tmp))
            result = report.run_full_diagnostic()

            assert any("логов" in w["message"] for w in result["warnings"])

    def test_logs_with_errors(self):
        """Логи с ошибками."""
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp) / ".codebase_indices" / "logs"
            log_dir.mkdir(parents=True)
            log_file = log_dir / "test.log"
            log_file.write_text(
                "2026-06-28 ERROR Something failed\n"
                "2026-06-28 ERROR Another error\n"
                "2026-06-28 WARNING Warning message\n"
            )

            report = HealthReport(Path(tmp))
            result = report.run_full_diagnostic()

            assert result["metrics"].get("recent_errors", 0) >= 2


class TestHealthReportOrphanChunks:
    """Тесты обнаружения осиротевших чанков."""

    def test_orphan_files_detected(self):
        """Обнаружены осиротевшие файлы."""
        mock_indexer = MagicMock()
        mock_indexer.get_status.return_value = {
            "total_chunks": 10,
            "unique_files": 2,
            "status": "active",
        }

        # Мокаем table.to_pandas() для возврата данных
        mock_table = MagicMock()
        import pandas as pd
        mock_table.to_pandas.return_value = pd.DataFrame({
            "file_path": ["old_deleted.py", "existing.py", "old_deleted.py"],
            "text": ["code1", "code2", "code3"],
        })
        mock_indexer.table = mock_table

        with tempfile.TemporaryDirectory() as tmp:
            # Создаём только existing.py
            (Path(tmp) / "existing.py").write_text("code")

            report = HealthReport(Path(tmp), indexer=mock_indexer)
            result = report.run_full_diagnostic()

            # Должно быть предупреждение об осиротевших файлах
            orphan_warnings = [w for w in result["warnings"] if "Осиротевшие" in w.get("message", "")]
            assert len(orphan_warnings) >= 1


class TestHealthReportComponents:
    """Тесты проверки компонентов."""

    def test_symbol_index_zero_symbols(self):
        """0 символов при непустом индексе."""
        mock_indexer = MagicMock()
        mock_indexer.get_status.return_value = {
            "total_chunks": 100,
            "unique_files": 10,
            "status": "active",
        }
        mock_symbol_index = MagicMock()
        mock_symbol_index.get_symbol_count.return_value = 0

        with tempfile.TemporaryDirectory() as tmp:
            report = HealthReport(
                Path(tmp),
                indexer=mock_indexer,
                symbol_index=mock_symbol_index,
            )
            result = report.run_full_diagnostic()

            assert any("Символов 0" in w.get("message", "") for w in result["warnings"])

    def test_all_components_healthy(self):
        """Все компоненты здоровы."""
        mock_indexer = MagicMock()
        mock_indexer.get_status.return_value = {
            "total_chunks": 500,
            "unique_files": 50,
            "status": "active",
        }
        mock_symbol_index = MagicMock()
        mock_symbol_index.get_symbol_count.return_value = 200
        mock_embedder = MagicMock()
        mock_embedder.mode = "lm_studio"

        with tempfile.TemporaryDirectory() as tmp:
            report = HealthReport(
                Path(tmp),
                indexer=mock_indexer,
                symbol_index=mock_symbol_index,
                embedder=mock_embedder,
            )
            result = report.run_full_diagnostic()

            assert result["metrics"]["total_chunks"] == 500
            assert result["metrics"]["total_symbols"] == 200
            assert result["metrics"]["embedder_mode"] == "lm_studio"
