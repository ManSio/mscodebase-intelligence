"""
MSCodebase Intelligence — Продакшен инкрементальный индекс на LanceDB с авто-очисткой (Pruning)
"""

import hashlib
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from src.core.indexing.chunk_summarizer import ChunkSummarizer
from src.core.indexing.indexer_table import IndexerTableMixin
from src.utils.paths import SafePathManager

logger = logging.getLogger("mscodebase_server.indexer")

# Размер батча для кросс-файлового эмбеддинга.
# E5-base/BGE-M3 обрабатывают 64 текста почти за то же время, что и 1.
_BATCH_SIZE = 64


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

        # ─── Chunk Summarizer ───────────────────────────────
        self.enable_summaries = enable_summaries
        self.summarizer = None
        if enable_summaries:
            cache_dir = db_path.parent / "summaries_cache"
            self.summarizer = ChunkSummarizer(embedder=embedder, cache_dir=cache_dir)

        # ─── Load SymbolIndex from disk ─────────────────────
        try:
            if self._index_guard.load_symbol_index(self._symbol_index):
                logger.info(f"SymbolIndex: {self._symbol_index.get_symbol_count()} symbols")
        except Exception as _e:
            logger.debug(f"SymbolIndex load skipped: {_e}")
    def watchdog_heartbeat(self, label: str = ""):
        """Обновляет heartbeat — вызывается при каждом прогрессе.

        Если индексер завис, watchdog не обновляется >60s.
        HealthReport проверяет это поле.
        """
        with self._watchdog_lock:
            self._watchdog_heartbeat = time.time()
            self._watchdog_ever_beat = True
            if label:
                self._watchdog_label = label

    def watchdog_status(self) -> dict:
        """Возвращает статус watchdog для HealthReport.

        Корректно обрабатывает idle-состояние:
        - Если heartbeat никогда не бился (чистый idle) — alive=True, idle_sec=0.
        - Если бился, но давно — считаем age от последнего удара.
        - Ложная critical-ошибка "56 лет простоя" устранена (init = time.time()).
        """
        with self._watchdog_lock:
            if not self._watchdog_ever_beat:
                # Индексер простаивает с момента запуска — это норма, не сбой
                return {
                    "alive": True,
                    "idle_sec": 0.0,
                    "label": self._watchdog_label,
                }
            age = time.time() - self._watchdog_heartbeat
            return {
                "alive": age < 60.0,
                "idle_sec": round(age, 1),
                "label": self._watchdog_label,
            }

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
        """Запись результатов эмбеддинга в LanceDB.

        Принимает результат `_parse_file_only` и список векторов,
        собирает PyArrow-записи и атомарно пишет в таблицу.

        Args:
            parsed: результат _parse_file_only
            embeddings: список векторов (по одному на чанк)

        Returns:
            True если запись успешна, иначе False
        """
        rel_path_str = parsed["rel_path"]
        current_hash = parsed["current_hash"]
        escaped_path = parsed["escaped_path"]
        existing_hash = parsed["existing_hash"]
        chunk_texts = parsed["chunk_texts"]
        chunk_texts_full = parsed["chunk_texts_full"]
        chunk_metadatas = parsed["chunk_metadatas"]
        health = parsed["health"]
        source = parsed["source"]

        if not embeddings or len(embeddings) != len(chunk_texts):
            logger.warning(
                f"⚠️ Несовпадение числа эмбеддингов и чанков для {rel_path_str}: "
                f"{len(embeddings)} vs {len(chunk_texts)}"
            )
            return False

        _target_dim = self.embedder.embedding_dim or 768
        data_records = []
        for i, (chunk_text, chunk_vec) in enumerate(zip(chunk_texts, embeddings)):
            # Нормализация вектора под размерность схемы
            if len(chunk_vec) != _target_dim:
                chunk_vec = chunk_vec[:_target_dim] + [0.0] * (_target_dim - len(chunk_vec))

            full_text = (
                chunk_texts_full[i] if i < len(chunk_texts_full) else chunk_text
            )

            # LLM-описание если включено
            summary = ""
            if self.summarizer and self.enable_summaries:
                symbol_name = ""
                if self.parser and hasattr(self.parser, "_current_symbol"):
                    symbol_name = getattr(self.parser, "_current_symbol", "")
                summary = self.summarizer.summarize_chunk(chunk_text, symbol_name)

            meta = chunk_metadatas[i] if i < len(chunk_metadatas) else {}

            data_records.append(
                {
                    "id": f"{hashlib.md5(rel_path_str.encode()).hexdigest()}_{i}",
                    "vector": chunk_vec,
                    "text": chunk_text,
                    "text_full": full_text,
                    "file_path": rel_path_str,
                    "file_hash": current_hash,
                    "chunk_index": i,
                    "source": source,
                    "indexed_at": datetime.now().isoformat(),
                    "summary": summary,
                    "layer": meta.get("layer", ""),
                    "module_name": meta.get("module_name", ""),
                    "hierarchy_level": meta.get("hierarchy_level", "other"),
                    "is_public": meta.get("is_public", False),
                    "symbol_type": meta.get("symbol_type", ""),
                    "parent_id": meta.get("parent_id", ""),
                    "callees": meta.get("callees", ""),
                    "health_score": health.get("score", 0.0),
                    "health_band": health.get("band", ""),
                }
            )

        # Атомарная запись пачки чанков в таблицу
        with self._table_write_lock:
            old_chunks = 0
            if existing_hash is not None:
                try:
                    old_chunks = self.table.count_rows(
                        filter=f"file_path = '{escaped_path}'"
                    )
                except Exception as _e:
                    logger.warning("exception", exc_info=True)
                    pass
                try:
                    self.table.delete(f"file_path = '{escaped_path}'")
                except Exception as del_err:
                    logger.debug(f"delete() не нашёл запись: {del_err}")

            try:
                self.table.add(data_records)
            except Exception as add_err:
                err_str = str(add_err).lower()
                if (
                    "not found" in err_str
                    or "does not exist" in err_str
                    or "no such table" in err_str
                ):
                    logger.warning(
                        f"⚠️ Таблица не найдена при записи, пересоздаём и ретраим: {add_err}"
                    )
                    if self._safe_recreate_table():
                        self.table.add(data_records)
                    else:
                        raise
                else:
                    raise

        # Синхронизация кэша
        with self._index_lock:
            if old_chunks > 0:
                self._cached_total_chunks = max(
                    0, self._cached_total_chunks - old_chunks + len(data_records)
                )
            else:
                self._cached_total_chunks += len(data_records)
            self._cached_unique_files.add(rel_path_str)

        # Сохраняем SymbolIndex на диск
        try:
            self._index_guard.save_symbol_index(self._symbol_index)
        except Exception as _e:
            logger.warning("exception", exc_info=True)
            pass
        logger.info(
            f"✅ Записано в БД: {rel_path_str} ({len(chunk_texts)} чанков)"
        )
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

            # Очистка PropertyGraph
            if hasattr(self._symbol_index, "graph"):
                pg = self._symbol_index.graph
                if pg:
                    pg.remove_file(rel_path_str.replace("\\", "/"))

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
        """Быстрая проверка: переиндексирует только файлы с изменившимся hash.

        В отличие от index_project:
        - Не удаляет orphan файлы (только предупреждает)
        - Не перестраивает BM25
        - Не создаёт IVF_PQ индекс
        - Работает за 2-5 секунд вместо 5 минут

        Returns: количество переиндексированных файлов.
        """
        project_path = Path(project_path).resolve()
        if not project_path.exists():
            return 0

        if self.table is None:
            return 0

        try:
            # Получаем все file_hash из индекса
            df = self.table.to_pandas(columns=["file_path", "file_hash"])
        except Exception:
            return 0

        if df.empty:
            return 0

        indexed_hashes = dict(zip(df["file_path"], df["file_hash"]))

        reindexed = 0
        walk_root = str(project_path.resolve())
        for root, dirs, files in os.walk(walk_root):
            dirs[:] = [d for d in dirs if not self.file_guard.should_skip_dir(d)]
            for file_name in files:
                full_path = Path(root) / file_name
                if self.file_guard.should_skip_file(full_path):
                    continue
                try:
                    rel = str(full_path.relative_to(project_path)).replace(
                        os.sep, "/"
                    )
                except ValueError:
                    continue

                # Если файла нет в индексе — пропускаем (не наша забота)
                if rel not in indexed_hashes:
                    continue

                # Сверяем hash
                try:
                    current_hash = self._calculate_file_hash(full_path)
                except Exception:
                    continue

                if current_hash == indexed_hashes[rel]:
                    continue  # не изменился

                # Файл изменился — переиндексируем
                if self._index_single_file(full_path, project_path):
                    reindexed += 1

        if reindexed > 0:
            logger.info(f"📝 Переиндексировано {reindexed} изменённых файлов")
        else:
            logger.info("✅ Индекс свежий, изменений нет")

        return reindexed

    def index_project(
        self, project_path: Path, progress_callback: Optional[Callable] = None
    ) -> int:
        """Полное сканирование проекта.

        1. Инкрементально добавляет новые/измененные файлы.
        2. Автоматически удаляет из базы файлы, стертые с диска (Pruning).

        Args:
            project_path: Путь к корневой директории проекта.
                Должен существовать и быть директорией.
            progress_callback: Опциональный callback для отслеживания прогресса.
                Вызывается с аргументами: (current_file, files_done, files_total, phase)
                phase: 'scanning', 'embedding', 'complete'

        Returns:
            Количество индексированных (новых/изменённых) файлов.

        Raises:
            FileNotFoundError: Если project_path не существует.
            NotADirectoryError: Если project_path не является директорией.
        """
        project_path = Path(project_path).resolve()

        if not project_path.exists():
            raise FileNotFoundError(f"Путь проекта не существует: {project_path}")
        if not project_path.is_dir():
            raise NotADirectoryError(f"Путь не является директорией: {project_path}")

        logger.info(f"🚀 Старт фоновой синхронизации проекта: {project_path}")
        indexed_count = 0
        current_files_on_disk: Set[str] = set()

        if not self.path_manager.is_safe_to_process(project_path):
            logger.warning(f"Путь не прошёл проверку безопасности: {project_path}")
            if progress_callback:
                progress_callback("", 0, 0, "error_security")
            return 0

        # Подсчёт общего числа файлов для прогресса
        all_files: list = []
        walk_root = str(project_path.resolve())
        for root, dirs, files in os.walk(walk_root):
            dirs[:] = [d for d in dirs if not self.file_guard.should_skip_dir(d)]
            for file_name in files:
                full_path = Path(root) / file_name
                if self.file_guard.should_skip_file(full_path):
                    continue
                all_files.append((root, file_name, full_path))

        total_files = len(all_files)
        logger.info(f"📁 Найдено {total_files} файлов для индексации")

        if progress_callback:
            progress_callback("", 0, total_files, "scanning")

        # Уведомление через NotificationBroker — сквозной прогресс 0-100%
        # через все фазы: Phase 1 (parse) 0-70%, Phase 2 (embed) 70-90%, Phase 3 (write) 90-100%
        def _notify_progress(
            done: int, total: int, phase: str, current: str,
            offset_pct: float = 0.0, span_pct: float = 100.0,
        ):
            if not self._notification_broker:
                return
            raw = (done / total) if total > 0 else 0.0
            continuous = offset_pct + raw * span_pct
            pct = int(continuous)
            if (
                pct == 0
                or pct == 100
                or (pct % 5 == 0 and pct != self._last_reported_progress)
            ):
                self._last_reported_progress = pct
                self._notification_broker.publish_sync(
                    "mscodebase/indexing_status",
                    {
                        "status": "indexing" if pct < 100 else "idle",
                        "progress": pct,
                        "total_chunks": total,
                        "current_file": current or "",
                    },
                )

        _notify_progress(0, total_files, "scanning", "", 0, 5)

        # ═══════════════════════════════════════════════════════════
        # Batch Embedder: Фаза 1 (Parse) → Фаза 2 (Sort+Embed) → Фаза 3 (Write)
        # ═══════════════════════════════════════════════════════════
        #
        # Фаза 1 (параллельный парсинг):
        #   workers парсят файлы → список parsed (с хэшами)
        #
        # Фаза 2 (сортировка + батчинг):
        #   все чанки собираются в плоский список
        #   сортируются по длине (чтобы минимизировать padding)
        #   эмбеддятся батчами по _BATCH_SIZE
        #
        # Фаза 3 (запись):
        #   результаты разбираются обратно по файлам → _write_file_records
        # ═══════════════════════════════════════════════════════════

        # ── Фаза 1: Параллельный парсинг ───────────────────────────
        from concurrent.futures import ThreadPoolExecutor

        _max_workers = min(4, (os.cpu_count() or 4) // 2)
        _all_parsed: list = []  # список {"parsed": Dict, "name": str}
        _parse_errors = []

        def _parse_worker_file(args):
            _idx, _root, _fname, _full_path = args
            _rel_path = str(_full_path.relative_to(project_path))
            current_files_on_disk.add(_rel_path)

            try:
                parsed = self._parse_file_only(
                    _full_path, _rel_path, source="filesystem"
                )
                if parsed is not None:
                    return {"parsed": parsed, "name": _fname, "rel": _rel_path}
            except Exception as e:
                return {"error": str(e), "rel": _rel_path}
            return None

        _parsed_list: list = []
        with ThreadPoolExecutor(max_workers=_max_workers) as _exec:
            _futs = []
            for idx, (root, fname, fpath) in enumerate(all_files):
                _futs.append(_exec.submit(_parse_worker_file, (idx, root, fname, fpath)))

            for i, fut in enumerate(_futs):
                try:
                    res = fut.result()
                    if res:
                        if "error" in res:
                            _parse_errors.append((res["rel"], res["error"]))
                        else:
                            _parsed_list.append(res)
                            self.watchdog_heartbeat(f"parse:{res['name']}")
                except Exception as e:
                    logger.warning(f"\u26a0\ufe0f Worker error: {e}")

                # Прогресс парсинга
                if i % max(1, total_files // 20) == 0 or i == total_files - 1:
                    if progress_callback:
                        try:
                            progress_callback("", i + 1, total_files, "parsing")
                        except Exception as _e:
                            logger.warning("exception", exc_info=True)
                            pass
                    _notify_progress(i + 1, total_files, "parsing", "", 5, 50)

        parsed_count = len(_parsed_list)
        logger.info(f"\u2705 Парсинг завершён: {parsed_count} файлов изменено из {total_files}")

        if parsed_count == 0:
            logger.info("\u2705 Нет изменённых файлов — индекс актуален")
            indexed_count = 0
            # Всё равно делаем pruning и финализируем
            pruned = self.prune_deleted_files(current_files_on_disk)
            if self.searcher:
                self.searcher.reindex()
            if progress_callback:
                progress_callback("", total_files, total_files, "complete")
            _notify_progress(total_files, total_files, "complete", "", 0, 100)
            return 0

        # ── Фаза 2: Сортировка + батчинг эмбеддинга ────────────────
        # Собираем все чанки в плоский список с индексами файлов
        _flat_chunks: list = []  # [(file_idx, text), ...]
        for fp_idx, fp_data in enumerate(_parsed_list):
            parsed = fp_data["parsed"]
            for chunk_text in parsed["chunk_texts"]:
                _flat_chunks.append((fp_idx, chunk_text))

        total_chunks = len(_flat_chunks)
        logger.info(f"\U0001f4ca Всего чанков: {total_chunks}, batch_size={_BATCH_SIZE}")

        # Сортируем по длине текста (минимизируем padding)
        _flat_chunks.sort(key=lambda x: len(x[1]))

        # Проверка: embedder готов?
        if not getattr(self.embedder, 'is_ready', lambda: True)():
            logger.error("❌ Embedder не готов к работе. Индексация прервана.")
            return 0

        # Батчим по _BATCH_SIZE
        _all_embeddings: list = [None] * total_chunks
        _embed_t0 = time.time()

        for batch_start in range(0, total_chunks, _BATCH_SIZE):
            batch_end = min(batch_start + _BATCH_SIZE, total_chunks)
            batch_data = _flat_chunks[batch_start:batch_end]
            batch_texts = [text for (_, text) in batch_data]
            [idx for (idx, _) in batch_data]

            # Эмбеддинг батча
            t0 = time.time()
            try:
                embeddings = self.embedder.embed_batch(batch_texts)
            except Exception as embed_err:
                # НЕ подменяем нулями — это отравляет индекс (все векторы
                # становятся нулевыми, семантический поиск ломается, а
                # IVF-индекс не строится с "0 vectors"). Прерываем индексацию
                # с явной ошибкой, чтобы причина была видна пользователю.
                logger.error(
                    f"❌ Embedder error: {embed_err}. Индексация прервана "
                    f"(embedder недоступен — проверьте ONNX/OpenVINO модель)."
                )
                raise RuntimeError(
                    f"Embedder unavailable: {embed_err}. "
                    f"Indexing aborted to avoid zero-vector corruption."
                ) from embed_err
            embed_time = time.time() - t0

            if not embeddings or len(embeddings) != len(batch_texts):
                raise RuntimeError(
                    f"Embedder returned {len(embeddings) if embeddings else 0} "
                    f"vectors instead of {len(batch_texts)} — indexing aborted."
                )

            # Раскладываем результаты обратно по flat-индексу
            for i, flat_idx in enumerate(range(batch_start, batch_end)):
                _all_embeddings[flat_idx] = embeddings[i]

            # Мониторинг каждые 5 батчей
            if batch_start % (_BATCH_SIZE * 5) == 0 or batch_end >= total_chunks:
                elapsed = time.time() - _embed_t0
                done = min(batch_end, total_chunks)
                speed = done / elapsed if elapsed > 0 else 0
                try:
                    from src.core.indexing.resource_monitor import get_monitor
                    mon = get_monitor()
                    snap = mon.sample(force=True)
                    ram_info = f"RAM={snap.rss_mb:.0f}MB CPU={snap.cpu_percent:.0f}%"
                except Exception:
                    ram_info = ""
                logger.info(
                    f"\U0001f4ca [embed] {done}/{total_chunks} chunks "
                    f"{ram_info} "
                    f"batch={len(batch_texts)}ch/{embed_time:.1f}s={len(batch_texts)/max(embed_time,0.001):.0f}ch/s "
                    f"avg={speed:.0f}ch/s elapsed={elapsed:.0f}s"
                )
                _notify_progress(done, total_chunks, "embedding", "", 50, 40)
                self.watchdog_heartbeat(f"embed:{done}/{total_chunks}")

            import gc
            gc.collect()

        _embed_total = time.time() - _embed_t0
        logger.info(f"\u2705 Эмбеддинг завершён: {total_chunks} чанков за {_embed_total:.1f}s ({total_chunks/max(_embed_total,0.001):.0f} ch/s)")
        _notify_progress(total_chunks, total_chunks, "writing", "", 90, 10)

        # ── Фаза 3: Запись результатов по файлам ────────────────────
        # Восстанавливаем маппинг: для каждого файла собираем его embeddings
        _file_embeddings: dict = {}  # {fp_idx: {parsed: ..., vecs: [...]}}
        for flat_idx, (fp_idx, _) in enumerate(_flat_chunks):
            if fp_idx not in _file_embeddings:
                _file_embeddings[fp_idx] = {
                    "parsed": _parsed_list[fp_idx]["parsed"],
                    "vecs": [],
                }
            _file_embeddings[fp_idx]["vecs"].append(_all_embeddings[flat_idx])

        indexed_count = 0
        for fp_idx, fdata in _file_embeddings.items():
            try:
                if self._write_file_records(fdata["parsed"], fdata["vecs"]):
                    indexed_count += 1
                    self.watchdog_heartbeat(f"write:{Path(fdata['parsed']['rel_path']).name}")
            except Exception as e:
                logger.warning(f"\u26a0\ufe0f Ошибка записи {fdata['parsed']['rel_path']}: {e}")

        logger.info(f"\u2705 Запись завершена: {indexed_count} файлов записано")

        # Финальное уведомление
        if progress_callback:
            progress_callback("", total_files, total_files, "indexing")

        # Пауза: даём Windows сбросить буферы записи (race condition LanceDB)
        time.sleep(1)

        # Шаг 2: Автоматическое вычищение (Pruning) «мертвого груза"
        pruned = 0
        try:
            pruned = self.prune_deleted_files(current_files_on_disk)
            if pruned > 0:
                logger.info(f"🗑️ Удалено {pruned} устаревших файлов из базы")
        except Exception as prune_err:
            logger.warning(f"⚠️ Pruning не удался (некритично): {prune_err}")

        # Шаг 3: Перестройка BM25 индекса
        if indexed_count > 0 and self.searcher:
            if progress_callback:
                progress_callback("", total_files, total_files, "rebuilding_bm25")
            self.searcher.reindex()

        # Шаг 4: Создание индекса для ускорения косинусного поиска
        if self.table and self.table.count_rows() > 1000:
            try:
                # 1. Flush данных на диск (compaction)
                try:
                    self.table.optimize(compaction=True)
                except Exception as opt_err:
                    logger.debug(f"optimize: {opt_err}")

                # 2. Пауза для Windows I/O
                time.sleep(2)

                # 3. Проверка реального количества строк
                _row_count = self.table.count_rows()
                logger.info(f"📊 Создаю индекс ({_row_count} чанков)...")
                if _row_count == 0:
                    logger.warning("⚠️ Таблица пуста после optimize, индекс пропущен")
                    return

                # Удаляем старый индекс
                try:
                    for idx in self.table.list_indices():
                        idx_name = getattr(idx, "name", None)
                        if idx_name:
                            self.table.drop_index(idx_name)
                except Exception as _e:
                    logger.warning("exception", exc_info=True)
                    pass
                # 4. IVF_FLAT — стабилен на Windows, без KMeans/PQ
                self.table.create_index(
                    metric="cosine",
                    vector_column_name="vector",
                    index_type="IVF_FLAT",
                    replace=True,
                )
                logger.info("✅ IVF_FLAT индекс создан")
            except Exception as e:
                logger.error(f"⚠️ IVF_PQ индекс не создан: {e}")

        # Шаг 5: Финальная статистика
        final_stats = self.get_status()

        if progress_callback:
            progress_callback("", total_files, total_files, "complete")

        # Финальное Push-уведомление
        _notify_progress(total_files, total_files, "complete", "", 0, 100)

        # Сохраняем кэш суммари
        if self.summarizer:
            self.summarizer.save_cache()

        # Сохраняем SymbolIndex на диск (persistence между перезапусками)
        if hasattr(self, "_symbol_index") and self._symbol_index:
            self._index_guard.save_symbol_index(self._symbol_index)

        logger.info(
            f"✅ Индексация завершена: {indexed_count} новых/изменённых, "
            f"{pruned} удалено, всего {final_stats.get('total_chunks', 0)} чанков"
        )

        return indexed_count

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
