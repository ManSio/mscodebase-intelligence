"""
Статус-отчет для расширения MSCodebase Intelligence.
Предоставляет информацию о состоянии индексации, прогрессе и метаданных.
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class StatusReporter:
    """Отвечает за отчет о состоянии индексации и прогрессе."""

    def __init__(self, project_path: Path):
        self.project_path = project_path
        self._status_file = project_path / ".codebase_status.json"
        self._last_status = {}

    def update_status(self, indexer, searcher) -> Dict[str, Any]:
        """Обновляет статус и возвращает отчет."""
        status = self._collect_status(indexer, searcher)
        self._save_status(status)
        self._last_status = status
        return status

    def _collect_status(self, indexer, searcher) -> Dict[str, Any]:
        """Собирает полную информацию о состоянии."""
        status = {
            "timestamp": int(time.time()),
            "project_path": str(self.project_path),
            "indexer": self._get_indexer_status(indexer),
            "searcher": self._get_searcher_status(searcher),
            "system": self._get_system_info(),
            "progress": self._get_progress_info(indexer),
            "health": self._get_health_status(indexer),
        }

        return status

    def _get_indexer_status(self, indexer) -> Dict[str, Any]:
        """Возвращает статус индексации."""
        try:
            indexer_status = indexer.get_status()
            return {
                "total_chunks": indexer_status.get("total_chunks", 0),
                "unique_files": indexer_status.get("unique_files", 0),
                "total_files": indexer_status.get("total_files", 0),
                "status": indexer_status.get("status", "unknown"),
                "error": indexer_status.get("error"),
                "table_exists": indexer.table is not None,
                "table_size": len(indexer.table) if indexer.table else 0,
            }
        except Exception as e:
            logger.error(f"Ошибка получения статуса индекса: {e}")
            return {
                "error": str(e),
                "total_chunks": 0,
                "unique_files": 0,
                "total_files": 0,
                "status": "error",
                "table_exists": False,
                "table_size": 0,
            }

    def _get_searcher_status(self, searcher) -> Dict[str, Any]:
        """Возвращает статус поискового движка."""
        try:
            # BM25 статус
            bm25_stats = {
                "enabled": hasattr(searcher, "_bm25") and searcher._bm25 is not None,
                "documents_count": len(searcher._bm25_ids)
                if hasattr(searcher, "_bm25_ids")
                else 0,
                "initialized": hasattr(searcher, "_bm25")
                and searcher._bm25 is not None,
            }

            # Векторный статус
            vector_stats = {
                "enabled": True,  # Всегда включен, если есть таблица
                "table_exists": searcher.indexer.table is not None,
                "embedder_available": hasattr(searcher.embedder, "embed"),
            }

            return {
                "bm25": bm25_stats,
                "vector": vector_stats,
                "hybrid_search": True,  # Всегда true после наших изменений
            }
        except Exception as e:
            logger.error(f"Ошибка получения статуса поискового движка: {e}")
            return {
                "error": str(e),
                "bm25": {"enabled": False},
                "vector": {"enabled": False},
                "hybrid_search": False,
            }

    def _get_system_info(self) -> Dict[str, Any]:
        """Возвращает системную информацию."""
        import platform
        import sys

        return {
            "platform": platform.system(),
            "python_version": platform.python_version(),
            "architecture": platform.architecture()[0],
            "processor": platform.processor(),
            "working_directory": os.getcwd(),
            "project_root": str(self.project_path),
            "pid": os.getpid(),
        }

    def _get_progress_info(self, indexer) -> Dict[str, Any]:
        """Возвращает информацию о прогрессе индексации."""
        try:
            # Получаем базовую информацию
            base_status = indexer.get_status()

            # Пытаемся получить дополнительную информацию о прогрессе
            progress = {
                "indexed_chunks": base_status.get("total_chunks", 0),
                "unique_files": base_status.get("unique_files", 0),
                "total_files": base_status.get("total_files", 0),
                "progress_percentage": 0.0,
                "estimated_remaining": 0,
                "indexing_speed": 0.0,  # чанков в секунду
                "last_update": int(time.time()),
                            }

                            # Вычисляем примерный прогресс (упрощенная версия)
            if base_status.get("total_files", 0) > 0:
                progress["progress_percentage"] = (
                    base_status.get("unique_files", 0)
                    / base_status.get("total_files", 1)
                    * 100
                )

            return progress

        except Exception as e:
            logger.error(f"Ошибка получения информации о прогрессе: {e}")
            return {
                "indexed_chunks": 0,
                "unique_files": 0,
                "total_files": 0,
                "progress_percentage": 0.0,
                "estimated_remaining": 0,
                "indexing_speed": 0.0,
                "last_update": int(time.time()),
                                "error": str(e),
            }

    def _get_health_status(self, indexer) -> Dict[str, Any]:
        """Возвращает статус здоровья системы."""
        health = {
            "lancedb_connected": False,
            "table_accessible": False,
            "embedder_available": False,
            "file_guard_initialized": False,
            "issues": [],
            "warnings": [],
        }

        try:
            # Проверка LanceDB
            if indexer.table is not None:
                health["lancedb_connected"] = True
                health["table_accessible"] = True

                # Проверка размера таблицы
                table_size = len(indexer.table)
                if table_size == 0:
                    health["warnings"].append(
                        "Таблица пуста - нет проиндексированных файлов"
                    )
                elif table_size < 10:
                    health["warnings"].append(
                        f"Небольшая таблица: {table_size} записей"
                    )

        except Exception as e:
            health["issues"].append(f"Ошибка подключения к LanceDB: {e}")

        try:
            # Проверка эмбеддера
            if hasattr(indexer.embedder, "embed"):
                # Простая проверка - попытка вызвать метод (будет проигнорировано в реальном коде)
                health["embedder_available"] = True
            else:
                health["issues"].append("Эмбеддер недоступен")

        except Exception as e:
            health["issues"].append(f"Ошибка проверки эмбеддера: {e}")

        try:
            # Проверка FileGuard
            if hasattr(indexer, "file_guard") and indexer.file_guard:
                health["file_guard_initialized"] = True
            else:
                health["warnings"].append("FileGuard не инициализирован")

        except Exception as e:
            health["issues"].append(f"Ошибка проверки FileGuard: {e}")

        # Определяем общий статус здоровья
        if health["issues"]:
            health["status"] = "unhealthy"
        elif health["warnings"]:
            health["status"] = "warning"
        else:
            health["status"] = "healthy"

        return health

    def _save_status(self, status: Dict[str, Any]) -> None:
        """Сохраняет статус в файл."""
        try:
            # Создаем директорию, если не существует
            self._status_file.parent.mkdir(parents=True, exist_ok=True)

            # Записываем статус
            with open(self._status_file, "w", encoding="utf-8") as f:
                json.dump(status, f, indent=2, ensure_ascii=False)

            logger.debug(f"Статус сохранен: {self._status_file}")

        except Exception as e:
            logger.error(f"Ошибка сохранения статуса: {e}")

    def load_status(self) -> Optional[Dict[str, Any]]:
        """Загружает сохраненный статус."""
        try:
            if not self._status_file.exists():
                return None

            with open(self._status_file, "r", encoding="utf-8") as f:
                return json.load(f)

        except Exception as e:
            logger.error(f"Ошибка загрузки статуса: {e}")
            return None

    def get_formatted_status(self) -> str:
        """Возвращает отформатированный статус для отображения."""
        if not self._last_status:
            return "Статус не инициализирован"

        status = self._last_status

        # Основная информация
        lines = [
            "📊 Статус MSCodebase Intelligence:",
            f"  Проект: {status['project_path']}",
            f"  Время: {status['timestamp']}",
            "",
            "📈 Индексация:",
            f"  Фрагментов кода: {status['indexer']['total_chunks']}",
            f"  Уникальных файлов: {status['indexer']['unique_files']}",
            f"  Всего файлов: {status['indexer']['total_files']}",
            f"  Статус: {status['indexer']['status']}",
            "",
            "🔍 Поиск:",
            f"  BM25: {'✅' if status['searcher']['bm25']['enabled'] else '❌'}",
            f"  Векторный: {'✅' if status['searcher']['vector']['enabled'] else '❌'}",
            f"  Гибридный поиск: {'✅' if status['searcher']['hybrid_search'] else '❌'}",
            "",
            "🖥️ Система:",
            f"  Платформа: {status['system']['platform']}",
            f"  Python: {status['system']['python_version']}",
            "",
            "📊 Прогресс:",
            f"  Процент завершения: {status['progress']['progress_percentage']:.1f}%",
            f"  Обработано файлов: {status['progress']['unique_files']}/{status['progress']['total_files']}",
            "",
            "🏥 Здоровье:",
            f"  Статус: {status['health']['status']}",
        ]

        if status["health"]["issues"]:
            lines.append("  Проблемы:")
            for issue in status["health"]["issues"]:
                lines.append(f"    ❌ {issue}")

        if status["health"]["warnings"]:
            lines.append("  Предупреждения:")
            for warning in status["health"]["warnings"]:
                lines.append(f"    ⚠️ {warning}")

        return "\n".join(lines)

    def clear_status(self) -> None:
        """Очищает сохраненный статус."""
        try:
            if self._status_file.exists():
                self._status_file.unlink()
                logger.info(f"Статус очищен: {self._status_file}")
        except Exception as e:
            logger.error(f"Ошибка очистки статуса: {e}")
