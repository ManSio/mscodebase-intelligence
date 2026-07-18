"""
i18n — минимальная интернационализация для MCP-инструментов.

Использование:
    from src.utils.i18n import _

    # В коде:
    return _("📦 Chunks: {count} | Files: {count}", count=chunks)

    # Переключение языка (из server.py при старте):
    from src.utils.i18n import set_locale
    set_locale("en")  # "ru" | "en" | "zh"
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger("mscodebase.i18n")

_LOCALE: str = "en"
_TRANSLATIONS: Dict[str, str] = {}

_LOCALES_DIR = Path(__file__).resolve().parent.parent.parent / "locales"


def set_locale(locale: str) -> None:
    """Устанавливает язык сообщений. Загружает файл locales/{locale}.json."""
    global _LOCALE, _TRANSLATIONS
    _LOCALE = locale
    _TRANSLATIONS = _load_file(locale)
    logger.info(f"🌐 Локализация: {locale} ({len(_TRANSLATIONS)} строк)")


def get_locale() -> str:
    return _LOCALE


def _load_file(locale: str) -> Dict[str, str]:
    """Загружает файл перевода для языка."""
    path = _LOCALES_DIR / f"{locale}.json"
    if not path.exists():
        logger.warning(f"Файл перевода не найден: {path}")
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Ошибка загрузки {path}: {e}")
        return {}


def _(msg: str, **kwargs: Any) -> str:
    """Переводит строку. Если перевода нет — возвращает оригинал (fallback = en).

    Поддерживает .format(**kwargs):
        _("Found {count} files", count=5) → "Found 5 files"
    """
    translated = _TRANSLATIONS.get(msg, msg)

    # Fallback: если файл перевода загружен, но ключа нет — пробуем en
    if translated == msg and _LOCALE != "en":
        en_path = _LOCALES_DIR / "en.json"
        if en_path.exists():
            try:
                with open(en_path, "r", encoding="utf-8") as f:
                    en_data = json.load(f)
                translated = en_data.get(msg, msg)
            except Exception as _e:
                logger.warning("exception", exc_info=True)
                pass
    if kwargs:
        try:
            return translated.format(**kwargs)
        except KeyError:
            return translated
    return translated


# Auto-detect locale from env
_init_locale = os.environ.get("MSCODEBASE_LOCALE", "en")
set_locale(_init_locale)
