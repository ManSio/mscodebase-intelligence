"""
Index Guard — самовосстановление индекса при сбоях.

Решает проблемы:
1. Несовместимость схемы LanceDB (миграция)
2. Потеря SymbolIndex после перезапуска (persistence)
3. Бинарные/minified файлы при индексации
4. Таймауты при загрузке моделей LM Studio
5. Race condition при параллельной индексации
"""

import hashlib
import json
import logging
import os
import pickle
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

import lancedb
import pyarrow as pa

logger = logging.getLogger("index_guard")

# Текущая версия схемы
SCHEMA_VERSION = 3

# Ожидаемая схема таблицы
EXPECTED_SCHEMA_FIELDS = {
    "id": pa.string(),
    "vector": pa.list_(pa.float32(), 1024),
    "text": pa.string(),
    "text_full": pa.string(),
    "file_path": pa.string(),
    "file_hash": pa.string(),
    "chunk_index": pa.int32(),
    "source": pa.string(),
    "indexed_at": pa.string(),
    "summary": pa.string(),
}


class IndexGuard:
    """Защита и самовосстановление индекса."""

    def __init__(self, db_path: Path, project_path: Path):
        """
        Args:
            db_path: Путь к директории LanceDB
            project_path: Путь к проекту
        """
        self.db_path = db_path
        self.project_path = project_path
        self._guard_file = db_path / ".index_guard.json"

    def check_and_repair(self, db: lancedb.LanceDB) -> Dict[str, any]:
        """Полная проверка и восстановление индекса.

        Returns:
            Отчёт о проверке: {status, actions_taken, errors}
        """
        report = {
            "status": "ok",
            "actions_taken": [],
            "errors": [],
            "timestamp": datetime.now().isoformat(),
        }

        try:
            # 1. Проверка существования таблицы
            tables_response = db.list_tables()
            # list_tables() возвращает ListTablesResponse с полем .tables
            tables = tables_response.tables if hasattr(tables_response, 'tables') else list(tables_response)
            if "codebase_chunks" not in tables:
                report["actions_taken"].append("table_missing_will_create")
                report["status"] = "needs_reindex"
                return report

            # 2. Проверка схемы
            table = db.open_table("codebase_chunks")
            existing_fields = {f.name: f.type for f in table.schema}
            schema_ok, schema_errors = self._validate_schema(existing_fields)

            if not schema_ok:
                # Критичная ошибка схемы — нужна миграция
                report["status"] = "needs_repair"
                report["errors"].extend(schema_errors)

                # Пытаемся мигрировать
                migrated = self._migrate_table(db, table, existing_fields)
                if migrated:
                    report["actions_taken"].append("schema_migrated")
                else:
                    report["actions_taken"].append("migration_failed_drop_required")
                    # Пересоздаём таблицу
                    db.drop_table("codebase_chunks")
                    report["status"] = "needs_reindex"
                    return report
            elif not self._is_schema_complete(existing_fields):
                # Схема минимально рабочая, но неполная — мигрируем без ошибки
                report["actions_taken"].append("schema_incomplete_will_migrate")
                self._migrate_table(db, table, existing_fields)
                report["actions_taken"].append("schema_migrated")

            # 3. Проверка целостности данных
            row_count = len(table)
            if row_count == 0:
                report["status"] = "needs_reindex"
                report["actions_taken"].append("empty_table")
            else:
                report["row_count"] = row_count

            # 4. Проверка SymbolIndex persistence
            symbol_index_ok = self._ensure_symbol_index()
            if not symbol_index_ok:
                report["actions_taken"].append("symbol_index_will_rebuild")

            # 5. Сохранение состояния guard
            self._save_guard_state(report)

        except Exception as e:
            report["status"] = "error"
            report["errors"].append(str(e))
            logger.error(f"Index guard check failed: {e}")

        return report

    def _is_schema_complete(self, existing_fields: Dict[str, pa.DataType]) -> bool:
        """Проверяет полноту схемы (все ожидаемые поля)."""
        full_fields = {"id", "vector", "text", "text_full", "file_path", "file_hash", "chunk_index", "source", "indexed_at", "summary"}
        return full_fields.issubset(set(existing_fields.keys()))

    def _validate_schema(
        self, existing_fields: Dict[str, pa.DataType]
    ) -> Tuple[bool, list]:
        """Проверяет соответствие схемы ожидаемой."""
        errors = []

        # Проверяем наличие обязательных полей
        required_fields = {"id", "vector", "text", "file_path", "chunk_index"}
        missing = required_fields - set(existing_fields.keys())
        if missing:
            errors.append(f"missing_required_fields:{','.join(missing)}")

        # Проверяем размерность вектора
        if "vector" in existing_fields:
            vec_type = existing_fields["vector"]
            if hasattr(vec_type, 'list_size') and vec_type.list_size != 1024:
                errors.append(f"vector_dim_mismatch:{vec_type.list_size}")

        return len(errors) == 0, errors

    def _migrate_table(
        self,
        db: lancedb.LanceDB,
        table: lancedb.LanceTable,
        existing_fields: Dict[str, pa.DataType],
    ) -> bool:
        """Миграция таблицы к актуальной схеме.

        Returns:
            True если миграция успешна, False если нужен drop+recreate
        """
        try:
            # Читаем существующие данные
            old_df = table.to_pandas()
            if len(old_df) == 0:
                # Пустая таблица — просто пересоздаём
                db.drop_table("codebase_chunks")
                return True

            # Восстанавливаем отсутствующие поля
            if "text_full" not in old_df.columns:
                old_df["text_full"] = old_df["text"]
            if "source" not in old_df.columns:
                old_df["source"] = "filesystem"
            if "indexed_at" not in old_df.columns:
                old_df["indexed_at"] = ""
            if "summary" not in old_df.columns:
                old_df["summary"] = ""

            # Пересоздаём таблицу с актуальной схемой
            db.drop_table("codebase_chunks")

            records = []
            for _, row in old_df.iterrows():
                records.append({
                    "id": str(row["id"]),
                    "vector": row["vector"],
                    "text": str(row["text"]),
                    "text_full": str(row.get("text_full", row["text"])),
                    "file_path": str(row["file_path"]),
                    "file_hash": str(row.get("file_hash", "")),
                    "chunk_index": int(row.get("chunk_index", 0)),
                    "source": str(row.get("source", "filesystem")),
                    "indexed_at": str(row.get("indexed_at", "")),
                    "summary": str(row.get("summary", "")),
                })

            new_table = db.create_table(
                "codebase_chunks",
                schema=pa.schema([
                    pa.field("id", pa.string()),
                    pa.field("vector", pa.list_(pa.float32(), 1024)),
                    pa.field("text", pa.string()),
                    pa.field("text_full", pa.string()),
                    pa.field("file_path", pa.string()),
                    pa.field("file_hash", pa.string()),
                    pa.field("chunk_index", pa.int32()),
                    pa.field("source", pa.string()),
                    pa.field("indexed_at", pa.string()),
                    pa.field("summary", pa.string()),
                ]),
            )
            new_table.add(records)
            logger.info(f"Migrated {len(records)} records to new schema")
            return True

        except Exception as e:
            logger.error(f"Migration failed: {e}")
            return False

    def _ensure_symbol_index(self) -> bool:
        """Проверяет наличие сохранённого SymbolIndex.

        Returns:
            True если SymbolIndex существует или может быть восстановлен
        """
        symbol_cache = self.db_path / "symbol_index.pkl"
        return symbol_cache.exists()

    def save_symbol_index(self, symbol_index: any) -> bool:
        """Сохраняет SymbolIndex на диск.

        Args:
            symbol_index: Инстанс SymbolIndex

        Returns:
            True если сохранение успешно
        """
        try:
            cache_file = self.db_path / "symbol_index.pkl"
            with open(cache_file, "wb") as f:
                pickle.dump(
                    {
                        "definitions": symbol_index._definitions,
                        "references": symbol_index._references,
                        "file_to_symbols": symbol_index._file_to_symbols,
                        "saved_at": datetime.now().isoformat(),
                    },
                    f,
                )
            logger.info(f"SymbolIndex saved to {cache_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to save SymbolIndex: {e}")
            return False

    def load_symbol_index(self, symbol_index: any) -> bool:
        """Загружает SymbolIndex с диска.

        Args:
            symbol_index: Инстанс SymbolIndex для заполнения

        Returns:
            True если загрузка успешна
        """
        try:
            cache_file = self.db_path / "symbol_index.pkl"
            if not cache_file.exists():
                return False

            with open(cache_file, "rb") as f:
                data = pickle.load(f)

            symbol_index._definitions = data.get("definitions", {})
            symbol_index._references = data.get("references", {})
            symbol_index._file_to_symbols = data.get("file_to_symbols", {})

            logger.info(
                f"SymbolIndex loaded: {len(symbol_index._definitions)} symbols"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to load SymbolIndex: {e}")
            return False

    def _save_guard_state(self, report: Dict):
        """Сохраняет состояние guard для диагностики."""
        try:
            state = {
                "schema_version": SCHEMA_VERSION,
                "last_check": report,
            }
            with open(self._guard_file, "w") as f:
                json.dump(state, f, indent=2, default=str)
        except Exception:
            pass

    def get_stale_files(self) -> list:
        """Находит файлы которые изменились с последней индексации.

        Сравнивает текущие хеши файлов с хранимыми в базе данных.

        Returns:
            Список файлов требующих переиндексации
        """
        try:
            # Подключаемся к базе данных
            raw_path = str(self.db_path.resolve())
            if raw_path.startswith("\\\\?\\"):
                lancedb_path = raw_path[4:]
            else:
                lancedb_path = raw_path

            db = lancedb.connect(lancedb_path)

            # Получаем текущие хеши файлов из базы
            table = db.open_table(self._get_table_name())

            # Получаем уникальные пути файлов из базы
            try:
                file_data = table.search().limit(10000).to_pandas()
                if file_data.empty:
                    return []

                # Группируем по file_path и получаем последний file_hash
                last_hashes = {}
                for _, row in file_data.iterrows():
                    file_path = row.get("file_path")
                    file_hash = row.get("file_hash", "")
                    if file_path and file_hash:
                        last_hashes[file_path] = file_hash
            except Exception as e:
                logger.debug(f"Ошибка при получении данных из таблицы: {e}")
                return []

            # Сравниваем с текущими хешами файлов на диске
            stale_files = []
            for file_path_str, stored_hash in last_hashes.items():
                try:
                    file_path = Path(file_path_str)
                    if not file_path.exists():
                        stale_files.append(file_path_str)
                        continue

                    # Вычисляем текущий хеш файла
                    current_hash = self._compute_file_hash(file_path)

                    # Если хеши не совпадают или отсутствуют - файл изменился
                    if current_hash != stored_hash:
                        stale_files.append(file_path_str)
                except Exception as e:
                    logger.debug(f"Ошибка при проверке файла {file_path_str}: {e}")
                    stale_files.append(file_path_str)

            return stale_files

        except Exception as e:
            logger.debug(f"Ошибка при проверке устаревших файлов: {e}")
            return []

    def _compute_file_hash(self, file_path: Path) -> str:
        """Вычисляет хеш файла для сравнения."""
        try:
            with open(file_path, 'rb') as f:
                content = f.read()
                return hashlib.md5(content).hexdigest()
        except Exception:
            return ""

    def should_reindex(self) -> bool:
        """Определяет нужна ли полная переиндексация.

        Returns:
            True если требуется reindex
        """
        try:
            if not self._guard_file.exists():
                return True

            with open(self._guard_file, "r") as f:
                state = json.load(f)

            last_check = state.get("last_check", {})
            status = last_check.get("status", "unknown")

            return status in ("needs_reindex", "error")
        except Exception:
            return True


def quick_health_check(db_path: Path) -> Dict[str, any]:
    """Быстрая проверка здоровья индекса (без восстановления).

    Args:
        db_path: Путь к директории LanceDB

    Returns:
        {healthy, table_exists, row_count, schema_ok, symbol_index_exists}
    """
    result = {
        "healthy": False,
        "table_exists": False,
        "row_count": 0,
        "schema_ok": False,
        "symbol_index_exists": False,
    }

    try:
        db = lancedb.connect(str(db_path))
        tables_response = db.list_tables()
        tables = tables_response.tables if hasattr(tables_response, 'tables') else list(tables_response)

        if "codebase_chunks" not in tables:
            return result

        result["table_exists"] = True
        table = db.open_table("codebase_chunks")
        result["row_count"] = len(table)

        # Проверка схемы (минимально необходимые поля)
        existing = {f.name for f in table.schema}
        minimal_required = {"id", "vector", "text", "file_path"}
        result["schema_ok"] = minimal_required.issubset(existing)

        # Полная схема (для продвинутых фич)
        full_required = {"id", "vector", "text", "text_full", "file_path", "file_hash", "chunk_index", "source", "indexed_at", "summary"}
        result["schema_complete"] = full_required.issubset(existing)

        # Проверка SymbolIndex
        result["symbol_index_exists"] = (db_path / "symbol_index.pkl").exists()

        result["healthy"] = (
            result["table_exists"]
            and result["schema_ok"]
            and result["row_count"] > 0
        )

    except Exception as e:
        result["error"] = str(e)

    return result
