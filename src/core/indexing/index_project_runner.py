"""
IndexProjectRunner — полная индексация проекта: парсинг → эмбеддинг → запись.

Выделено из Indexer.index_project (Phase 7 — «Сердце»).
3 фазы: параллельный парсинг (Phase 1), сортированный батч-эмбеддинг (Phase 2),
  запись + prune + BM25 + IVF (Phase 3).

PID-lock и write guard:
- PID-lock (Layer 3): в db_manager._acquire_pid_lock() — атомарный lock-файл
  с PID. Второй процесс ждёт или падает.
- reindex guard (Layer 1): Indexer.set_reindexing() / clear_reindexing()
  — search fast-fail во время reindex.
- write lock (Layer 2): threading.Lock сериализует write/reconnect
  между потоками одного процесса.
"""

from __future__ import annotations

import gc
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional, Set

__all__ = [
    "IndexProjectRunner",
]
logger = logging.getLogger("mscodebase_server.index_project")


class IndexProjectRunner:
    """Оркестрирует полную индексацию проекта.

    Использует db_manager.begin_write() для сериализации записи в LanceDB.
    PID-lock (Layer 3) обеспечивается db_manager._acquire_pid_lock().
    """

    def __init__(
        self,
        parse_file_only: Callable,
        write_file_records: Callable,
        embedder,
        file_guard,
        searcher,
        table,
        path_manager,
        project_path: Path,
        notification_broker=None,
        summarizer=None,
        last_reported_progress: int = -1,
        db_manager=None,
    ):
        self._parse_file_only = parse_file_only
        self._write_file_records = write_file_records
        self.embedder = embedder
        self.file_guard = file_guard
        self.searcher = searcher
        self.table = table
        self.path_manager = path_manager
        self.project_path = project_path
        self._notification_broker = notification_broker
        self.summarizer = summarizer
        self._last_reported_progress = last_reported_progress
        self.db_manager = db_manager

    # ── Self-healing helpers ───────────────────────────────────────────

    def _reset_table_if_not_found(self, error: Exception, context: str, attempt: int) -> bool:
        """Проверяет, является ли ошибка 'Not found' (LanceDB race),
        и если да — пытается восстановить таблицу через reset_connection.
        Возвращает True, если восстановление выполнено и можно retry.
        """
        err_str = str(error).lower()
        if not any(kw in err_str for kw in ("not found", "lanceerror", "does not exist", "no such")):
            return False

        logger.warning(
            f"{context}: LanceDB race detected ({error}), "
            f"reset_connection + retry (attempt {attempt + 1}/2)"
        )
        try:
            if self.db_manager is not None:
                self.db_manager.reset_connection()
                self.table = self.db_manager.table
            else:
                self._safe_recreate_table()
        except Exception as rc_err:
            logger.error(f"{context}: reset_connection failed: {rc_err}")
            return False
        return True

    def _safe_recreate_table(self):
        """Fallback: удалить и пересоздать таблицу когда db_manager нет."""
        if not hasattr(self, '_write_file_records_from_table'):
            return
        try:
            schema = self.table.schema
            _db = getattr(self.table, '_db', None)
            if _db:
                try:
                    _db.drop_table("codebase_chunks")
                except Exception:
                    pass
                self.table = _db.create_table("codebase_chunks", schema=schema)
        except Exception as e:
            logger.error(f"Table recreate failed: {e}")

    def run(
        self,
        project_path: Path,
        progress_callback: Optional[Callable] = None,
        phase_callback: Optional[Callable] = None,
        watchdog_heartbeat: Optional[Callable] = None,
        prune_deleted_files: Optional[Callable] = None,
        get_status: Optional[Callable] = None,
        save_symbol_index: Optional[Callable] = None,
    ) -> int:
        """Запускает полную индексацию проекта.

        Returns: количество проиндексированных файлов.
        """
        project_path = Path(project_path).resolve()
        if not self.path_manager.is_safe_to_process(project_path):
            logger.warning(f"Path not safe: {project_path}")
            return 0

        BATCH_SIZE = 4       # см. benchmark: batch=4 даёт 52 ch/s для small INT8

        # Write operations сериализуются через db_manager.begin_write()
        # PID-lock уже захвачен в db_manager.__init__()
        with (self.db_manager.begin_write() if self.db_manager else threading_lock_context()):
            logger.info("🔑 Write lock acquired for indexing")

            # Сканирование файлов
            all_files: list = []
            current_files_on_disk: Set[str] = set()

            for root, dirs, files in os.walk(str(project_path.resolve())):
                dirs[:] = [d for d in dirs if self.file_guard and not self.file_guard.should_skip_dir(d)]
                for file_name in files:
                    full_path = Path(root) / file_name
                    if self.file_guard and self.file_guard.should_skip_file(full_path):
                        continue
                    all_files.append((root, file_name, full_path))

            total_files = len(all_files)
            logger.info(f"Found {total_files} files for indexing")
            if progress_callback:
                progress_callback("", 0, total_files, "scanning")

            def _notify_progress(done: int, total: int, phase: str, current: str,
                                  offset_pct: float = 0.0, span_pct: float = 100.0):
                if not self._notification_broker:
                    return
                raw = (done / total) if total > 0 else 0.0
                pct = int(offset_pct + raw * span_pct)
                if pct in (0, 100) or (pct % 5 == 0 and pct != self._last_reported_progress):
                    self._last_reported_progress = pct
                    self._notification_broker.publish_sync(
                        "mscodebase/indexing_status",
                        {"status": "indexing" if pct < 100 else "idle",
                         "progress": pct, "total_chunks": total, "current_file": current or ""},
                    )

            _notify_progress(0, total_files, "scanning", "", 0, 5)

            #Phase 1: Parallel Parse
            def _parse_worker(args):
                _idx, _root, _fname, _full_path = args
                _rel_path = str(_full_path.relative_to(project_path))
                current_files_on_disk.add(_rel_path)
                try:
                    parsed = self._parse_file_only(_full_path, _rel_path, source="filesystem")
                    if parsed is not None:
                        return {"parsed": parsed, "name": _fname, "rel": _rel_path}
                except Exception as e:
                    return {"error": str(e), "rel": _rel_path}
                return None

            _max_workers = min(4, (os.cpu_count() or 4) // 2)
            _parsed_list: list = []
            _parse_errors = []

            with ThreadPoolExecutor(max_workers=_max_workers) as _exec:
                _futs = [_exec.submit(_parse_worker, (idx, root, fname, fpath))
                         for idx, (root, fname, fpath) in enumerate(all_files)]
                for i, fut in enumerate(_futs):
                    try:
                        res = fut.result()
                        if res:
                            if "error" in res:
                                _parse_errors.append((res["rel"], res["error"]))
                            else:
                                _parsed_list.append(res)
                                if watchdog_heartbeat:
                                    watchdog_heartbeat(f"parse:{res['name']}")
                    except Exception as e:
                        logger.warning(f"Worker error: {e}")

                    if i % max(1, total_files // 20) == 0 or i == total_files - 1:
                        if progress_callback:
                            progress_callback("", i + 1, total_files, "parsing")
                        _notify_progress(i + 1, total_files, "parsing", "", 5, 50)

            parsed_count = len(_parsed_list)
            logger.info(f"Parse complete: {parsed_count}/{total_files} files changed")

            if parsed_count == 0:
                logger.info("No changes — index is current")
                if prune_deleted_files:
                    self._safe_prune(prune_deleted_files, current_files_on_disk)
                if self.searcher:
                    self.searcher.reindex()
                if progress_callback:
                    progress_callback("", total_files, total_files, "complete")
                return 0

            # Phase 2: Sort + Batch Embed
            _flat_chunks: list = [(fp_idx, text) for fp_idx, fp_data in enumerate(_parsed_list)
                                  for text in fp_data["parsed"]["chunk_texts"]]
            total_chunks = len(_flat_chunks)
            logger.info(f"Total chunks: {total_chunks}, batch_size={BATCH_SIZE}")

            _flat_chunks.sort(key=lambda x: len(x[1]))

            if not getattr(self.embedder, 'is_ready', lambda: True)():
                logger.error("Embedder not ready. Indexing aborted.")
                return 0

            _all_embeddings: list = [None] * total_chunks
            _embed_t0 = time.time()

            for batch_start in range(0, total_chunks, BATCH_SIZE):
                batch_end = min(batch_start + BATCH_SIZE, total_chunks)
                batch_data = _flat_chunks[batch_start:batch_end]
                batch_texts = [text for (_, text) in batch_data]

                t0 = time.time()
                try:
                    embeddings = self.embedder.embed_batch(batch_texts)
                except Exception as embed_err:
                    logger.error(f"Embedder error: {embed_err}. Aborted.")
                    raise RuntimeError(f"Embedder unavailable: {embed_err}. Aborted.") from embed_err

                embed_time = time.time() - t0
                if not embeddings or len(embeddings) != len(batch_texts):
                    raise RuntimeError(
                        f"Embedder returned {len(embeddings) if embeddings else 0} vectors "
                        f"instead of {len(batch_texts)} — aborted."
                    )

                for i, flat_idx in enumerate(range(batch_start, batch_end)):
                    _all_embeddings[flat_idx] = embeddings[i]

                if batch_start % (BATCH_SIZE * 5) == 0 or batch_end >= total_chunks:
                    elapsed = time.time() - _embed_t0
                    done = min(batch_end, total_chunks)
                    speed = done / elapsed if elapsed > 0 else 0
                    logger.info(
                        f"[embed] {done}/{total_chunks} "
                        f"batch={len(batch_texts)}ch/{embed_time:.1f}s={len(batch_texts)/max(embed_time,0.001):.0f}ch/s "
                        f"avg={speed:.0f}ch/s elapsed={elapsed:.0f}s"
                    )
                    _notify_progress(done, total_chunks, "embedding", "", 50, 40)
                    if watchdog_heartbeat:
                        watchdog_heartbeat(f"embed:{done}/{total_chunks}")
                gc.collect()

            _embed_total = time.time() - _embed_t0
            logger.info(f"Embed complete: {total_chunks} in {_embed_total:.1f}s "
                        f"({total_chunks/max(_embed_total,0.001):.0f} ch/s)")
            _notify_progress(total_chunks, total_chunks, "writing", "", 90, 10)

            # Phase 3: Write Results (с self-healing от Not Found)
            _file_embeddings: dict = {}
            for flat_idx, (fp_idx, _) in enumerate(_flat_chunks):
                if fp_idx not in _file_embeddings:
                    _file_embeddings[fp_idx] = {"parsed": _parsed_list[fp_idx]["parsed"], "vecs": []}
                _file_embeddings[fp_idx]["vecs"].append(_all_embeddings[flat_idx])

            indexed_count = 0
            for fp_idx, fdata in _file_embeddings.items():
                for attempt in range(2):
                    try:
                        if self._write_file_records(fdata["parsed"], fdata["vecs"]):
                            indexed_count += 1
                        break  # успех — выходим из retry-цикла
                    except Exception as e:
                        if attempt == 0 and self._reset_table_if_not_found(e, "write_file_records", attempt):
                            continue
                        logger.warning(f"Write error {fdata['parsed']['rel_path']} (attempt {attempt+1}/2): {e}")
                        break

                if watchdog_heartbeat:
                    watchdog_heartbeat(f"write:{Path(fdata['parsed']['rel_path']).name}")

            logger.info(f"Write complete: {indexed_count} files")
            if progress_callback:
                progress_callback("", total_files, total_files, "indexing")

            time.sleep(1)  # Windows flush

            # Prune (с self-healing от Not Found)
            pruned = 0
            if prune_deleted_files:
                pruned = self._safe_prune(prune_deleted_files, current_files_on_disk)

            # BM25 reindex
            if indexed_count > 0 and self.searcher:
                if progress_callback:
                    progress_callback("", total_files, total_files, "rebuilding_bm25")
                self.searcher.reindex()

            # IVF index
            if self.table:
                _row_count = self.table.count_rows()
                if _row_count > 1000:
                    self._safe_ivf_index()

            final_stats = get_status() if get_status else {}
            if progress_callback:
                progress_callback("", total_files, total_files, "complete")

            if self.summarizer:
                self.summarizer.save_cache()

            if save_symbol_index:
                save_symbol_index()

            logger.info(
                f"Indexing complete: {indexed_count} new/changed, "
                f"{pruned} removed, total {final_stats.get('total_chunks', 0)} chunks"
            )
            return indexed_count

    def _safe_prune(self, prune_deleted_files: Callable, current_files_on_disk: Set[str]) -> int:
        """Prune с self-healing от Not Found (LanceDB race)."""
        for attempt in range(2):
            try:
                pruned = prune_deleted_files(current_files_on_disk)
                if pruned > 0:
                    logger.info(f"Pruned {pruned} stale files")
                return pruned
            except Exception as e:
                if attempt == 0 and self._reset_table_if_not_found(e, "prune", attempt):
                    continue
                logger.warning(f"Prune failed (attempt {attempt+1}/2): {e}")
                return 0
        return 0

    def _safe_ivf_index(self):
        """IVF index с self-healing от Not Found."""
        # Phase 1: optimize
        def _safe_optimize():
            for attempt in range(2):
                try:
                    _opt_ex = ThreadPoolExecutor(max_workers=1)
                    try:
                        _opt_ex.submit(self.table.optimize).result(timeout=300)
                    except Exception as _opt_to:
                        logger.warning(
                            f"Table optimize exceeded 300s timeout "
                            f"(continuing to wait for completion): {_opt_to}"
                        )
                    finally:
                        _opt_ex.shutdown(wait=True)
                    return True
                except Exception as e:
                    if attempt == 0 and self._reset_table_if_not_found(e, "optimize", attempt):
                        continue
                    logger.warning(f"Table optimize failed (non-critical): {e}")
                    return False
            return False

        if not _safe_optimize():
            logger.warning("Optimize failed after retries, skipping index creation")
            return

        # Drop old indices
        try:
            for idx in self.table.list_indices():
                idx_name = getattr(idx, "name", None)
                if idx_name:
                    self.table.drop_index(idx_name)
        except Exception as _drop_err:
            logger.debug(f"Drop old index (non-critical): {_drop_err}")

        # Phase 2: create IVF_FLAT index
        def _safe_create_index():
            for attempt in range(2):
                try:
                    self.table.create_index(
                        "vector",
                        index_type="IVF_FLAT",
                        metric="cosine",
                        replace=True,
                    )
                    logger.info("IVF_FLAT index created")
                    return True
                except TypeError:
                    # Fallback to legacy positional API (< 0.33)
                    try:
                        self.table.create_index(
                            metric="cosine", vector_column_name="vector",
                            index_type="IVF_FLAT", replace=True,
                        )
                        logger.info("IVF_FLAT index created (legacy API)")
                        return True
                    except Exception as _legacy_e:
                        logger.warning(f"Legacy create_index failed: {_legacy_e}")
                        raise
                except Exception as e:
                    if attempt == 0 and self._reset_table_if_not_found(e, "create_index", attempt):
                        continue
                    logger.warning(f"create_index failed (non-critical): {e}")
                    return False
            return False

        if not _safe_create_index():
            logger.warning("create_index failed after retries")


def threading_lock_context():
    """Fallback: если db_manager нет — используем простой threading.Lock."""
    import threading
    return threading.Lock()
