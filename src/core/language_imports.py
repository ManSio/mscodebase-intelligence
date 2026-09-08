"""language_imports.py — извлечение импортов из tree-sitter-дерева (Вариант A).

Возрождение IMPORT_NODE_MAP: был в parser.py с 17.07.2026 (v3.3.0, 20 языков,
commit 142761d), удалён рефакторингом к 04.08.2026 — claim «20 языков» в
CHANGELOG разошёлся с кодом (закрыто 24.08.2026).

ЕДИНЫЙ ИСТОЧНИК ИСТИНЫ по node-типам импортов — CodeParser.IMPORT_NODE_MAP
(parser.py, B3-карты, сверены с живыми грамматиками 2026-08-18).
LANGUAGE_IMPORT_NODES ниже — ПРОИЗВОДНАЯ (ext→lang через _EXT_TO_LANG),
литерала карты здесь больше нет; расхождение ловит TestMapConsistency
в tests/test_language_imports.py.

Экстрактор ЧИСТЫЙ и duck-typed: работает с любым деревом, у которого есть
node.type / node.children / node.text — поэтому тестируется синтетикой БЕЗ
tree-sitter (герметичность). Реальные грамматики (tree-sitter-language-pack,
+56 языков) скачиваются по сети при первом использовании — это вне юнит-тестов.

Два режима:
  1. Точный: node-типы из LANGUAGE_IMPORT_NODES (производной от IMPORT_NODE_MAP).
  2. Fallback: для языков без карты — любой node, чей тип содержит
     'import'/'use'/'include' (best-effort, никогда не падает — Negative control).
     Активен ТОЛЬКО при MSCODEBASE_LANGUAGE_PACK=true; реальный путь parser.py
     (_extract_fallback_imports) вызывает его только когда точная карта для
     расширения отсутствует — при доступном основном grammar-пути fallback
     не запускается никогда.

Гейт включения — как у language_pack.py: MSCODEBASE_LANGUAGE_PACK=true
(единая точка чтения флага — language_pack.is_enabled()).
"""

from __future__ import annotations

import logging
from typing import Dict, List, Sequence

from src.core.language_pack import is_enabled as _pack_enabled

__all__ = [
    "extract_imports",
    "extract_imports_from_file",
    "iter_import_candidate_nodes",
    "LANGUAGE_IMPORT_NODES",  # noqa: F822 — ленивый lazy-export через module __getattr__ (PEP 562)
    "known_languages",
]

logger = logging.getLogger(__name__)

# Каноническое соответствие расширение → имя языка. Обслуживает и деривацию
# карты из parser.IMPORT_NODE_MAP, и _lang_for_ext — второй копии быть не должно.
_EXT_TO_LANG: Dict[str, str] = {
    ".py": "python", ".rs": "rust", ".js": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "tsx", ".vue": "vue", ".go": "go",
    ".java": "java", ".cs": "csharp", ".rb": "ruby", ".php": "php",
    ".kt": "kotlin", ".swift": "swift", ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp",
    ".scala": "scala", ".dart": "dart", ".sh": "bash", ".bash": "bash",
    ".m": "objectivec",
}


def _derive_language_import_nodes() -> Dict[str, tuple[str, ...]]:
    """Строит LANGUAGE_IMPORT_NODES из CodeParser.IMPORT_NODE_MAP (B3).

    ВЫЗЫВАЕТСЯ ТОЛЬКО лениво (module __getattr__) при первом обращении,
    НИКОГДА при загрузке модуля — иначе статический цикл
    parser ⇄ language_imports (architecture_linter, _ALLOWED_CORE_CYCLES).
    Ext без маппинга в _EXT_TO_LANG пропускается с warning; полноту покрытия
    закрепляет консистентный тест.
    """
    from src.core.indexing.parser import CodeParser

    merged: Dict[str, set] = {}
    for ext, types in CodeParser.IMPORT_NODE_MAP.items():
        lang = _EXT_TO_LANG.get(ext)
        if lang is None:
            logger.warning("language_imports: ext %s без маппинга _EXT_TO_LANG", ext)
            continue
        merged.setdefault(lang, set()).update(types)
    return {lang: tuple(sorted(types)) for lang, types in sorted(merged.items())}


