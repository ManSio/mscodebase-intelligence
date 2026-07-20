"""
MSCodebase Intelligence — Продакшен инкрементальный индекс на LanceDB с авто-очисткой (Pruning)
"""

import hashlib
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.core.indexing.chunk_summarizer import ChunkSummarizer
from src.core.indexing.indexer_table import IndexerTableMixin
from src.utils.paths import SafePathManager

__all__ = [
    "Indexer",
]
logger = logging.getLogger("mscodebase_server.indexer")

# Размер батча для кросс-файлового эмбеддинга.
# E5-base/BGE-M3 обрабатывают 64 текста почти за то же время, что и 1.
_BATCH_SIZE = 4       # Оптимум для small INT8: batch=4 даёт 52 ch/s (vs 25 при 64)


def _generate_unique_db_path(project_path: Path) -> Path:
    """Генерирует уникальный путь к базе данных на основе пути проекта.

    Это позволяет каждому проекту иметь свою изолированную базу данных,
    предотвращая конфликты при параллельной индексации.
    """
    # Используем хэш пути проекта для создания уникального имени файла
    # Нормализуем путь: lower() + replace('\', '/') для защиты от разного регистра в Windows
    normalized_path = str(project_path.resolve()).lower().replace("\\", "/")
    project_hash = hashlib.md5(normalized_path.encode()).hexdigest()[:8]
    project_name = os.path.basename(project_path).lower()

    # Создаем директорию .codebase_indices в корне проекта, если её нет
    # ВАЖНО: используем сам project_path, а не его parent — иначе БД создаётся
    # в родительской директории (D:\Project\.codebase_indices вместо D:\Project\MSCodeBase\.codebase_indices)
    project_root = project_path
    db_dir = project_root / ".codebase_indices" / "lancedb_v2"
    db_dir.mkdir(parents=True, exist_ok=True)

    # Имя базы данных: index_{project_name}_{hash}.db
    db_name = f"index_{project_name}_{project_hash}.db"
    return db_dir / db_name


