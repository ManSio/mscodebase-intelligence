"""Agent-facing query plan (E45).

The agent supplies one primary query plus exact tokens/symbols; the server
executes one query and applies deterministic boosts. No multi-query flood.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

__all__ = ["build_plan", "apply_plan_boosts", "normalize_list"]

_RU_STOP = set(
    """
    почему как что зачем насколько какой каким какая какие где когда это этот эта эти
    и а но или же ли бы то все всё если чтобы может можно нужно надо делает делают
    работает работают используется используются происходит происходят относится
    является были был была есть не ни в на с со по для из к ко о об от до при
    между через после перед под над без более менее самый самая самое
    чем чего чему кем том того этому этих также только уже еще ещё
    вот так там тут мы вы они он она оно
    """.split()
)

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_\.:/-]*")
_SYMBOL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{2,}$")

_CONCEPTS = {
    "auth": ["auth", "login", "session", "credential", "authorization",
             "authenticate", "авторизация", "аутентификация", "логин", "сессия",
             "токен", "доступ"],
    "cache": ["cache", "caching", "кэш", "кэширование", "кэшировать"],
    "database": ["database", "sqlite", "lancedb", "schema", "база", "данных"],
    "config": ["config", "configuration", "settings", "конфиг", "настройка"],
    "error": ["error", "exception", "failure", "ошибка", "исключение", "сбой"],
    "rate_limit": ["rate limit", "rate_limiter", "throttle", "ограничитель",
                   "скорости", "лимит"],
    "graph": ["graph", "node", "edge", "caller", "callee", "граф", "узел",
              "ребро", "вызов"],
    "search": ["search", "retrieval", "hybrid", "bm25", "fts5", "rerank",
               "поиск", "поисковый", "реранкер"],
    "index": ["index", "indexing", "reindex", "индекс", "индексация",
              "переиндексация"],
    "memory": ["memory", "recall", "prompt", "context", "память", "контекст"],
    "concurrency": ["thread", "lock", "mutex", "async", "await", "race",
                    "поток", "блокировка", "мьютекс"],
    "network": ["http", "request", "response", "server", "client", "port",
                "запрос", "ответ", "сервер", "клиент", "порт"],
    "file": ["file", "path", "module", "package", "файл", "путь", "модуль"],
    "test": ["test", "pytest", "тест", "проверка"],
    "process": ["process", "pid", "start", "stop", "процесс", "запуск"],
    "security": ["security", "secret", "redact", "trust", "credential",
                 "безопасность", "секрет", "доверие"],
}


def normalize_list(value: Any) -> List[str]:
    """Accept a list, comma/space-separated string, or None."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(x).strip() for x in value if str(x).strip()]
    return [x.strip() for x in re.split(r"[,;\s]+", str(value)) if x.strip()]


def _is_symbol(tok: str) -> bool:
    if not _SYMBOL_RE.match(tok):
        return False
    if any(ch.isupper() for ch in tok) or "_" in tok:
        return True
    return "." in tok or "/" in tok or "::" in tok


def build_plan(query: str) -> Dict[str, Any]:
    """Deterministic plan from a natural-language question."""
    q = (query or "").strip()
    if not q:
        return {
            "primary": "",
            "must_include": [],
            "symbols": [],
            "concepts": [],
            "intent": "auto",
            "suggested_queries": [],
        }

    tokens = re.findall(r"[\w\.:/-]+", q, flags=re.UNICODE)
    primary_tokens = []
    for tok in tokens:
        low = tok.lower().strip(".,!?;:()[]{}\"'«»")
        if not low or low in _RU_STOP:
            continue
        primary_tokens.append(tok)
    primary = " ".join(primary_tokens) or q

    must: List[str] = []
    for tok in _IDENT_RE.findall(q):
        if len(tok) < 3:
            continue
        if any(ch.isupper() for ch in tok) or "_" in tok or "." in tok or "/" in tok:
            if tok.lower() not in {m.lower() for m in must}:
                must.append(tok)
    symbols = [t for t in must if _is_symbol(t)]

    low = q.lower()
    concepts = [
        c
        for c, terms in _CONCEPTS.items()
        if any(t.lower() in low for t in terms)
    ]

    try:
        from .scoring import auto_detect_intent

        intent = auto_detect_intent(q)
    except Exception:  # noqa: BLE001 - optional intent must not break planning
        intent = "auto"

    return {
        "primary": primary,
        "must_include": must[:5],
        "symbols": symbols[:5],
        "concepts": concepts[:5],
        "intent": intent,
        "suggested_queries": [primary],
    }


def apply_plan_boosts(
    results: Iterable[Dict[str, Any]],
    must_include: Any = None,
    symbols: Any = None,
    factor: float = 2.0,
) -> List[Dict[str, Any]]:
    """Apply deterministic ×factor boosts for exact tokens/symbols."""
    must = [m.lower() for m in normalize_list(must_include)]
    syms = {s.lower() for s in normalize_list(symbols)}
    out = []
    for r in results:
        meta = r.get("metadata") or {}
        blob = " ".join(
            [
                str(meta.get("symbol_name", "") or ""),
                str(r.get("text_full") or r.get("text") or ""),
            ]
        ).lower()
        score = float(r.get("final_score", 0.0) or 0.0)
        if must and any(m in blob for m in must):
            score *= factor
        if syms and str(meta.get("symbol_name", "")).lower() in syms:
            score *= factor
        item = dict(r)
        item["_plan_score"] = score
        out.append(item)
    out.sort(key=lambda r: r.get("_plan_score", 0.0), reverse=True)
    return out
