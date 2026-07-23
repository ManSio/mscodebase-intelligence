"""Modification Guard — защита от деструктивных операций на горячих файлах.

Паттерн Qartez: перед write-операцией проверяем PageRank и blast radius.
Если файл "горячий" — возвращаем Deny с требованием вызвать impact_analysis сначала.

Ack-система: после impact_analysis() пользователь получает TTL=600s,
в течение которого write разрешён.
"""

from __future__ import annotations

import hashlib
import hmac
import inspect
import logging
import os
import time
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict

logger = logging.getLogger(__name__)

# Ack registry: {file_path: timestamp}
# После вызова impact_analysis пользователь "подтверждает" осведомлённость
_ack_registry: Dict[str, float] = {}
_ACK_TTL: float = 600.0  # 600 секунд = 10 минут
_ACK_SECRET = os.environ.get(
    "MSCODEBASE_ACK_SECRET", "dev-secret-change-me"
).encode()


def _file_fingerprint(file_path: str) -> str:
    """Хэш mtime+size файла — токен привязан к конкретному состоянию."""
    try:
        p = Path(file_path)
        stat = p.stat()
        return f"{stat.st_mtime_ns}:{stat.st_size}"
    except OSError:
        return "missing"


def _make_ack_token(file_path: str) -> str:
    """Генерирует HMAC-токен для файла. Токен привязан к текущему состоянию."""
    normalized = _normalize_path(file_path)
    fingerprint = _file_fingerprint(file_path)
    msg = f"{normalized}:{fingerprint}".encode()
    return hmac.new(_ACK_SECRET, msg, hashlib.sha256).hexdigest()[:32]


def _verify_ack_token(file_path: str, token: str) -> bool:
    """Проверяет, что токен валиден для текущего состояния файла."""
    expected = _make_ack_token(file_path)
    return hmac.compare_digest(expected, token)


def ack_impact(file_path: str, impact_token: str) -> Dict[str, Any]:
    """Подтвердить осведомлённость о влиянии изменений в файле.

    impact_token обязателен и должен быть получен из ответа impact_analysis
    для ЭТОГО файла в его ТЕКУЩЕМ состоянии. Голый ack без токена больше
    не принимается — иначе это ритуальный чек-бокс без содержания.
    """
    if not _verify_ack_token(file_path, impact_token):
        return {
            "status": "denied",
            "message": (
                f"Invalid or stale impact_token for {file_path}. "
                f"Call impact_analysis first and use the token from its response — "
                f"a token is only valid for the file's current content."
            ),
        }
    normalized = _normalize_path(file_path)
    _ack_registry[normalized] = time.time()
    return {
        "status": "ok",
        "message": f"Impact acknowledged for {file_path}. Write operations allowed for {_ACK_TTL}s.",
        "ttl_seconds": _ACK_TTL,
    }


def _normalize_path(path: str) -> str:
    """Нормализует путь для единообразия ключей ack_registry."""
    return Path(path).resolve().as_posix().lower()


def _get_pagerank_for_file(file_path: str, services) -> float:
    """Получает PageRank файла через get_repo_rank.

    Returns 0.0 если не удалось получить.
    Raises RuntimeError if DI resolution fails (fail-closed).
    """
    try:
        # Используем MCP инструмент get_repo_rank (если доступен)
        from src.core.di_container import ProjectIndexerRegistry

        registry = services.resolve(ProjectIndexerRegistry)
        indexer = registry.get_indexer(Path(file_path).resolve())
        if hasattr(indexer, "get_repo_rank"):
            rank = indexer.get_repo_rank(file_path)
            if isinstance(rank, dict):
                return rank.get("pagerank", 0.0)
            return float(rank or 0.0)
    except Exception as e:
        # Fail-closed: if we can't determine PageRank, assume file is hot
        # and require explicit ack. Log at WARNING so it's visible.
        logger.warning(f"[Guard] PageRank lookup failed (fail-closed): {e}")
        return 1.0  # Treat as maximum PageRank to force ack


