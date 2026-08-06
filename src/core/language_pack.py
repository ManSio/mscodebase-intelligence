"""Опциональный слой tree-sitter-language-pack: +56 языков с tags.scm.

⚠️ Особенности (проверено 2026-08-06, language-pack 1.14.3):
- Парсеры СКАЧИВАЮТСЯ при первом использовании (нужна сеть; кэш в
  %LOCALAPPDATA%/tree-sitter-language-pack). На Windows 1.14.3 загрузка
  работает (per-language), хотя download_all() может падать (issue #174).
- Queries (tags.scm) встроены в пакет и доступны без скачивания.
- Включение: MSCODEBASE_LANGUAGE_PACK=true в .env (по умолчанию ВЫКЛЮЧЕН —
  иначе сканирование новых типов файлов меняет поведение индексации).

Лицензия: tree-sitter-language-pack — MIT (проверено по PyPI метаданным).
"""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("mscodebase.language_pack")

_ENV_FLAG = "MSCODEBASE_LANGUAGE_PACK"

# Язык -> расширения. Языки БЕЗ конфликтов с существующими расширениями.
# ⚠️ MATLAB пропущен: .m пересекается с Objective-C (.m/.mm уже в индексе).
LANG_EXT_MAP: Dict[str, List[str]] = {
    "lua": [".lua"],
    # ⚠️ elixir исключён: макро-грамматика (def/defmodule — call-узлы),
    # generic-извлечение даёт шум (def/defmodule как символы).
    "elm": [".elm"],
    "solidity": [".sol"],
    "svelte": [".svelte"],
    "gleam": [".gleam"],
    "ocaml": [".ml", ".mli"],
    "ocaml_interface": [".mli"],
    "fortran": [".f", ".f90", ".f95", ".f03", ".f08"],
    "r": [".r"],
    "racket": [".rkt"],
    "commonlisp": [".lisp", ".cl"],
    "elisp": [".el"],
    "d": [".d"],
    "cython": [".pyx", ".pxd", ".pxi"],
    "cuda": [".cu", ".cuh"],
    "ispc": [".ispc"],
    "arduino": [".ino"],
    "apex": [".cls", ".trigger"],
    "applescript": [".applescript"],
    "beancount": [".beancount", ".bean"],
    "cedar": [".cedar"],
    "cedarschema": [".cedarschema"],
    "cfml": [".cfm", ".cfc"],
    "chatito": [".chatito"],
    "enforce": [".enforce"],
    "fsharp": [".fs", ".fsx"],
    "fsharp_signature": [".fsi"],
    "gap": [".gap", ".gi"],
    "gdshader": [".gdshader"],
    "gren": [".gren"],
    "mojo": [".mojo"],
    "moonbit": [".mbt"],
    "netlinx": [".axs", ".axi"],
    "nix": [".nix"],
    "picat": [".pi"],
    "pony": [".pony"],
    "properties": [".properties"],
    "ql": [".ql", ".qll"],
    "roc": [".roc"],
    "sas": [".sas"],
    "sflog": [".sflog"],
    "snakemake": [".smk"],
    "soql": [".soql"],
    "sosl": [".sosl"],
    "sourcepawn": [".sp"],
    "spicedb": [".zed"],
    "stan": [".stan"],
    "sysml": [".sysml"],
    "t32": [".t32", ".cmm"],
    "tact": [".tact"],
    "templ": [".templ"],
    "udev": [".udev"],
    "al": [".al"],
}

# ext -> (lang) — производный индекс для быстрого lookup
_EXT_TO_LANG: Dict[str, str] = {
    ext: lang for lang, exts in LANG_EXT_MAP.items() for ext in exts
}

_parsers: Dict[str, Tuple[object, str]] = {}  # ext -> (tree_sitter.Parser, lang)
_tags: Dict[str, str] = {}  # lang -> tags.scm query string
_enabled: bool = False
_tried: bool = False


