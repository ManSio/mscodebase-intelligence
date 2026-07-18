"""
IndexParser — чистый парсер: чтение файла → AST-чанкинг → возврат данных.

Ничего не знает о БД (LanceDB), SymbolIndex или эмбеддингах.
Может быть переиспользован в Indexer, IndexPipeline и в отдельном
воркере для параллельного парсинга.

Выделено из Indexer._parse_file_only (Фаза 6 декомпозиции God-Object).
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

__all__ = [
    "IndexParser",
]
logger = logging.getLogger("mscodebase_server.index_parser")


class IndexParser:
    """Чистый парсер: читает файл → AST-чанкинг → возвращает данные.

    Не содержит:
    - Логику проверки хэша через БД (existing_hash передаётся снаружи)
    - Логику обновления SymbolIndex
    - Эмбеддинг
    - Запись в LanceDB

    Пример:
        parser = IndexParser(code_parser, path_manager, project_path)
        result = parser.parse_file(
            full_path=Path("src/main.py"),
            rel_path_str="src/main.py",
            existing_hash="abc123",
        )
        if result:
            # result["chunk_texts"], result["health"], ...
            pass
    """

    def __init__(
        self,
        parser,
        path_manager,
        project_path: Path,
    ):
        self.parser = parser
        self.path_manager = path_manager
        self.project_path = project_path

    def parse_file(
        self,
        full_path: Path,
        rel_path_str: str,
        source: str = "filesystem",
        existing_hash: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Только парсинг файла (без эмбеддинга и записи в БД).

        Args:
            full_path: Абсолютный путь к файлу
            rel_path_str: Относительный путь (src/core/indexer.py)
            source: Источник ('filesystem' | 'lsp_vfs')
            existing_hash: MD5 хэш предыдущей версии из БД (если известен).
                Передаётся снаружи — парсер не ходит в БД.

        Returns:
            Dict с данными чанков или None если файл не изменился.
            Структура: {
                "rel_path": str, "current_hash": str,
                "existing_hash": str | None,
                "chunk_texts": List[str],
                "chunk_texts_full": List[str],
                "chunk_metadatas": List[Dict],
                "health": Dict, "source": str
            }
        """
        try:
            safe_read_path = self.path_manager.get_safe_path(full_path)
            with open(str(safe_read_path), "rb") as f:
                raw_data = f.read()
            content = raw_data.decode("utf-8", errors="replace")

            current_hash = hashlib.md5(content.encode("utf-8")).hexdigest()

            # Хэш не изменился — пропускаем
            if existing_hash == current_hash:
                return None

            if not content.strip():
                return None

            # AST-чанкинг + Breadcrumbs
            chunk_texts: List[str] = []
            chunk_texts_full: List[str] = []
            chunk_metadatas: List[Dict] = []
            health = {"score": 0.0, "band": ""}
            _ast_symbols_cache = (None, None)

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
                                _header = f"// Scope: {_scope}\n"
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
                                    "start_line": c.get("start_line", 0),
                                    "end_line": c.get("end_line", 0),
                                })
                    # Сохраняем AST-результат для SymbolIndex (без повторного парсинга)
                    _ast_symbols_cache = (ast_chunks, symbols)
                except Exception as ast_err:
                    logger.warning(
                        f"⚠️ AST-чанкинг не удался для {rel_path_str}: {ast_err}"
                    )
                    chunk_texts = []
                    chunk_metadatas = []

            # Fallback: символьное деление если AST не дал чанков
            if not chunk_texts:
                _fb_header = f"// Scope: fallback | {Path(rel_path_str).name}\n"
                chunk_texts = [
                    _fb_header + content[i : i + 1000]
                    for i in range(0, len(content), 800)
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
            except Exception:
                pass

            return {
                "rel_path": rel_path_str,
                "current_hash": current_hash,
                "existing_hash": existing_hash,
                "chunk_texts": chunk_texts,
                "chunk_texts_full": chunk_texts_full,
                "chunk_metadatas": chunk_metadatas,
                "health": health,
                "source": source,
                "_ast_symbols": _ast_symbols_cache,
            }

        except Exception as e:
            logger.warning(f"⚠️ Ошибка парсинга {rel_path_str}: {e}")
            return None