# Язык -> node-типы tree-sitter, представляющие импорты (производная, см. выше).
# ЛЕНИВАЯ: первый доступ (module __getattr__, PEP 562) деривирует карту из
# CodeParser.IMPORT_NODE_MAP. При загрузке модуля parser НЕ импортируется —
# иначе статический цикл parser ⇄ language_imports (architecture_linter).
# Число синхронизировано с _ALLOWED_CORE_CYCLES (scripts/architecture_linter.py).
_LANGUAGE_IMPORT_NODES_CACHE: Dict[str, tuple[str, ...]] | None = None


def _get_language_import_nodes() -> Dict[str, tuple[str, ...]]:
    global _LANGUAGE_IMPORT_NODES_CACHE
    if _LANGUAGE_IMPORT_NODES_CACHE is None:
        _LANGUAGE_IMPORT_NODES_CACHE = _derive_language_import_nodes()
    return _LANGUAGE_IMPORT_NODES_CACHE


def __getattr__(name: str):
    if name == "LANGUAGE_IMPORT_NODES":
        return _get_language_import_nodes()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

# Импорт НЕ должен содержать эти слова (ключевые слова/служебные имена).
_IMPORT_KEYWORDS = frozenset(
    {
        "import", "from", "as", "require", "use", "pub", "mod", "crate", "self",
        "super", "export", "default", "include", "source", "using", "namespace",
        "static", "fn", "const", "let", "var", "new", "extends", "if", "else",
    }
)

_FALLBACK_SUBSTR = ("import", "use", "include")


def _fallback_type_match(ntype: str) -> bool:
    """Подстрочный критерий fallback-режима 2 (одно определение на модуль)."""
    return any(s in ntype for s in _FALLBACK_SUBSTR)


def _iter_nodes(node) -> Sequence:
    """Обход узлов. Реальный tree-sitter даёт объект TREE (дети в .root_node),
    fake-узлы — сами родители (.children). Унифицируем через root_node.
    """
    root = getattr(node, "root_node", None)
    start = root if root is not None else node
    yield start
    for child in getattr(start, "children", ()) or ():
        yield from _iter_nodes(child)


def _is_import_node(node, lang: str) -> bool:
    ntype = str(getattr(node, "type", "") or "")
    targets = _get_language_import_nodes().get(lang)
    if targets:
        if ntype not in targets:
            return False
        if lang == "ruby" and ntype == "call":
            # Только require/require_relative, не произвольные вызовы
            return any(
                str(getattr(ch, "text", "") or "") in ("require", "require_relative")
                for ch in getattr(node, "children", ()) or ()
            )
        return True
    # Fallback для неизвестных языков: best-effort по имени node-типа.
    # Гейт: ТОЛЬКО при MSCODEBASE_LANGUAGE_PACK (докстринг модуля) — без флага
    # незнакомый язык даёт пустой результат (негативный тест закреплён).
    if not _pack_enabled():
        return False
    return _fallback_type_match(ntype)


def iter_import_candidate_nodes(tree):
    """Узлы-кандидаты fallback-режима 2 для реального пути parser.py.

    CodeParser._extract_fallback_imports вызывает это ТОЛЬКО для ext без
    точной карты (IMPORT_NODE_MAP) — основной grammar-путь всегда приоритетен.
    Пустой генератор при выключенном MSCODEBASE_LANGUAGE_PACK
    (language_pack.is_enabled).
    """
    if not _pack_enabled():
        return
    for node in _iter_nodes(tree):
        if _fallback_type_match(str(getattr(node, "type", "") or "")):
            yield node


# Листья, из которых собирается имя модуля. Обычные 'identifier' НЕ входят:
# в python from-import {defaultdict} и в js import {x} символы не должны
# приклеиваться к имени модуля (модуль = 'collections' / 'pkg', не 'collections.defaultdict').
_LEAF_TYPES = (
    "dotted_name", "scoped_identifier", "string", "string_fragment",
    "import_prefix", "module", "name", "path", "namespace",
)