def _get_blast_radius_for_file(symbol: str, services) -> int:
    """Получает blast radius символа через impact_analysis.

    Returns 0 если не удалось получить.
    Raises RuntimeError if DI resolution fails (fail-closed).
    """
    try:
        from src.core.di_container import ProjectIndexerRegistry

        registry = services.resolve(ProjectIndexerRegistry)
        indexer = registry.get_indexer()
        si = indexer.symbol_index if hasattr(indexer, "symbol_index") else None
        if si and hasattr(si, "get_impact_analysis"):
            impact = si.get_impact_analysis(symbol, depth=2)
            if impact:
                dc = len(impact.get("direct_callers", []) or [])
                tc = len(impact.get("transitive_callers", []) or [])
                dcal = len(impact.get("direct_callees", []) or [])
                tcal = len(impact.get("transitive_callees", []) or [])
                return dc + tc + dcal + tcal
    except Exception as e:
        # Fail-closed: if we can't determine blast radius, assume it's large
        logger.warning(f"[Guard] Blast radius lookup failed (fail-closed): {e}")
        return 100  # Treat as maximum blast radius to force ack
    return 0


def modification_guard(
    pagerank_min: float = 0.05,
    blast_min: int = 10,
    ack_ttl: float = 600.0,
):
    """Декоратор для write-инструментов.

    Проверяет перед выполнением:
    1. PageRank файла — если >= pagerank_min, файл "горячий"
    2. Blast radius символа — если >= blast_min, изменение затронет много мест
    3. Ack status — если пользователь вызвал ack_impact для этого файла < ack_ttl секунд назад

    Если (PageRank >= min ИЛИ BlastRadius >= min) И нет актуального ack → DENY.

    Args:
        pagerank_min: Порог PageRank (0.0-1.0). 0.05 = топ-5% файлов.
        blast_min: Порог количества затронутых связей.
        ack_ttl: Время жизни ack в секундах.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            # Определяем target file — bind positional + keyword args via inspect
            sig = inspect.signature(func)
            try:
                bound = sig.bind_partial(self, *args, **kwargs)
                bound.apply_defaults()
                call_args = bound.arguments
            except TypeError:
                call_args = kwargs  # fallback

            file_path = (
                call_args.get("file_path", "") or kwargs.get("file_path", "")
            )
            symbol = (
                call_args.get("symbol")
                or call_args.get("old_name")
                or kwargs.get("symbol", kwargs.get("old_name", ""))
                or ""
            )

            if not file_path and not symbol:
                # Нет цели для проверки — пропускаем
                return await func(self, *args, **kwargs)

            # Если указан file_path — используем его
            if file_path:
                target_path = _normalize_path(file_path)
            elif symbol:
                # Пытаемся найти файл по символу через SymbolIndex
                try:
                    si = self.resolve_symbol_index() if hasattr(self, "resolve_symbol_index") else None
                    if si:
                        defs = si.find_definitions(symbol)
                        if defs:
                            target_path = _normalize_path(defs[0].file_path)
                        else:
                            target_path = ""
                    else:
                        target_path = ""
                except Exception:
                    target_path = ""
            else:
                target_path = ""

            # Проверяем ack
            if target_path and target_path in _ack_registry:
                elapsed = time.time() - _ack_registry[target_path]
                if elapsed < ack_ttl:
                    # Ack актуален — разрешаем
                    return await func(self, *args, **kwargs)
                else:
                    # Ack истёк — удаляем
                    del _ack_registry[target_path]

            # Получаем PageRank и blast radius
            pagerank = _get_pagerank_for_file(target_path, self._services) if target_path else 0.0
            blast = _get_blast_radius_for_file(symbol, self._services) if symbol else 0

            is_hot = pagerank >= pagerank_min or blast >= blast_min

            if is_hot:
                token = _make_ack_token(target_path)
                return {
                    "status": "denied",
                    "message": (
                        f"Modification guard: file is load-bearing.\n"
                        f"  \u2022 PageRank: {pagerank:.3f} (threshold: {pagerank_min})\n"
                        f"  \u2022 Blast radius: {blast} connections (threshold: {blast_min})\n\n"
                        f'Call `ack_impact(file_path="{file_path or target_path}", '
                        f'impact_token="{token}")` to acknowledge impact and proceed.'
                    ),
                    "guard": {
                        "pagerank": round(pagerank, 3),
                        "pagerank_threshold": pagerank_min,
                        "blast_radius": blast,
                        "blast_threshold": blast_min,
                        "ack_required": True,
                        "impact_token": token,
                    },
                }

            return await func(self, *args, **kwargs)

        return wrapper

    return decorator


__all__ = [
    "modification_guard",
    "ack_impact",
    "_ack_registry",
    "_make_ack_token",
    "_verify_ack_token",
]