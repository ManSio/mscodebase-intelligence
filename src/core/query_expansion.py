"""
MSCodebase Intelligence — Query Expansion (расширение запросов).

Генерирует варианты запроса для улучшения recall поиска:
  • Синонимы из словаря терминов кодовой базы
  • Стемминг (удаление окончаний)
  • Plural/singular формы
  • Распространённые сокращения (db → database, auth → authentication)
"""

import logging
import re
from typing import Dict, List, Set

logger = logging.getLogger(__name__)


# Словарь синонимов для терминов кодовой базы
SYNONYMS: Dict[str, List[str]] = {
    # Авторизация / аутентификация
    "auth": ["authentication", "authorization", "login", "session"],
    "authentication": ["auth", "login", "signin"],
    "authorization": ["auth", "permission", "access_control"],
    "login": ["signin", "authenticate", "auth"],
    # База данных
    "db": ["database", "datastore", "storage", "persistence"],
    "database": ["db", "datastore", "storage"],
    "query": ["select", "fetch", "get", "find", "retrieve"],
    # CRUD операции
    "create": ["add", "insert", "new", "post", "register"],
    "read": ["get", "fetch", "retrieve", "select", "find", "list"],
    "update": ["edit", "modify", "change", "put", "patch"],
    "delete": ["remove", "destroy", "drop", "clear"],
    # Паттерны
    "handler": ["controller", "endpoint", "route", "view"],
    "controller": ["handler", "endpoint", "resource"],
    "service": ["manager", "provider", "usecase", "interactor"],
    "manager": ["service", "handler", "controller"],
    "repository": ["repo", "dao", "store", "gateway"],
    "config": ["configuration", "settings", "options", "env"],
    # Структуры
    "list": ["array", "collection", "items", "elements"],
    "dict": ["dictionary", "map", "hashmap", "object"],
    "error": ["exception", "failure", "issue", "problem"],
    # Действия
    "validate": ["check", "verify", "assert", "ensure"],
    "parse": ["deserialize", "decode", "extract"],
    "format": ["serialize", "encode", "stringify"],
    "init": ["initialize", "setup", "bootstrap", "create"],
    "send": ["dispatch", "emit", "post", "publish"],
    "receive": ["listen", "subscribe", "handle", "accept"],
    # Типы
    "string": ["str", "text", "varchar"],
    "int": ["integer", "number", "count"],
    "bool": ["boolean", "flag"],
    "func": ["function", "method", "procedure", "handler"],
    "cls": ["class", "type", "model"],
    # Распространённые сокращения
    "api": ["endpoint", "route", "resource"],
    "ui": ["view", "page", "component", "screen"],
    "util": ["helper", "tool", "utils"],
    "mgr": ["manager", "service"],
    "cfg": ["config", "configuration"],
    "conn": ["connection", "client"],
    "msg": ["message", "event", "notification"],
    "req": ["request", "input", "params"],
    "res": ["response", "output", "result"],
    "ctx": ["context", "scope"],
    "err": ["error", "exception"],
    "info": ["information", "metadata", "details"],
    "params": ["parameters", "args", "arguments"],
    "args": ["arguments", "params"],
}

# Распространённые окончания для стемминг (простой SUFFIX stripping)
SUFFIXES = ["ing", "tion", "sion", "ment", "ness", "able", "ible", "ful", "less", "ous", "ive", "ly", "er", "es", "s"]


def expand_query(query: str, max_expansions: int = 5) -> List[str]:
    """Расширяет запрос синонимами и вариациями.

    Args:
        query: Исходный запрос
        max_expansions: Максимальное число вариантов

    Returns:
        Список вариантов запроса (включая оригинал)
    """
    if not query.strip():
        return [query]

    words = query.lower().split()
    variants: Set[str] = {query.lower()}

    # 1. Синонимы для каждого слова
    for word in words:
        # Убираем пунктуацию
        clean_word = re.sub(r"[^\w]", "", word)
        if clean_word in SYNONYMS:
            for synonym in SYNONYMS[clean_word]:
                # Заменяем слово на синоним
                new_words = []
                for w in words:
                    clean_w = re.sub(r"[^\w]", "", w)
                    if clean_w == clean_word:
                        # Сохраняем оригинальный регистр первой буквы
                        if w[0].isupper():
                            new_words.append(synonym.capitalize())
                        else:
                            new_words.append(synonym)
                    else:
                        new_words.append(w)
                variant = " ".join(new_words)
                variants.add(variant)

    # 2. Стемминг (удаление окончаний)
    for word in words:
        clean_word = re.sub(r"[^\w]", "", word)
        if len(clean_word) > 5:  # Не стеммим короткие слова
            for suffix in SUFFIXES:
                if clean_word.endswith(suffix) and len(clean_word) - len(suffix) >= 3:
                    stem = clean_word[:-len(suffix)]
                    new_words = []
                    for w in words:
                        clean_w = re.sub(r"[^\w]", "", w)
                        if clean_w == clean_word:
                            new_words.append(stem)
                        else:
                            new_words.append(w)
                    variants.add(" ".join(new_words))
                    break  # Только один суффикс на слово

    # 3. Plural/singular (простая эвристика)
    for word in words:
        clean_word = re.sub(r"[^\w]", "", word)
        if clean_word.endswith("s") and len(clean_word) > 3:
            singular = clean_word[:-1]
            new_words = [singular if re.sub(r"[^\w]", "", w) == clean_word else w for w in words]
            variants.add(" ".join(new_words))

    # Ограничиваем количество
    result = list(variants)[:max_expansions]

    logger.debug(f"Query expansion: '{query}' → {result}")
    return result


def get_search_suggestions(query: str) -> List[str]:
    """Возвращает предложения для уточнения запроса.

    Args:
        query: Исходный запрос

    Returns:
        Список предложений
    """
    suggestions = []
    words = query.lower().split()

    for word in words:
        clean_word = re.sub(r"[^\w]", "", word)
        if clean_word in SYNONYMS:
            synonyms = SYNONYMS[clean_word][:3]
            suggestions.append(f"Попробуйте: {', '.join(synonyms)}")

    return suggestions[:5]
