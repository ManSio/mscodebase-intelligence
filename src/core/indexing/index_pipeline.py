"""
IndexPipeline — ядро пайплайна индексации одного файла.

Выделено из Indexer._index_single_file + _parse_file_only (Фаза 2).
Отвечает за:
- AST-парсинг через CodeParser (с fallback на символьное деление)
- Эмбеддинг чанков через embedder
- Обновление SymbolIndex (definitions, references, assignments)
- Code Health scoring
- Возврат готовых данных для записи в LanceDB

Не содержит:
- Логику открытия/закрытия таблиц (LanceDBManager)
- Логику записи в LanceDB (_write_file_records)
- Логику переключения проектов
"""

from __future__ import annotations

import gc
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

__all__ = [
    "IndexPipeline",
]
logger = logging.getLogger("mscodebase_server.index_pipeline")


class IndexPipeline:
    """Пайплайн: файл -> AST-чанки -> эмбеддинги -> готовые записи."""

    def __init__(
        self,
        embedder,
        parser,
        symbol_index,
        symbol_index_lock,
        project_path: Path,
    ):
        self.embedder = embedder
        self.parser = parser
        self._symbol_index = symbol_index
        self._symbol_index_lock = symbol_index_lock
        self.project_path = project_path

    def process_file(
        self,
        rel_path_str: str,
        full_path: Path,
        content: str,
        current_hash: str,
        source: str = "filesystem",
    ) -> Optional[Dict[str, Any]]:
        """Обрабатывает один файл: парсинг -> эмбеддинг.

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

        # Очистка старых данных из PropertyGraph
        if hasattr(self._symbol_index, "graph"):
            pg = self._symbol_index.graph
            if pg:
                rel_posix = rel_path_str.replace("\\", "/")
                pg.remove_file(rel_posix)

        # AST-aware чанкинг
        chunk_texts: List[str] = []
        chunk_texts_full: List[str] = []
        chunk_metadatas: List[Dict] = []
        health = {"score": 0.0, "band": ""}

        chunk_texts, chunk_texts_full, chunk_metadatas = self._parse_chunks(
            rel_path_str=rel_path_str,
            full_path=full_path,
            content=content,
        )
        if not chunk_texts:
            return None

        # Code Health
        try:
            from src.core.code_health import score_file
            health = score_file(rel_path_str, self.project_path)
        except Exception:
            pass

        # Embedding
        embeddings = self.embedder.embed_batch(chunk_texts)
        gc.collect()
        if not embeddings or any(len(e) == 0 for e in embeddings):
            logger.warning(
                f"Empty embeddings for {rel_path_str}. Skipping."
            )
            return None

        return {
            "rel_path": rel_path_str,
            "current_hash": current_hash,
            "chunk_texts": chunk_texts,
            "chunk_texts_full": chunk_texts_full,
            "chunk_metadatas": chunk_metadatas,
            "health": health,
            "source": source,
            "embeddings": embeddings,
        }

    def parse_file_only(
        self,
        full_path: Path,
        rel_path_str: str,
        source: str = "filesystem",
    ):
        """Parse only (no embedding). Returns dict for write or None."""
        try:
            safe_path = full_path
            if not safe_path.exists():
                return None
            with open(str(safe_path), "rb") as f:
                raw_data = f.read()
            content = raw_data.decode("utf-8", errors="replace")
            if not content.strip():
                return None
            import hashlib
            current_hash = hashlib.md5(content.encode("utf-8")).hexdigest()
            escaped_path = rel_path_str.replace("'", "''")

            # Parse chunks (same logic as process_file but without embedding)
            chunk_texts, chunk_texts_full, chunk_metadatas, health = self._parse_chunks(
                rel_path_str=rel_path_str,
                full_path=full_path,
                content=content,
            )
            if not chunk_texts:
                return None

            health_score = {"score": 0.0, "band": ""}
            try:
                from src.core.code_health import score_file
                health_score = score_file(rel_path_str, self.project_path)
            except Exception:
                pass

            return {
                "rel_path": rel_path_str,
                "current_hash": current_hash,
                "escaped_path": escaped_path,
                "existing_hash": None,
                "chunk_texts": chunk_texts,
                "chunk_texts_full": chunk_texts_full,
                "chunk_metadatas": chunk_metadatas,
                "health": health_score,
                "source": source,
            }
        except Exception as e:
            logger.warning(f"Parse failed {rel_path_str}: {e}")
            return None

    def _parse_chunks(self, rel_path_str, full_path, content):
        """Common chunking logic used by both process_file and parse_file_only."""
        chunk_texts = []
        chunk_texts_full = []
        chunk_metadatas = []

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
                logger.warning(f"AST chunking failed for {rel_path_str}, fallback: {ast_err}")
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

        return chunk_texts, chunk_texts_full, chunk_metadatas
