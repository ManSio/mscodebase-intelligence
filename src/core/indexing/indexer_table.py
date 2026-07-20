"""
MSCodebase Intelligence — Indexer LanceDB Table Management Mixin

Содержит все методы Indexer, относящиеся к управлению таблицей LanceDB:
создание, миграция, удаление записей, векторный поиск.
"""

import logging
from typing import Set

__all__ = [
    "IndexerTableMixin",
]
logger = logging.getLogger("mscodebase_server.indexer")


class IndexerTableMixin:
    """Mixin for Indexer: управление таблицей LanceDB.

    Все методы работают через self.table, self.db, self.schema и другие
    атрибуты, определённые в Indexer.__init__().
    """

    # ──────────────────────────────────────────────
    # Escape / экранирование для SQL-like where
    # ──────────────────────────────────────────────

    def _escape_file_path_for_lance(self, file_path: str) -> str:
        """Экранирует file_path для безопасного использования в where/delete запросах LanceDB.
        LanceDB не поддерживает параметризованные запросы, поэтому экранируем вручную.
        """
        # Экранируем одинарные кавычки (удвоением) и обратные слеши
        escaped = file_path.replace("'", "''")
        return escaped

    # ──────────────────────────────────────────────
    # Миграция схемы
    # ──────────────────────────────────────────────

    def _migrate_text_full_inplace(self) -> None:
        """Мигрирует text_full без drop_table (см. INC-53EC / REFC-07).

        Стратегия:
        1. Добавляем колонку через add_columns (если API доступно).
        2. На следующих вызовах _index_single_file text_full будет
           перезаписан при чанковании. Для старых записей оставляем
           копию text (медленно, но безопасно).
        """
        try:
            # LanceDB >= 0.5 поддерживает add_columns.
            if hasattr(self.table, "add_columns"):
                # Дефолтное значение — пустая строка. Заполним lazy
                # при следующем переиндексе.
                try:
                    self.table.add_columns({"text_full": ""})
                except TypeError:
                    # Старая сигнатура add_columns без value
                    self.table.add_columns({"text_full": "string"})
                logger.info("📦 add_columns(text_full) выполнен")
            else:
                logger.warning(
                    "add_columns недоступен — text_full будет заполняться "
                    "по мере переиндексации (без потери данных)."
                )
        except Exception as e:
            logger.warning(f"_migrate_text_full_inplace: {e}")

    def _migrate_add_metadata_columns(self, existing_fields: list) -> None:
        """Мигрирует Metadata Enrichment колонки (v2.4.3+).

        Пытается добавить поля layer, module_name, hierarchy_level, is_public,
        symbol_type, parent_id, callees, health_score, health_band
        в существующую таблицу.
        Использует три стратегии:
        1. add_columns — быстрая миграция без чтения данных.
           Работает в LanceDB < 0.30. На 0.33+ падает с SQL parser error
           из-за неэкранирования строковых значений по умолчанию.
        2. read-drop-recreate — если add_columns не сработал,
           пересоздаёт таблицу с полной схемой.
        3. _safe_recreate_table — если to_pandas() тоже упал (таблица
           повреждена), создаёт пустую таблицу с полной схемой.
        """
        # Проверяем, каких колонок не хватает
        string_columns = [
            "layer",
            "module_name",
            "hierarchy_level",
            "symbol_type",
            "parent_id",
            "callees",
            "health_band",
            "chunk_hash",
        ]
        bool_columns = ["is_public"]
        float_columns = ["health_score"]
        int_columns = ["start_line", "end_line"]
        missing = [
            c
            for c in string_columns + bool_columns + float_columns + int_columns
            if c not in existing_fields
        ]
        if not missing:
            return  # Все колонки уже есть

        logger.info(
            f"📦 Миграция metadata: не хватает {len(missing)} колонок: {missing}"
        )

        # Стратегия 1: add_columns (для LanceDB < 0.33)
        # В LanceDB 0.34+ add_columns принимает pa.field, не строку и не {name: type}.
        import pyarrow as pa
        if hasattr(self.table, "add_columns"):
            all_ok = True
            for col in string_columns:
                if col not in existing_fields:
                    try:
                        self.table.add_columns(pa.field(col, pa.string()))
                        logger.info(f"📦 Миграция: добавлена колонка {col}")
                    except Exception as e:
                        logger.debug(f"add_columns({col}) не сработал: {e}")
                        all_ok = False
                        break
            if all_ok and "is_public" not in existing_fields:
                try:
                    self.table.add_columns(pa.field("is_public", pa.bool_()))
                    logger.info("📦 Миграция: добавлена колонка is_public")
                except Exception as e:
                    logger.debug(f"add_columns(is_public) не сработал: {e}")
                    all_ok = False
            if all_ok and "health_score" not in existing_fields:
                try:
                    self.table.add_columns(pa.field("health_score", pa.float64()))
                    logger.info("📦 Миграция: добавлена колонка health_score")
                except Exception as e:
                    logger.debug(f"add_columns(health_score) не сработал: {e}")
                    all_ok = False
            # start_line/end_line: используем SQL-выражения (LanceDB 0.34+)
            for col in int_columns:
                if col not in existing_fields:
                    try:
                        self.table.add_columns({col: f"CAST(0 AS INT)"})
                        logger.info(f"📦 Миграция: добавлена колонка {col}")
                    except Exception as e:
                        logger.debug(f"add_columns({col}) не сработал: {e}")
                        all_ok = False
                        break
            if all_ok:
                logger.info("📦 Миграция metadata через add_columns завершена")
                return

        # Стратегия 2: read-drop-recreate (надёжно для всех версий LanceDB)
        logger.info("📦 Миграция metadata: читаем существующие данные...")
        try:
            try:
                old_df = self.table.to_pandas()
            except Exception as pandas_err:
                # Таблица может быть повреждена (сброшена внешним скриптом)
                logger.warning(
                    f"📦 to_pandas() не доступен ({pandas_err}), создаём пустую таблицу"
                )
                self._safe_recreate_table()
                return

            logger.info(f"📦 Миграция: прочитано {len(old_df)} чанков")

            # Восстанавливаем отсутствующие поля с пустыми значениями
            for col in string_columns:
                if col not in old_df.columns:
                    old_df[col] = ""
            if "is_public" not in old_df.columns:
                old_df["is_public"] = False
            if "health_score" not in old_df.columns:
                old_df["health_score"] = 0.0
            for col in int_columns:
                if col not in old_df.columns:
                    old_df[col] = 0

            # chunk_hash: вычисляем из text (content-addressed),
            # чтобы cache заработал на существующем индексе без полной переиндексации
            import hashlib

            def _calc_chunk_hash(t: str) -> str:
                return "ch:" + hashlib.sha256(str(t).encode("utf-8")).hexdigest()[:32]

            if "chunk_hash" not in old_df.columns:
                old_df["chunk_hash"] = old_df["text"].apply(_calc_chunk_hash)
            else:
                # Заполняем пустые значения (на случай частичной миграции)
                old_df["chunk_hash"] = old_df["chunk_hash"].apply(
                    lambda v: _calc_chunk_hash(old_df["text"]) if not v else v
                )

            # Пересоздаём таблицу с полной схемой
            self.db.drop_table(self.table_name)
            self.table = self.db.create_table(self.table_name, schema=self.schema)

            # Конвертируем DataFrame в список словарей
            records = []
            for _, row in old_df.iterrows():
                record = {
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
                    "layer": str(row.get("layer", "")),
                    "module_name": str(row.get("module_name", "")),
                    "hierarchy_level": str(row.get("hierarchy_level", "")),
                    "is_public": bool(row.get("is_public", False)),
                    "symbol_type": str(row.get("symbol_type", "")),
                    "parent_id": str(row.get("parent_id", "")),
                    "callees": str(row.get("callees", "")),
                    "health_score": float(row.get("health_score", 0.0)),
                    "health_band": str(row.get("health_band", "")),
                    "chunk_hash": str(row.get("chunk_hash", "")),
                }
                records.append(record)

            self.table.add(records)
            logger.info(
                f"📦 Миграция metadata завершена: {len(records)} чанков пересозданы с полной схемой"
            )
        except Exception as e:
            logger.error(
                f"❌ Миграция metadata провалилась: {e}. "
                f"Метаданные появятся после полной переиндексации."
            )

    # ──────────────────────────────────────────────
    # Управление таблицей (create / recreate / check)
    # ──────────────────────────────────────────────

    def _safe_recreate_table(self) -> bool:
        """Безопасно пересоздаёт таблицу с полной схемой.

        Используется когда таблица повреждена, сброшена извне или
        migration не удался. Сбрасывает кэши и обновляет self.table.

        Returns:
            True если таблица создана, False при ошибке.
        """
        try:
            # Пытаемся удалить таблицу если существует
            try:
                self.db.drop_table(self.table_name)
            except Exception:
                pass
            # Создаём новую таблицу с полной схемой
            self.table = self.db.create_table(self.table_name, schema=self.schema)

            # Сбрасываем кэши (таблица пуста)
            self._cached_total_chunks = 0
            self._cached_unique_files = set()

            # Сбрасываем async-кэш (будет пересоздан лениво)
            self._async_table = None

            # Сбрасываем BM25-индекс Searcher-а (будет перестроен лениво)
            if hasattr(self, "searcher") and self.searcher is not None:
                try:
                    self.searcher.reindex()
                except Exception:
                    pass
            logger.info(f"📦 Таблица {self.table_name} пересоздана с полной схемой")
            return True
        except Exception as e:
            logger.error(f"❌ Не удалось пересоздать таблицу: {e}")
            return False

    def _ensure_table_ready(self) -> bool:
        """Проверяет, что таблица существует и доступна для записи.

        Если таблица была сброшена извне или повреждена — пересоздаёт её.
        Безопасно вызывает count_rows() для проверки.

        Returns:
            True если таблица готова, False если не удалось восстановить.
        """
        if self.table is None:
            return self._safe_recreate_table()

        try:
            # Быстрая проверка: count_rows не читает данные, только metadata
            self.table.count_rows()
            return True
        except Exception as e:
            err_str = str(e).lower()
            if (
                "not found" in err_str
                or "does not exist" in err_str
                or "no such table" in err_str
            ):
                logger.warning(f"⚠️ Таблица не найдена ({e}), пересоздаём...")
                return self._safe_recreate_table()
            if "corrupt" in err_str or "io error" in err_str:
                logger.warning(f"⚠️ Таблица повреждена ({e}), пересоздаём...")
                return self._safe_recreate_table()
            # Другая ошибка — логируем, но не трогаем таблицу
            logger.debug(f"_ensure_table_ready: {e}")
            return True

    # ──────────────────────────────────────────────
    # Удаление записей из таблицы
    # ──────────────────────────────────────────────

    def _safe_read_arrow(self, max_retries: int = 1):
        """Безопасное чтение таблицы в Arrow с self-healing при 'Not found'.

        Defense-in-depth (Слой 2): если таблица повреждена (битый manifest
        после rmtree/частичного удаления БД), ловим LanceError/Not found,
        вызываем reset_connection() (обновляет self.table) и повторяем.

        Returns:
            pyarrow.Table или None если восстановить не удалось.
        """
        for attempt in range(max_retries + 1):
            try:
                if self.table is None:
                    if not self._safe_recreate_table():
                        return None
                return self.table.to_arrow()
            except Exception as e:
                err_str = str(e).lower()
                if ("not found" in err_str or "lanceerror" in err_str
                        or "does not exist" in err_str or "no such" in err_str):
                    logger.warning(
                        f"_safe_read_arrow: таблица повреждена ({e}), "
                        f"reset_connection (попытка {attempt+1})"
                    )
                    try:
                        if hasattr(self, "db_manager") and self.db_manager is not None:
                            self.db_manager.reset_connection()
                            self.table = self.db_manager.table
                        else:
                            self._safe_recreate_table()
                    except Exception as _rc_err:
                        logger.error(f"_safe_read_arrow: reset не удался: {_rc_err}")
                        return None
                    continue  # retry с обновлённой self.table
                else:
                    # Не LanceError — пробрасываем как None (вызывающий решит)
                    logger.debug(f"_safe_read_arrow: не-Lance ошибка: {e}")
                    return None
        return None

    def prune_deleted_files(self, active_files_on_disk: Set[str]) -> int:
        """Удаляет из базы данных файлы, которых больше нет на физическом диске.

        Args:
            active_files_on_disk: Полный набор файлов на диске (не только удалённые!).

        Returns:
            Количество удалённых файлов.

        Warning:
            НЕ вызывайте эту функцию с одним элементом — это удалит все
            остальные файлы из базы! Используйте delete_file() для одиночного удаления.
        """
        if self._cached_total_chunks == 0:
            return 0
        if not active_files_on_disk:
            logger.warning(
                "⚠️ prune_deleted_files вызван с пустым набором файлов. Пропуск."
            )
            return 0

        try:
            # Arrow-native: в 5-10x быстрее и в 3x меньше RAM чем to_pandas
            import pyarrow.compute as pc

            tbl = self._safe_read_arrow()
            if tbl is None:
                # Таблица повреждена/недоступна — reset_connection уже сделан
                # в _safe_read_arrow. Пропускаем prune, чтобы не усугублять.
                logger.warning("Pruning пропущен: таблица недоступна после reset")
                return 0
            files_in_db = pc.unique(tbl["file_path"]).to_pylist()
            deleted_files = set(files_in_db) - active_files_on_disk

            if deleted_files:
                # Safety ratio: не удалять >50% индекса за раз — это значит
                # что active_files_on_disk неполный (прерванная индексация).
                total_files_in_db = len(files_in_db)
                delete_ratio = len(deleted_files) / max(total_files_in_db, 1)
                if delete_ratio > 0.5:
                    logger.warning(
                        f"⚠️ Safety guard: prune_deleted_files хочет удалить "
                        f"{len(deleted_files)}/{total_files_in_db} файлов "
                        f"({delete_ratio:.0%}). Пропуск — active_files_on_disk неполный."
                    )
                    return 0

                logger.info(
                    "🧹 Обнаружены удаленные файлы. Начинается чистка базы от мёртвого груза..."
                )
                total_deleted_chunks = 0
                for file_path in deleted_files:
                    escaped = self._escape_file_path_for_lance(file_path)

                    # Подсчёт чанков из Arrow-таблицы (без to_pandas)
                    fp_mask = pc.equal(tbl["file_path"], file_path)
                    file_chunks = int(pc.sum(fp_mask).as_py() or 0)
                    total_deleted_chunks += file_chunks

                    try:
                        self.table.delete(f"file_path = '{escaped}'")
                    except Exception as _del_err:
                        err_str = str(_del_err).lower()
                        if "not found" in err_str or "lanceerror" in err_str:
                            # Таблица сменилась под ногами — обновляем и retry
                            if hasattr(self, "db_manager") and self.db_manager is not None:
                                self.db_manager.reset_connection()
                                self.table = self.db_manager.table
                            try:
                                self.table.delete(f"file_path = '{escaped}'")
                            except Exception as _del_err2:
                                logger.warning(f"Prune delete retry failed: {_del_err2}")
                        else:
                            logger.warning(f"Prune delete error: {_del_err}")

                    # Очистка PropertyGraph
                    if hasattr(self._symbol_index, "graph"):
                        pg = self._symbol_index.graph
                        if pg:
                            rel_posix = file_path.replace("\\", "/")
                            deleted_nodes = pg.remove_file(rel_posix)
                            if deleted_nodes:
                                logger.info(
                                    f"  └─ Изъято из PropertyGraph: {deleted_nodes} узлов"
                                )

                    logger.info(f"  └─ Изъят из индекса: {file_path}")

                # Синхронизация кэша: декремент на количество удалённых чанков
                if total_deleted_chunks > 0:
                    self._cached_total_chunks = max(
                        0, self._cached_total_chunks - total_deleted_chunks
                    )
                for fp in deleted_files:
                    self._cached_unique_files.discard(fp)

                # Compaction: оптимизация хранения после удаления данных
                # LanceDB накапливает stale версии, compaction освобождает место
                if total_deleted_chunks > 50:
                    try:
                        import gc

                        gc.collect()  # Принудительная сборка перед compaction
                        logger.info(
                            f"🗜️ Compaction: {total_deleted_chunks} чанков удалено, "
                            f"запускаю оптимизацию..."
                        )
                        self.table.compact_files()
                        logger.info("✅ Compaction завершён")
                    except Exception as compact_err:
                        logger.debug(f"Compaction не удался: {compact_err}")

                logger.info("✅ База данных полностью синхронизирована с диском.")
                return len(deleted_files)
            return 0
        except Exception as e:
            logger.error(f"Ошибка при выполнении операции Pruning: {e}")
            return 0

    def delete_file(self, rel_path_str: str) -> bool:
        """Удаляет один файл из базы по относительному пути. Безопасно для одиночного удаления."""
        try:
            escaped = self._escape_file_path_for_lance(rel_path_str)

            # Подсчёт количества удаляемых чанков для корректного декремента кэша
            deleted_count = 0
            try:
                df_all = self.table.to_pandas()
                if not df_all.empty:
                    deleted_count = int((df_all["file_path"] == rel_path_str).sum())
            except Exception:
                pass
            self.table.delete(f"file_path = '{escaped}'")

            # Синхронизация кэша: декремент на количество удалённых чанков
            if deleted_count > 0:
                self._cached_total_chunks = max(
                    0, self._cached_total_chunks - deleted_count
                )
            self._cached_unique_files.discard(rel_path_str)

            logger.info(f"🗑️ Удалён файл: {rel_path_str}")
            return True
        except Exception as e:
            logger.debug(f"delete_file() не нашёл запись {rel_path_str}: {e}")
            return False

    async def search_async(
        self,
        query_vector: list,
        limit: int = 5,
        filter_expr: str = "",
    ) -> list:
        """Асинхронный векторный поиск через AsyncTable.

        В LanceDB >= 0.33 AsyncTable.search() возвращает coroutine →
        await даёт AsyncVectorQuery builder; builder.where() синхронен,
        builder.limit() синхронен, to_pandas() асинхронен.

        Args:
            query_vector: Вектор запроса.
            limit: Максимальное число результатов.
            filter_expr: SQL-выражение (например, "layer = 'core'").

        Returns:
            Список dict-ов с полями text, text_full, metadata.
        """
        table = await self._ensure_async_table()
        if table is None:
            return []

        try:
            builder = await table.search(query_vector, vector_column_name="vector")
            if filter_expr:
                builder = builder.where(filter_expr)
            df = await builder.limit(limit).to_pandas()

            results = []
            for _, row in df.iterrows():
                results.append(
                    {
                        "text": row["text"],
                        "text_full": row.get("text_full", row["text"]),
                        "metadata": {
                            "file": row["file_path"],
                            "chunk_index": row["chunk_index"],
                            "indexed_at": row.get("indexed_at", ""),
                            "layer": row.get("layer", ""),
                            "hierarchy_level": row.get("hierarchy_level", ""),
                            "parent_id": row.get("parent_id", ""),
                        },
                        "vector": row.get("vector"),  # v3.2.1: для MMR
                    }
                )
            return results
        except Exception as e:
            logger.error(f"Ошибка async векторного поиска LanceDB: {e}")
            return []
