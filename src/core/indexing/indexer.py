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
            symbol_index=self._symbol_index,
            symbol_index_lock=self._symbol_index_lock,
            project_path=self.project_path,
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

        Returns:
            Dict с данными чанков или None если файл не изменился.
            Структура: {
                "rel_path": str, "current_hash": str, "escaped_path": str,
                "existing_hash": str | None, "chunk_texts": List[str],
                "chunk_texts_full": List[str], "chunk_metadatas": List[Dict],
                "health": Dict, "source": str
            }
        """
        try:
            safe_read_path = self.path_manager.get_safe_path(full_path)
            with open(str(safe_read_path), "rb") as f:
                raw_data = f.read()
            content = raw_data.decode("utf-8", errors="replace")

            current_hash = hashlib.md5(content.encode("utf-8")).hexdigest()
            escaped_path = self._escape_file_path_for_lance(rel_path_str)

            # Проверка хэша (один bulk-запрос в index_project или per-file в _index_single_file)
            existing_hash = None
            if known_hashes is not None:
                existing_hash = known_hashes.get(rel_path_str)
            else:
                try:
                    if self.table is not None:
                        existing_df = (
                            self.table.search()
                            .where(f"file_path = '{escaped_path}'", prefilter=True)
                            .limit(1)
                            .to_pandas()
                        )
                        if not existing_df.empty:
                            existing_hash = str(existing_df["file_hash"].iloc[0])
                except Exception as _e:
                    logger.warning("exception", exc_info=True)
                    pass
            if existing_hash == current_hash:
                return None  # не изменился

            if not content.strip():
                return None

            # Очистка PropertyGraph через SymbolIndexAdapter (с нормализацией пути)
            if hasattr(self._symbol_index, "graph"):
                pg = self._symbol_index.graph
                if pg:
                    self._symbol_index.remove_file(str(full_path))

            # AST-чанкинг + Breadcrumbs (как в _index_single_file)
            chunk_texts: List[str] = []
            chunk_texts_full: List[str] = []
            chunk_metadatas: List[Dict] = []
            health = {"score": 0.0, "band": ""}

            if self.parser is not None:
                try:
                    ast_chunks, symbols = self.parser.parse_file(full_path)
                    if ast_chunks:
                        for c in ast_chunks:
                            compact = c.get("text_compact", "") or c.get("text", "")
                            full = c.get("text", "")
                            if compact.strip():
                                _module = c.get("module_name", "")
                                _level = c.get("hierarchy_level", "other")
                                _type = c.get("symbol_type", c.get("type", ""))
                                _scope_parts = [p for p in [_level, _type, _module] if p]
                                _scope = " | ".join(_scope_parts) if _scope_parts else _module
                                _header = f"// File: {rel_path_str} | Scope: {_scope}\n"
                                chunk_texts.append(_header + compact)
                                chunk_texts_full.append(_header + full)
                                chunk_metadatas.append({
                                    "layer": c.get("layer", ""),
                                    "module_name": c.get("module_name", ""),
                                    "hierarchy_level": c.get("hierarchy_level", "other"),
                                    "is_public": c.get("is_public", False),
                                    "symbol_type": c.get("symbol_type", c.get("type", "")),
                                    "parent_id": c.get("parent_id", ""),
                                    "callees": c.get("callees", ""),
                                })
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
                except Exception as ast_err:
                    logger.warning(f"⚠️ AST-чанкинг не удался для {rel_path_str}: {ast_err}")
                    chunk_texts = []
                    chunk_metadatas = []

            if not chunk_texts:
                _fb_header = f"// File: {rel_path_str} | Scope: fallback\n"
                chunk_texts = [
                    _fb_header + content[i : i + 1000] for i in range(0, len(content), 800)
                ]
                chunk_texts_full = chunk_texts
                chunk_metadatas = [{
                    "layer": "", "module_name": "", "hierarchy_level": "other",
                    "is_public": False, "symbol_type": "", "parent_id": "", "callees": "",
                } for _ in chunk_texts]

            if not chunk_texts:
                return None

            # Code Health
            try:
                from src.core.code_health import score_file
                health = score_file(rel_path_str, self.project_path)
            except Exception as _e:
                logger.warning("exception", exc_info=True)
                pass
            return {
                "rel_path": rel_path_str,
                "current_hash": current_hash,
                "escaped_path": escaped_path,
                "existing_hash": existing_hash,
                "chunk_texts": chunk_texts,
                "chunk_texts_full": chunk_texts_full,
                "chunk_metadatas": chunk_metadatas,
                "health": health,
                "source": source,
            }
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
            except Exception:
                pass

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

            import gc
            gc.collect()
            return True

        except Exception as e:
            logger.error(f"Index failed for {rel_path_str}: {e}")
            return False

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

        # 4. Notify file guard
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
