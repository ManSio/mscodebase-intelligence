"""
LanceDBWriter — запись чанков в LanceDB (delete old + add new + cache sync).

Выделено из Indexer._write_file_records (Фаза 5).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any, Dict, List

__all__ = [
    "LanceDBWriter",
]
logger = logging.getLogger("mscodebase_server.db_writer")


class LanceDBWriter:
    """Управляет записью чанков в LanceDB с атомарностью и кэш-синхронизацией."""

    def __init__(self, table, table_write_lock, index_lock, embedder):
        self.table = table
        self._table_write_lock = table_write_lock
        self._index_lock = index_lock
        self.embedder = embedder

    def write_records(
        self,
        parsed: Dict[str, Any],
        embeddings: List[List[float]],
        summarizer=None,
        enable_summaries: bool = False,
        parser=None,
    ) -> list:
        """Собирает data_records и пишет в LanceDB. Возвращает records."""
        rel_path_str = parsed["rel_path"]
        current_hash = parsed["current_hash"]
        escaped_path = parsed.get("escaped_path", rel_path_str)
        existing_hash = parsed.get("existing_hash")
        chunk_texts = parsed["chunk_texts"]
        chunk_hashes = parsed.get("chunk_hashes", [])
        chunk_texts_full = parsed.get("chunk_texts_full", [])
        chunk_metadatas = parsed.get("chunk_metadatas", [])
        health = parsed.get("health", {})
        source = parsed.get("source", "filesystem")

        if not embeddings or len(embeddings) != len(chunk_texts):
            logger.warning(
                f"Embedding count mismatch for {rel_path_str}: "
                f"{len(embeddings)} vs {len(chunk_texts)}"
            )
            return []

        _target_dim = self.embedder.embedding_dim or 768
        for i, vec in enumerate(embeddings):
            if len(vec) != _target_dim:
                embeddings[i] = vec[:_target_dim] + [0.0] * (_target_dim - len(vec))
            # Guard: проверка нормы вектора (если norm=0, эмбеддер не работал)
            _norm_sq = sum(v*v for v in embeddings[i])
            if _norm_sq < 1e-9:
                logger.warning(f"Zero vector for chunk {i} in {rel_path_str} "
                              f"(text={repr(chunk_texts[i])[:100]}))")
                # Не возвращаем [] — записываем как есть, чтобы индекс построился.
                # Позже re-embed заменит нулевые векторы.

        for i in range(len(chunk_texts)):
            if i >= len(chunk_texts_full) or not chunk_texts_full[i]:
                chunk_texts_full.append(chunk_texts[i])

        data_records = []
        for i, (chunk_text, chunk_vec) in enumerate(zip(chunk_texts, embeddings)):
            full_text = chunk_texts_full[i] if i < len(chunk_texts_full) else chunk_text
            summary = ""
            if summarizer and enable_summaries:
                symbol_name = ""
                if parser and hasattr(parser, "_current_symbol"):
                    symbol_name = getattr(parser, "_current_symbol", "")
                summary = summarizer.summarize_chunk(chunk_text, symbol_name)

            meta = chunk_metadatas[i] if i < len(chunk_metadatas) else {}
            data_records.append({
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
                "chunk_hash": chunk_hashes[i] if i < len(chunk_hashes) else "",
            })

        # Atomic write: delete old + add new
        with self._table_write_lock:
            if existing_hash is not None:
                try:
                    self.table.delete(f"file_path = '{escaped_path}'")
                except Exception as del_err:
                    logger.debug(f"delete failed: {del_err}")

            try:
                self.table.add(data_records)
            except Exception as add_err:
                err_str = str(add_err).lower()
                if "not found" in err_str or "does not exist" in err_str or "no such table" in err_str:
                    logger.warning(f"Table not found, recreating: {add_err}")
                    if self._safe_recreate_table():
                        self.table.add(data_records)
                    else:
                        raise
                else:
                    raise

        return data_records

    def _safe_recreate_table(self):
        """Fallback: удалить и пересоздать таблицу при потере.
        
        После пересоздания обновляет self.table на актуальный объект
        и вызывает on_recreate callback (если есть) для синхронизации
        ссылок в Indexer и IndexProjectRunner.
        """
        try:
            schema = self.table.schema
            self.table.db.drop_table("codebase_chunks")
            self.table = self.table.db.create_table("codebase_chunks", schema=schema)
            logger.info("✅ Таблица пересоздана (fresh schema)")
            # Оповещаем внешние компоненты о новом объекте таблицы
            if hasattr(self, '_on_recreate') and self._on_recreate:
                try:
                    self._on_recreate(self.table)
                except Exception as cb_err:
                    logger.warning(f"on_recreate callback failed: {cb_err}")
            return True
        except Exception as e:
            logger.error(f"Table recreation failed: {e}")
            return False

    def set_on_recreate_callback(self, callback):
        """Устанавливает callback, который вызывается после пересоздания таблицы.
        
        Позволяет Indexer/IndexProjectRunner синхронизировать свою ссылку self.table
        с новым объектом таблицы после _safe_recreate_table().
        """
        self._on_recreate = callback