class Indexer(IndexerTableMixin):
    def __init__(
        self,
        db_path: Path,
        embedder,
        file_guard,
        project_path: Optional[Path] = None,
        parser=None,
        enable_summaries: bool = True,
        symbol_index=None,
        notification_broker=None,
        searcher=None,
    ):
        self.db_path = db_path
        self.embedder = embedder
        self.file_guard = file_guard
        self.path_manager = SafePathManager(db_path.parent)
        self.searcher = searcher
        self.project_path = project_path or db_path.parent.parent.parent
        self.parser = parser
        self._notification_broker = notification_broker
        self._last_reported_progress = -1

        import threading
        self._index_lock = threading.Lock()
        self._table_write_lock = threading.Lock()
        self._symbol_index_lock = threading.Lock()

        # IndexParser — чистый парсер без БД и SymbolIndex
        from src.core.indexing.index_parser import IndexParser
        self._index_parser = IndexParser(
            parser=self.parser,
            path_manager=self.path_manager,
            project_path=self.project_path,
        )

        # Watchdog
        self._watchdog_heartbeat = time.time()
        self._watchdog_ever_beat = False
        self._watchdog_label = "idle"
        self._watchdog_lock = threading.Lock()
        from src.core.indexing.watchdog import Watchdog
        self._watchdog = Watchdog()

        # ─── LanceDB Manager ────────────────────────────────
        _dim = getattr(self.embedder, 'embedding_dim', None) or 768
        from src.core.indexing.db_manager import LanceDBManager
        self.db_manager = LanceDBManager(
            db_path=db_path,
            embedder=embedder,
            project_path=self.project_path,
            embedding_dim=_dim,
        )
        # Прокси для обратной совместимости
        self.db = self.db_manager.db
        self.table = self.db_manager.table
        self.schema = self.db_manager.schema
        self._cached_total_chunks = self.db_manager._cached_total_chunks
        self._cached_unique_files = self.db_manager._cached_unique_files
        self._needs_full_reindex = self.db_manager._needs_full_reindex
        self._index_guard = self.db_manager._index_guard

        # ─── SymbolIndex (persistent graph) ─────────────────
        if symbol_index is not None:
            self._symbol_index = symbol_index
        else:
            from src.core.graph import PropertyGraph
            from src.core.search.graph_adapter import SymbolIndexAdapter

            _graph_db = self.project_path / ".codebase" / "graph.db"
            _pg = PropertyGraph(_graph_db)
            self._symbol_index = SymbolIndexAdapter(_pg, mode=SymbolIndexAdapter.MODE_PURE)
            logger.info(f"PropertyGraph: {_pg.count_nodes()} nodes, {_pg.count_edges()} edges")
            self._property_graph = _pg

        # ─── IndexPipeline (parse -> embed)
        from src.core.indexing.index_pipeline import IndexPipeline
        self._pipeline = IndexPipeline(
            embedder=self.embedder,
            parser=self.parser,
            index_parser=self._index_parser,
            symbol_index=self._symbol_index,
            symbol_index_lock=self._symbol_index_lock,
            project_path=self.project_path,
            table=self.table,  # для chunk-level кэша
        )

        # ─── IndexStatusReporter
        from src.core.indexing.index_status import IndexStatusReporter
        self._status_reporter = IndexStatusReporter(
            table=self.table,
            project_path=self.project_path,
            file_guard=self.file_guard,
            watchdog_callback=self.watchdog_status,
        )
        self._cached_total_chunks = self._status_reporter._cached_total_chunks
        self._cached_unique_files = self._status_reporter._cached_unique_files

        # ─── LanceDBWriter
        from src.core.indexing.db_writer import LanceDBWriter
        self._db_writer = LanceDBWriter(
            table=self.table,
            table_write_lock=self._table_write_lock,
            index_lock=self._index_lock,
            embedder=self.embedder,
        )
        # Регистрируем callback для синхронизации таблицы при пересоздании
        self._db_writer.set_on_recreate_callback(self._sync_table_ref)

        # ─── FreshnessChecker
        from src.core.indexing.freshness import FreshnessChecker
        self._freshness_checker = FreshnessChecker(
            table=self.table,
            file_guard=self.file_guard,
            index_single_file=self._index_single_file,
            calculate_file_hash=self._calculate_file_hash,
        )

        # ─── Chunk Summarizer ───────────────────────────────
        self.enable_summaries = enable_summaries
        self.summarizer = None
        if enable_summaries:
            cache_dir = db_path.parent / "summaries_cache"
            self.summarizer = ChunkSummarizer(embedder=embedder, cache_dir=cache_dir)

        # ─── FileMoveManager
        from src.core.indexing.file_move_manager import FileMoveManager
        self._file_move_manager = FileMoveManager(
            table=self.table,
            searcher=self.searcher,
        )

        # ─── IndexProjectRunner
        from src.core.indexing.index_project_runner import IndexProjectRunner
        self._project_runner = IndexProjectRunner(
            parse_file_only=self._parse_file_only,
            write_file_records=self._write_file_records,
            embedder=self.embedder,
            file_guard=self.file_guard,
            searcher=self.searcher,
            table=self.table,
            path_manager=self.path_manager,
            project_path=self.project_path,
            notification_broker=self._notification_broker,
            summarizer=self.summarizer,
            last_reported_progress=self._last_reported_progress,
            db_manager=self.db_manager,
        )

        # ─── Load SymbolIndex from disk ─────────────────────
        try:
            if self._index_guard.load_symbol_index(self._symbol_index):
                logger.info(f"SymbolIndex: {self._symbol_index.get_symbol_count()} symbols")
        except Exception as _e:
            logger.debug(f"SymbolIndex load skipped: {_e}")
    def watchdog_heartbeat(self, label: str = ""):
        self._watchdog.heartbeat(label)

    def watchdog_status(self) -> dict:
        return self._watchdog.status()

    def set_searcher(self, searcher) -> None:
        """Ленивая инжекция Searcher (см. INC-53EC / REFC-05).

        Документированная альтернатива прямому присваиванию
        `indexer.searcher = ...` — не нарушает инкапсуляцию.
        Идемпотентен: повторный вызов заменяет ссылку.
        """
        self.searcher = searcher

    def _sync_table_ref(self, new_table) -> None:
        """Синхронизирует self.table во всех компонентах после пересоздания таблицы.

        Вызывается из LanceDBWriter._safe_recreate_table() через callback.
        Обновляет table в:
        - Indexer.table
        - Indexer._db_writer.table (уже обновлён в _safe_recreate_table)
        - Indexer._status_reporter.table
        - Indexer._freshness_checker.table
        - Indexer._file_move_manager.table
        - Indexer._project_runner.table
        """
        self.table = new_table
        if hasattr(self, '_status_reporter') and self._status_reporter is not None:
            self._status_reporter.table = new_table
            self._status_reporter.reset_cache()
        if hasattr(self, '_freshness_checker') and self._freshness_checker is not None:
            self._freshness_checker.table = new_table
        if hasattr(self, '_file_move_manager') and self._file_move_manager is not None:
            self._file_move_manager.table = new_table
        if hasattr(self, '_project_runner') and self._project_runner is not None:
            self._project_runner.table = new_table
        logger.info("🔄 Table reference synced across all components")

    # ══════════════════════════════════════════════════════════
        # Async LanceDB API (delegated to LanceDBManager)
    async def _ensure_async_table(self):
        return await self.db_manager.ensure_async_table()

    async def to_pandas_async(self):
        return await self.db_manager.to_pandas_async()

    async def count_rows_async(self) -> int:
        return await self.db_manager.count_rows_async()

    async def close_async(self) -> None:
        await self.db_manager.close_async()

    def _warmup_status(self) -> None:
        self.db_manager._warmup_cache()
        self._cached_total_chunks = self.db_manager._cached_total_chunks
        self._cached_unique_files = self.db_manager._cached_unique_files

    def switch_project(self, project_path: Path) -> None:
        self.project_path = project_path
        new_db_path = _generate_unique_db_path(project_path)
        self.db_manager.switch_db(new_db_path)
        self.db = self.db_manager.db
        self.table = self.db_manager.table
        self._cached_total_chunks = self.db_manager._cached_total_chunks
        self._cached_unique_files = self.db_manager._cached_unique_files
        self._needs_full_reindex = self.db_manager._needs_full_reindex
        self._index_guard = self.db_manager._index_guard
    def _calculate_file_hash(self, safe_path: Path) -> str:
        """Вычисляет хэш файла для отслеживания изменений (SHA256)."""
        hasher = hashlib.sha256()
        with open(str(safe_path), "rb") as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()

    def get_status(self) -> Dict[str, Any]:
        """Делегировано IndexStatusReporter."""
        return self._status_reporter.get_status()

    def _write_file_records(
        self,
        parsed: Dict,
        embeddings: List[List[float]],
    ) -> bool:
        """Запись результатов эмбеддинга в LanceDB (делегировано LanceDBWriter)."""
        rel_path_str = parsed["rel_path"]
        records = self._db_writer.write_records(
            parsed=parsed,
            embeddings=embeddings,
            summarizer=self.summarizer,
            enable_summaries=self.enable_summaries,
            parser=self.parser,
        )
        if not records:
            return False

        # Синхронизация кэша
        with self._index_lock:
            self._cached_total_chunks += len(records)
            self._cached_unique_files.add(rel_path_str)

        # Сохраняем SymbolIndex на диск
        try:
            self._index_guard.save_symbol_index(self._symbol_index)
        except Exception as _e:
            logger.warning("exception", exc_info=True)
            pass

        logger.info(f"Записано в БД: {rel_path_str} ({len(records)} чанков)")
        return True

    def _parse_file_only(
        self,
        full_path: Path,
        rel_path_str: str,
        source: str = "filesystem",
        known_hashes: Optional[Dict[str, str]] = None,
    ) -> Optional[Dict]:
        """Только парсинг файла (без эмбеддинга и записи в БД).

        Делегирует чтение и AST-чанкинг в IndexParser, затем
        добавляет LanceDB-специфичные поля и обновляет SymbolIndex.

        Returns:
            Dict с данными чанков или None если файл не изменился.
        """
        try:
            # 1. Получаем existing_hash (из bulk-кэша или через self.table)
            existing_hash = None
            if known_hashes is not None:
                existing_hash = known_hashes.get(rel_path_str)
            else:
                try:
                    if self.table is not None:
                        escaped_path = self._escape_file_path_for_lance(rel_path_str)
                        existing_df = (
                            self.table.search()
                            .where(f"file_path = '{escaped_path}'", prefilter=True)
                            .limit(1)
                            .to_pandas()
                        )
                        if not existing_df.empty:
                            existing_hash = str(existing_df["file_hash"].iloc[0])
                except Exception as _e:
                    err_str = str(_e).lower()
                    if "not found" in err_str or "lanceerror" in err_str:
                        # Таблица повреждена (reindex в процессе) — self-heal
                        logger.warning(
                            "_parse_file_only: таблица повреждена, "
                            "reset_connection и повторная попытка"
                        )
                        try:
                            if hasattr(self, "db_manager") and self.db_manager is not None:
                                self.db_manager.reset_connection()
                                self.table = self.db_manager.table
                                existing_df = (
                                    self.table.search()
                                    .where(f"file_path = '{escaped_path}'", prefilter=True)
                                    .limit(1)
                                    .to_pandas()
                                )
                                if not existing_df.empty:
                                    existing_hash = str(existing_df["file_hash"].iloc[0])
                        except Exception as _e2:
                            logger.debug(f"_parse_file_only retry failed: {_e2}")
                            pass
                    else:
                        logger.warning("exception", exc_info=True)
                        pass

            # 2. Чистый парсинг через IndexParser
            parsed = self._index_parser.parse_file(
                full_path=full_path,
                rel_path_str=rel_path_str,
                source=source,
                existing_hash=existing_hash,
            )
            if parsed is None:
                return None

            # 3. LanceDB-специфичное экранирование пути
            parsed["escaped_path"] = self._escape_file_path_for_lance(rel_path_str)

            # 4. Обновление SymbolIndex
            if self.parser is not None:
                try:
                    # Очистка PropertyGraph
                    if hasattr(self._symbol_index, "graph"):
                        pg = self._symbol_index.graph
                        if pg:
                            self._symbol_index.remove_file(str(full_path))

                    # AST-символы из кэша IndexParser (без повторного парсинга)
                    _ast_chunks, symbols = parsed.get("_ast_symbols", (None, None))
                    if symbols:
                        with self._symbol_index_lock:
                            self._symbol_index.add_definitions(str(full_path), symbols)
                        calls = self.parser.extract_calls(full_path)
                        if calls:
                            with self._symbol_index_lock:
                                self._symbol_index.add_references(str(full_path), calls)
                        assignments = self.parser.extract_assignments(full_path)
                        if assignments:
                            with self._symbol_index_lock:
                                self._symbol_index.add_assignments(str(full_path), assignments)
                        imports = self.parser.extract_imports(full_path)
                        if imports:
                            with self._symbol_index_lock:
                                self._symbol_index.add_imports(str(full_path), imports)
                except Exception as sym_err:
                    logger.warning(f"SymbolIndex update failed for {rel_path_str}: {sym_err}")

            return parsed

        except Exception as e:
            logger.warning(f"⚠️ Ошибка парсинга {rel_path_str}: {e}")
            return None

    def _index_single_file(
        self,
        full_path: Path,
        rel_path_str: str,
        content: Optional[str] = None,
        source: str = "filesystem",
    ) -> bool:
        """Индексирует один файл: проверка хэша -> IndexPipeline -> запись."""
        try:
            safe_read_path = self.path_manager.get_safe_path(full_path)
            if content is None:
                with open(str(safe_read_path), "rb") as f:
                    raw_data = f.read()
                content = raw_data.decode("utf-8", errors="replace")

            current_hash = hashlib.md5(content.encode("utf-8")).hexdigest()
            escaped_path = self._escape_file_path_for_lance(rel_path_str)

            # Проверка хэша — файл не изменился?
            existing_hash = None
            try:
                existing_df = (
                    self.table.search()
                    .where(f"file_path = '{escaped_path}'", prefilter=True)
                    .limit(1)
                    .to_pandas()
                )
                if not existing_df.empty:
                    existing_hash = str(existing_df["file_hash"].iloc[0])
            except Exception as _cache_err:
                logger.debug(f"Chunk cache check failed for {rel_path_str}: {_cache_err}")

            if existing_hash == current_hash:
                return False  # Файл не изменился, пропускаем

            # ─── IndexPipeline: парсинг -> эмбеддинг ────────
            parsed = self._pipeline.process_file(
                rel_path_str=rel_path_str,
                full_path=full_path,
                content=content,
                current_hash=current_hash,
                source=source,
            )
            if parsed is None:
                return False

            # ─── Delete old + Write new ──────────────────────
            # Сначала удаляем старые записи, потом добавляем новые.
            # Такой порядок гарантирует, что файл не пропадёт из индекса
            # при таймауте между delete и add (INC-TIMEOUT-FIX v3.1).
            with self._table_write_lock:
                self.table.delete(f"file_path = '{escaped_path}'")
                self._write_file_records(parsed, parsed["embeddings"])

            # ─── FTS5 incremental sync (А: не рассинхронизироваться с LanceDB) ───
            # Только если FTS5 уже построен (иначе lazy-rebuild при поиске).
            if self.searcher is not None and hasattr(self.searcher, "incremental_update_fts5"):
                try:
                    fts5_chunks = self._build_fts5_chunks_from_parsed(
                        rel_path_str, parsed
                    )
                    if fts5_chunks:
                        self.searcher.incremental_update_fts5(fts5_chunks)
                except Exception as _fts5_err:
                    logger.debug(f"FTS5 sync skipped for {rel_path_str}: {_fts5_err}")

            import gc
            gc.collect()
            return True

        except Exception as e:
            logger.error(f"Index failed for {rel_path_str}: {e}")
            return False

    def _build_fts5_chunks_from_parsed(
        self, rel_path_str: str, parsed: dict
    ) -> List[dict]:
        """Собирает FTS5-совместимые чанки из результата IndexPipeline.process_file.

        FTS5 ожидает: file_path, chunk_index, text, symbol_name, symbol_kind,
        docstring, layer. symbol_name/kind/docstring извлекаются из текста
        теми же хелперами, что и в FTS5Mixin._build_fts5_index.
        """
        from src.core.search.fts5_mixin import FTS5Mixin

        texts = parsed.get("chunk_texts", [])
        metas = parsed.get("chunk_metadatas", [])
        chunks = []
        for i, text in enumerate(texts):
            meta = metas[i] if i < len(metas) else {}
            symbol_name, symbol_kind = FTS5Mixin._extract_symbol_from_text(text)
            docstring = FTS5Mixin._extract_docstring(text)
            chunks.append({
                "file_path": rel_path_str,
                "chunk_index": i,
                "text": text,
                "symbol_name": symbol_name,
                "symbol_kind": symbol_kind,
                "docstring": docstring,
                "layer": meta.get("layer", ""),
            })
        return chunks

    def move_chunks_metadata(self, old_path: str, new_path: str) -> int:
        """P0 Meta-patching: update file_path in LanceDB WITHOUT re-embedding.

        Extracts old chunks, changes file_path metadata, re-inserts same vectors.
        Returns count of affected chunks for BM25 sync.

        Args:
            old_path: Old relative file path
            new_path: New relative file path

        Returns:
            Number of chunks moved
        """
        # Sanitize paths for LanceDB SQL filter
        safe_old = old_path.replace("\\", "/").replace("'", "''")
        safe_new = new_path.replace("\\", "/").replace("'", "''")

        if safe_old == safe_new:
            return 0

        try:
            # 1. Read old chunks with vectors and metadata
            old_df = self.table.search().where(f"file_path = '{safe_old}'").limit(10000).to_pandas()

            if old_df.empty:
                logger.debug(f"move_chunks_metadata: no chunks found for {old_path}")
                return 0

            count = len(old_df)

            # 2. Delete old entries from vector index
            self.table.delete(f"file_path = '{safe_old}'")

            # 3. Mutate metadata
            old_df['file_path'] = safe_new
            old_df['module_name'] = self._infer_module_name(new_path)
            old_df['layer'] = self._infer_layer(new_path)
            old_df['indexed_at'] = datetime.now().isoformat()

            # 4. Re-insert same vectors with new metadata
            self.table.add(old_df.to_dict('records'))

            # 5. Invalidate cache
            self._cached_total_chunks = None
            self._cached_unique_files.discard(old_path)

            logger.info(f"\u267b\ufe0f Meta-patched {count} chunks: {old_path} \u2192 {new_path}")
            return count

        except Exception as e:
            logger.error(f"move_chunks_metadata failed: {old_path} \u2192 {new_path}: {e}")
            return 0

    def apply_file_move(self, old_path: str, new_path: str) -> dict:
        """Coordinate file rename across all index layers.

        Instead of notify_change (which triggers full reindex),
        this does fast meta-patching in all layers.

        Args:
            old_path: Old relative file path
            new_path: New relative file path

        Returns:
            Dict with status, chunks_moved, symbol_updates
        """
        results = {"status": "ok", "chunks_moved": 0, "symbol_updates": 0, "bm25": "invalidated"}

        # 1. LanceDB meta-patching
        chunks = self.move_chunks_metadata(old_path, new_path)
        results["chunks_moved"] = chunks

        # 2. SymbolIndex remap
        try:
            symbol_updates = self._symbol_index.remap_file(old_path, new_path)
            results["symbol_updates"] = symbol_updates
        except Exception as e:
            logger.warning(f"SymbolIndex remap failed: {e}")
            results["symbol_updates"] = -1

        # 3. BM25 invalidation (next search will rebuild from LanceDB)
        if self.searcher is not None and hasattr(self.searcher, '_reset_bm25'):
            try:
                self.searcher._reset_bm25()
                results["bm25"] = "invalidated"
            except Exception as e:
                logger.debug(f"BM25 reset failed: {e}")

        # 4. FTS5: удаляем старый путь (FTS5 перестроится lazy при поиске,
        # т.к. move_chunks_metadata меняет file_path в LanceDB — source of truth)
        if self.searcher is not None and hasattr(self.searcher, 'remove_from_fts5'):
            try:
                self.searcher.remove_from_fts5(old_path)
                results["fts5"] = "old_path_removed"
            except Exception as e:
                logger.debug(f"FTS5 remove failed: {e}")

        # 5. Notify file guard
        try:
            if hasattr(self.file_guard, 'notify_file_renamed'):
                self.file_guard.notify_file_renamed(old_path, new_path)
        except Exception as _e:
            logger.warning("exception", exc_info=True)
            pass
        return results

    def _infer_module_name(self, file_path: str) -> str:
        """Infer Python module name from relative file path.

        E.g., 'src/core/indexer.py' \u2192 'core.indexer'
        """
        p = Path(file_path.replace("\\", "/"))
        stem = p.stem
        parts = p.parts
        # Find package root (src/, app/, lib/, or first meaningful dir)
        skip_dirs = {"src", "app", "lib"}
        module_parts = []
        in_package = False
        for part in parts[:-1]:  # exclude filename
            if not in_package:
                if part in skip_dirs:
                    in_package = True
                continue
            module_parts.append(part)
        module_parts.append(stem)
        return ".".join(module_parts)

    def _infer_layer(self, file_path: str) -> str:
        """Infer architectural layer from file path.

        E.g., 'src/core/foo.py' \u2192 'core', 'src/mcp/tools/bar.py' \u2192 'mcp_tools'
        """
        parts = file_path.replace("\\", "/").split("/")
        if "core" in parts:
            return "core"
        if "mcp" in parts:
            if "tools" in parts:
                return "mcp_tools"
            return "mcp"
        if "tests" in parts:
            return "tests"
        if "utils" in parts:
            return "utils"
        if "docs" in parts:
            return "docs"
        return "root"

    def verify_index_freshness(self, project_path: Path) -> int:
        """Быстрая проверка: переиндексирует только файлы с изменившимся hash."""
        return self._freshness_checker.verify(project_path)

    def _safe_recreate_table(self):
        """Fallback: удалить и пересоздать таблицу."""
        try:
            schema = self.table.schema
            self.db.drop_table("codebase_chunks")
            self.table = self.db.create_table("codebase_chunks", schema=schema)
            return True
        except Exception as e:
            logger.error(f"Table recreation failed: {e}")
            return False

    def index_project(
        self,
        project_path: Path,
        progress_callback: Optional[Callable] = None,
        phase_callback: Optional[Callable] = None,
    ) -> int:
        """Полная индексация проекта (делегировано IndexProjectRunner)."""
        return self._project_runner.run(
            project_path=project_path,
            progress_callback=progress_callback,
            phase_callback=phase_callback,
            watchdog_heartbeat=self.watchdog_heartbeat,
            prune_deleted_files=self.prune_deleted_files,
            get_status=self.get_status,
            save_symbol_index=lambda: self._index_guard.save_symbol_index(self._symbol_index),
        )

    def index_file(
        self, full_path: Path, project_path: Path, content: Optional[str] = None
    ) -> bool:
        """Публичный метод для индексации одного файла (вызывается из LSP-сервера).

        Args:
            full_path: Абсолютный путь к файлу
            project_path: Корневая директория проекта
            content: Готовый текст файла из памяти LSP (didSave). Если None — читает с диска.

        Returns:
            True если файл был проиндексирован, False если пропущен
        """
        try:
            if not self.path_manager.is_safe_to_process(full_path):
                return False
            if self.file_guard.should_skip_file(full_path):
                return False

            rel_path_str = str(full_path.relative_to(project_path))
            return self._index_single_file(full_path, rel_path_str, content=content)
        except Exception as e:
            logger.error(f"[index_file] Ошибка индексации {full_path}: {e}")
            return False
