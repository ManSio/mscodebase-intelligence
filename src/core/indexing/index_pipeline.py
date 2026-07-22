"""
IndexPipeline — ядро пайплайна индексации одного файла.

Выделено из Indexer._index_single_file + _parse_file_only (Фаза 2).
Отвечает за:
- AST-парсинг через IndexParser (делегировано)
- Эмбеддинг чанков через embedder
- Обновление SymbolIndex (definitions, references, assignments)
- Возврат готовых данных для записи в LanceDB

Не содержит:
- Логику открытия/закрытия таблиц (LanceDBManager)
- Логику записи в LanceDB (LanceDBWriter)
- Логику переключения проектов
- Собственный парсинг (использует IndexParser)
"""

from __future__ import annotations

import gc
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.indexing.indexer_table import IndexerTableMixin

__all__ = [
    "IndexPipeline",
]
logger = logging.getLogger("mscodebase_server.index_pipeline")


class IndexPipeline:
    """Пайплайн: файл -> IndexParser -> эмбеддинги -> готовые записи."""

    def __init__(
        self,
        embedder,
        parser,
        index_parser,
        symbol_index,
        symbol_index_lock,
        project_path: Path,
        table=None,
    ):
        self.embedder = embedder
        self.parser = parser
        self._index_parser = index_parser
        self._symbol_index = symbol_index
        self._symbol_index_lock = symbol_index_lock
        self.project_path = project_path
        # Опциональная ссылка на LanceDB table для chunk-level кэша.
        # Если None — кэш отключён (embed_batch всегда вызывается).
        self._table = table

    def process_file(
        self,
        rel_path_str: str,
        full_path: Path,
        content: str,
        current_hash: str,
        source: str = "filesystem",
    ) -> Optional[Dict[str, Any]]:
        """Обрабатывает один файл: IndexParser -> эмбеддинг.

        Args:
            rel_path_str: относительный путь (src/core/indexer.py)
            full_path: полный путь на диске
            content: содержимое файла
            current_hash: MD5-хэш содержимого
            source: источник ('filesystem' | 'lsp_vfs')

        Returns:
            dict с parsed + embeddings для записи в LanceDB,
            или None при ошибке.
        """
        if not content.strip():
            return None

        # Парсинг через IndexParser (с AST-кэшем)
        parsed = self._index_parser.parse_file(
            full_path=full_path,
            rel_path_str=rel_path_str,
            source=source,
        )
        if parsed is None:
            return None

        # SymbolIndex из AST-кэша (без повторного парсинга)
        _ast_chunks, symbols = parsed.get("_ast_symbols", (None, None))
        if symbols and self.parser is not None:
            try:
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

        # Embedding
        chunk_texts = parsed.get("chunk_texts", [])
        if not chunk_texts:
            return None

        # ─── Chunk-level content-addressed cache ───────────
        # Вычисляем chunk_hash для каждого чанка. Если хэш уже есть в БД,
        # переиспользуем сохранённый вектор (skip embed_batch).
        # Это даёт ~95% экономии повторных эмбеддингов при правке 1 функции
        # (подтверждено бенчмарком в sandbox/chunk_hash_exp/).
        import hashlib

        chunk_hashes = []
        for t in chunk_texts:
            h = "ch:" + hashlib.sha256(t.encode("utf-8")).hexdigest()[:32]
            chunk_hashes.append(h)

        # Загружаем известные векторы из БД (если table доступен)
        known_vectors: dict = {}
        if self._table is not None:
            try:
                _existing = (
                    self._table.search()
                    .where(f"file_path = '{IndexerTableMixin._escape_sql_value(rel_path_str)}'", prefilter=True)
                    .select(["chunk_hash", "vector"])
                    .to_pandas()
                )
                if not _existing.empty and "chunk_hash" in _existing.columns:
                    for _, _row in _existing.iterrows():
                        _ch = str(_row.get("chunk_hash", ""))
                        if _ch:
                            known_vectors[_ch] = _row["vector"]
            except Exception as _cache_err:
                logger.debug(f"Chunk cache load failed: {_cache_err}")

        # Разделяем на новые (нужен embed) и кэшированные (вектор из БД)
        texts_to_embed = []
        embed_idx_map = []  # индекс в chunk_texts -> позиция в texts_to_embed
        cached_vectors = [None] * len(chunk_texts)
        for i, (t, h) in enumerate(zip(chunk_texts, chunk_hashes)):
            if h in known_vectors:
                cached_vectors[i] = known_vectors[h]
            else:
                texts_to_embed.append(t)
                embed_idx_map.append(i)

        # Эмбеддим только новые чанки
        if texts_to_embed:
            new_embeddings = self.embedder.embed_batch(texts_to_embed)
            gc.collect()
            if not new_embeddings or any(len(e) == 0 for e in new_embeddings):
                logger.warning(f"Empty embeddings for {rel_path_str}. Skipping.")
                return None
            for pos, vec_idx in enumerate(embed_idx_map):
                cached_vectors[vec_idx] = new_embeddings[pos]

        embeddings = cached_vectors
        if any(v is None for v in embeddings):
            logger.warning(f"Chunk cache gap for {rel_path_str}. Skipping.")
            return None

        return {
            "rel_path": rel_path_str,
            "current_hash": current_hash,
            "chunk_texts": parsed["chunk_texts"],
            "chunk_texts_full": parsed.get("chunk_texts_full", []),
            "chunk_metadatas": parsed.get("chunk_metadatas", []),
            "chunk_hashes": chunk_hashes,
            "health": parsed.get("health", {"score": 0.0, "band": ""}),
            "source": source,
            "embeddings": embeddings,
        }

    def parse_file_only(
        self,
        full_path: Path,
        rel_path_str: str,
        source: str = "filesystem",
    ):
        """Parse only (no embedding). Delegated to IndexParser.

        Сохранён для обратной совместимости. Новый код использует
        IndexParser напрямую.
        """
        return self._index_parser.parse_file(
            full_path=full_path,
            rel_path_str=rel_path_str,
            source=source,
        )