def is_enabled() -> bool:
    """Гейт: MSCODEBASE_LANGUAGE_PACK=true в .env (по умолчанию выключен)."""
    return os.getenv(_ENV_FLAG, "").strip().lower() in ("1", "true", "yes", "on")


def registered_exts() -> List[str]:
    return sorted(_parsers.keys())


def lang_for_ext(ext: str) -> Optional[str]:
    """Язык language-pack для расширения (None если не зарегистрирован)."""
    entry = _parsers.get(ext)
    return entry[1] if entry else None


def is_registered(ext: str) -> bool:
    return ext in _parsers


def get_parser(ext: str) -> Optional[object]:
    """Возвращает (parser, lang) для расширения или None."""
    entry = _parsers.get(ext)
    return entry[0] if entry else None


def get_tags_query(lang: str) -> Optional[str]:
    """Кэшированный tags.scm query для языка (None если нет)."""
    if not _tags:
        _ensure_tried()
    return _tags.get(lang)


def try_enable() -> Dict[str, object]:
    """Одноразовая инициализация слоя (вызывается из CodeParser.init).

    Регистрирует парсеры и queries для LANG_EXT_MAP, расширяет
    FileGuard.SUPPORTED_EXTENSIONS (сканирование новых типов файлов).

    Returns:
        {"enabled": bool, "languages": int, "extensions": [...], "failed": [...]}
    """
    global _enabled, _tried
    _tried = True
    if not is_enabled():
        return {"enabled": False, "reason": "MSCODEBASE_LANGUAGE_PACK не включён"}

    try:
        import tree_sitter_language_pack as ts_pack
    except ImportError:
        logger.warning(
            "MSCODEBASE_LANGUAGE_PACK=true, но tree-sitter-language-pack "
            "не установлен: pip install tree-sitter-language-pack"
        )
        return {"enabled": False, "reason": "пакет не установлен"}

    failed: List[str] = []
    ok = 0
    for lang, exts in LANG_EXT_MAP.items():
        try:
            parser = ts_pack.get_parser(lang)
        except Exception as e:  # noqa: BLE001 — язык опционален, регистрируем остальные
            failed.append(f"{lang}: {str(e)[:60]}")
            continue
        for ext in exts:
            _parsers[ext] = (parser, lang)
        ok += 1
        try:
            q = ts_pack.get_tags_query(lang)
            if q:
                _tags[lang] = q
        except Exception:  # noqa: BLE001 — query необязателен, не роняем слой
            pass

    _enabled = ok > 0
    if _enabled:
        _extend_index_extensions()

    logger.info(
        "🌍 language-pack слой: %d языков, %d расширений, %d с tags.scm "
        "(failed: %s)",
        ok, len(_parsers), len(_tags), failed or "нет",
    )
    return {
        "enabled": _enabled,
        "languages": ok,
        "extensions": sorted(_parsers.keys()),
        "tags_queries": len(_tags),
        "failed": failed,
    }


def _ensure_tried() -> None:
    if not _tried:
        try_enable()


def _extend_index_extensions() -> None:
    """Расширяет FileGuard.SUPPORTED_EXTENSIONS динамическими расширениями.

    INDEX_EXTENSIONS — frozenset (не мутируем): FileGuard'у присваивается
    union один раз при включении слоя.
    """
    try:
        from src.core.extensions import DYNAMIC_EXTENSIONS
        from src.core.indexing.file_guard import FileGuard

        DYNAMIC_EXTENSIONS.update(_parsers.keys())
        FileGuard.SUPPORTED_EXTENSIONS = frozenset(
            set(FileGuard.SUPPORTED_EXTENSIONS) | set(_parsers.keys())
        )
    except Exception as e:  # noqa: BLE001 — инициализация не должна ронять парсер
        logger.warning("language-pack: расширение FileGuard не удалось: %s", e)