# Subtree, внутри которых лежат ИМЕНА из списка импорта, а не модуль:
# python import_list / aliased_import, js import_clause. Не спускаемся туда.
_SKIP_SUBTREES = frozenset({"import_list", "aliased_import", "import_clause"})


def _leaf_text(child) -> str:
    """Текст узла с декодированием байт (tree-sitter отдаёт bytes, не str).

    str(b'ast') → "b'ast'" — реальная ошибка фиделити, вскрыта живым
    прогоном с tree-sitter-language-pack (fake-деревья давали str).
    """
    raw = getattr(child, "text", "") or ""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    return str(raw).strip().strip('\"\'')


def _module_names(node) -> List[str]:
    """Имена модулей из узла импорта — по одному на каждый собирающий лист.

    Склейка листьев НЕ выполняется: go-block import ("os"; "strings") даёт
    два имени, python from-import (dotted 'collections' вне import_list) —
    одно (модуль), а не 'collections.defaultdict'.
    """

    def walk(n):
        yield n
        for ch in getattr(n, "children", ()) or ():
            if str(getattr(ch, "type", "") or "") in _SKIP_SUBTREES:
                continue  # имена из списка импорта — не модуль
            yield from walk(ch)

    names: List[str] = []
    for child in walk(node):
        ctype = str(getattr(child, "type", "") or "")
        if ctype not in _LEAF_TYPES:
            continue
        text = _leaf_text(child)
        if not text:
            continue
        if len(text) == 1 and text in (".", "/", "\\"):
            continue
        if text in _IMPORT_KEYWORDS:
            continue
        names.append(text)
    return names


def extract_imports(tree, lang: str = "python") -> List[str]:
    """Имена импортируемых модулей из дерева. Никогда не бросает исключений.

    >>> class N:  # минимальный fake-node для тестов
    ...     def __init__(self, type, text="", children=()):
    ...         self.type, self.text, self.children = type, text, children
    """
    lang = (lang or "python").lower().replace(".", "")
    results: List[str] = []
    try:
        for node in _iter_nodes(tree):
            if not _is_import_node(node, lang):
                continue
            for name in _module_names(node):
                if name:
                    results.append(name)
    except Exception:  # noqa: BLE001 — Negative control: экзотический синтаксис
        return []
    # дедупликация с сохранением порядка
    return list(dict.fromkeys(results))


def extract_imports_from_file(
    file_path: str,
    lang: str | None = None,
    parser_provider=None,
) -> List[str]:
    """Тонкий интеграционный мост: file → tree-sitter-дерево → имени модулей.

    parser_provider: callable(file_path, lang) -> (tree, detected_lang) | None.
    По умолчанию — дерево из tree_sitter_language_pack, если флаг
    MSCODEBASE_LANGUAGE_PACK включён и пакет установлен (кэшируется как в
    language_pack.try_enable). Для юнит-тестов передаём фейк-провайдера —
    сам мост остаётся герметичным.
    """
    from pathlib import Path

    if lang is None:
        lang = _lang_for_ext(Path(file_path).suffix)
    if parser_provider is None:
        # Единый гейт флага (language_pack.is_enabled) — дубля чтения env нет.
        if not _pack_enabled():
            return []
        parser_provider = _default_parser_provider
    try:
        parsed = parser_provider(file_path, lang)
    except Exception:  # noqa: BLE001 — интеграционный слой не роняет индексер
        return []
    if not parsed:
        return []
    tree, detected_lang = parsed
    return extract_imports(tree, detected_lang or lang)


def known_languages() -> List[str]:
    return sorted(_get_language_import_nodes())


def _lang_for_ext(ext: str) -> str:
    # _EXT_TO_LANG — единственный словарь ext→lang в модуле (деривация + мост).
    return _EXT_TO_LANG.get((ext or "").lower(), "")


def _default_parser_provider(file_path: str, lang: str):
    """Реальный tree-sitter-language-pack (скачивает грамматики по сети)."""
    try:
        import tree_sitter_language_pack as ts_pack
    except ImportError:
        return None
    parser = ts_pack.get_parser(lang)
    with open(file_path, "rb") as fh:
        tree = parser.parse(fh.read())
    return tree, lang
