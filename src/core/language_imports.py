"""language_imports.py — извлечение импортов из tree-sitter-дерева (Вариант A).

Возрождение IMPORT_NODE_MAP: был в parser.py с 17.07.2026 (v3.3.0, 20 языков,
commit 142761d), удалён рефакторингом к 04.08.2026 — claim «20 языков» в
CHANGELOG разошёлся с кодом (закрыто 24.08.2026).

Экстрактор ЧИСТЫЙ и duck-typed: работает с любым деревом, у которого есть
node.type / node.children / node.text — поэтому тестируется синтетикой БЕЗ
tree-sitter (герметичность). Реальные грамматики (tree-sitter-language-pack,
+56 языков) скачиваются по сети при первом использовании — это вне юнит-тестов.

Два режима:
  1. Точный: node-типы из LANGUAGE_IMPORT_NODES (исходные 20 языков).
  2. Fallback: для языков без карты — любой node, чей тип содержит
     'import'/'use'/'include' (best-effort, никогда не падает — Negative control).

Гейт включения — как у language_pack.py: MSCODEBASE_LANGUAGE_PACK=true.
"""

from __future__ import annotations

from typing import Dict, List, Sequence

__all__ = [
    "extract_imports",
    "extract_imports_from_file",
    "LANGUAGE_IMPORT_NODES",
    "known_languages",
]

# Язык -> node-типы tree-sitter, представляющие импорты (исходные 20).
# Ключи нормализованы (нижний регистр, без расширений).
LANGUAGE_IMPORT_NODES: Dict[str, tuple[str, ...]] = {
    "python": ("import_statement", "import_from_statement"),
    "rust": ("use_declaration",),
    "javascript": ("import_statement", "export_statement"),
    "typescript": ("import_statement", "export_statement"),
    "tsx": ("import_statement", "export_statement"),
    "go": ("import_declaration",),
    "java": ("import_declaration",),
    "csharp": ("using_directive",),
    "ruby": ("call",),  # require / require_relative — фильтруем по имени вызова
    "php": ("namespace_use_declaration",),
    "kotlin": ("import_header",),
    "swift": ("import_declaration",),
    "c": ("preproc_include",),
    "cpp": ("preproc_include",),
    "scala": ("import_declaration",),
    "dart": ("import_directive", "export_directive"),
    "bash": ("declaration_command",),  # source / import — грубый best-effort
    "objectivec": ("preproc_include",),
    "cpp_objectivec": ("preproc_include",),
    "vue": ("import_statement", "export_statement"),
}

# Импорт НЕ должен содержать эти слова (ключевые слова/служебные имена).
_IMPORT_KEYWORDS = frozenset(
    {
        "import", "from", "as", "require", "use", "pub", "mod", "crate", "self",
        "super", "export", "default", "include", "source", "using", "namespace",
        "static", "fn", "const", "let", "var", "new", "extends", "if", "else",
    }
)

_FALLBACK_SUBSTR = ("import", "use", "include")


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
    targets = LANGUAGE_IMPORT_NODES.get(lang)
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
    return any(s in ntype for s in _FALLBACK_SUBSTR)


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
    import os
    from pathlib import Path

    if lang is None:
        lang = _lang_for_ext(Path(file_path).suffix)
    if parser_provider is None:
        if os.getenv("MSCODEBASE_LANGUAGE_PACK", "").strip().lower() not in (
            "1", "true", "yes", "on",
        ):
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
    return sorted(LANGUAGE_IMPORT_NODES)


def _lang_for_ext(ext: str) -> str:
    _EXT_LANG = {
        ".py": "python", ".rs": "rust", ".js": "javascript", ".jsx": "javascript",
        ".ts": "typescript", ".tsx": "tsx", ".vue": "vue", ".go": "go",
        ".java": "java", ".cs": "csharp", ".rb": "ruby", ".php": "php",
        ".kt": "kotlin", ".swift": "swift", ".c": "c", ".h": "c",
        ".cpp": "cpp", ".cc": "cpp", ".hpp": "cpp", ".scala": "scala",
        ".dart": "dart", ".sh": "bash", ".bash": "bash", ".m": "objectivec",
    }
    return _EXT_LANG.get((ext or "").lower(), "")


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
