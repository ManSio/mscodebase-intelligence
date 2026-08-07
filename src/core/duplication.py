"""Детектор дупликации кода (v1): AST-нормализованные отпечатки + minhash-LSH.

Метод (проверен экспериментом 2026-08-08, EXPERIMENTS_LOG + experiments/exp_dup.py):
- tree-sitter (грамматики CodeParser, мультиязычно) → функции/методы/классы
- листовые токены нормализуются: идентификаторы → <id>, литералы/строки → <lit>
- точные дубли: sha1 нормализованной ПОСЛЕДОВАТЕЛЬНОСТИ токенов
- ближние дубли: Jaccard по МУЛЬТИМНОЖЕСТВУ нормализованных токенов
  (order-insensitive — устойчиво к вставкам, в отличие от k-грамм) +
  minhash-LSH (16 полос × 4) для отбора кандидатов

Не требует новых зависимостей: tree_sitter + hashlib уже в стеке проекта.
Связь: edge-тип SIMILAR_TO объявлен в graph.py, но не заполняется — этот
детектор может наполнять его на index-time (опционально, вне v1).
"""
from __future__ import annotations

import hashlib
import logging
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Set

logger = logging.getLogger("mscodebase.duplication")

# Идентификаторы любых языков нормализуются в <id>
_ID_TOKENS = {
    "identifier",
    "type_identifier",
    "field_identifier",
    "property_identifier",
}
# Литералы/комментарии — в <lit> (по подстроке типа узла — покрывает string/char/…)
_LIT_HINTS = ("string", "integer", "float", "bytes", "comment", "char_literal", "number")

_DEFAULT_MIN_TOKENS = 24
_DEFAULT_THRESHOLD = 0.85
_DEFAULT_MAX_FILE_BYTES = 200_000
_MAX_FILES = 10_000  # защита от необъятных репозиториев

_SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    ".codebase", ".codebase_indices", ".mscodebase", "dist", "build", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", ".cache", "site-packages",
}


def _norm_tokens(node) -> List[str]:
    """Листовые токены узла: идентификаторы и литералы → плейсхолдеры."""
    out: List[str] = []
    stack = [node]
    while stack:
        n = stack.pop()
        if n.child_count == 0:
            t = n.type
            if t in _ID_TOKENS:
                out.append("<id>")
            elif t in _LIT_HINTS or any(s in t for s in _LIT_HINTS):
                out.append("<lit>")
            else:
                out.append(t)
        else:
            stack.extend(reversed(n.children))
    return out


def _token_hashes(tokens: List[str]) -> List[int]:
    """64-битные хэши нормализованных токенов (порядок-независимо)."""
    return [
        int.from_bytes(hashlib.sha1(t.encode("utf-8")).digest()[:8], "big")
        for t in tokens
    ]


def _segmented_minhash(values: List[int], size: int = 64) -> List[int]:
    """Segmented minhash: по одному минимуму на сегмент (порядок-независимо)."""
    if not values:
        return []
    out = []
    for i in range(size):
        seg = values[i::size]
        out.append(min(seg) if seg else min(values))
    return out


def _multiset_jaccard(tokens_a: List[str], tokens_b: List[str]) -> float:
    """Jaccard по мультимножествам нормализованных токенов."""
    if not tokens_a or not tokens_b:
        return 0.0
    ca, cb = Counter(tokens_a), Counter(tokens_b)
    inter = sum((ca & cb).values())
    union = sum((ca | cb).values())
    return inter / union if union else 0.0


def _lsh_bands(sig: List[int], bands: int = 16, rows: int = 4) -> List[tuple]:
    """Полосы для LSH: (bands×rows) необязательно = len(sig)."""
    result = []
    for b in range(bands):
        start = b * rows
        result.append(tuple(sig[start : start + rows]))
    return result


def _symbol_name(node) -> str:
    for ch in node.children:
        if ch.type in ("identifier", "type_identifier", "name"):
            return ch.text.decode("utf-8", "replace")
    return "?"


def find_duplicates(
    project_path: Path,
    threshold: float = _DEFAULT_THRESHOLD,
    min_tokens: int = _DEFAULT_MIN_TOKENS,
    max_results: int = 50,
) -> Dict[str, Any]:
    """Находит дубликаты кода в проекте.

    Args:
        project_path: корень проекта.
        threshold: порог Jaccard для ближних дублей (0.0–1.0).
        min_tokens: минимальная длина нормализованного тела (фильтр шума).
        max_results: максимум ближних пар в ответе.

    Returns:
        {"status", "files_scanned", "symbols_scanned", "scan_ms",
         "exact_groups": [{"count", "symbols": [{"file", "name"}]}],
         "near_duplicates": [{"similarity", "a": {file,name}, "b": {file,name}}]}
    """
    try:
        from src.core.indexing.parser import CodeParser
    except ImportError:
        return {"status": "error", "message": "CodeParser недоступен"}

    threshold = max(0.0, min(1.0, threshold))
    if min_tokens < 4:
        min_tokens = 4

    parser = CodeParser()
    if not parser.parsers:
        return {"status": "error", "message": "tree-sitter грамматики не загружены"}

    target_nodes = set(getattr(CodeParser, "TARGET_NODES", set())) | {"class_definition"}

    t0 = time.perf_counter()
    files: List[Path] = []
    for p in project_path.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in parser.parsers:
            continue
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        try:
            if p.stat().st_size > _DEFAULT_MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        files.append(p)
        if len(files) >= _MAX_FILES:
            break

    symbols: List[Dict[str, Any]] = []  # {"file", "name", "tokens", "hash"}
    for fp in files:
        try:
            code = fp.read_bytes()
            if not code.strip():
                continue
            tree = parser.parsers[fp.suffix.lower()].parse(code)
        except Exception as e:  # noqa: BLE001 — битый файл не роняет весь скан
            logger.debug(f"dup scan skip {fp}: {e}")
            continue
        stack = [tree.root_node]
        while stack:
            node = stack.pop()
            for ch in node.children:
                if ch.type in target_nodes:
                    name = _symbol_name(ch)
                    toks = _norm_tokens(ch)
                    if len(toks) >= min_tokens:
                        symbols.append(
                            {
                                "file": str(fp),
                                "name": name,
                                "tokens": toks,
                                "hash": hashlib.sha1(
                                    "|".join(toks).encode("utf-8")
                                ).hexdigest(),
                            }
                        )
                stack.append(ch)

    scan_ms = (time.perf_counter() - t0) * 1000

    # Точные дубли
    by_hash: Dict[str, List[Dict[str, Any]]] = {}
    for s in symbols:
        by_hash.setdefault(s["hash"], []).append(s)
    exact_groups = []
    for h, group in by_hash.items():
        if len(group) > 1:
            exact_groups.append(
                {
                    "count": len(group),
                    "symbols": [{"file": s["file"], "name": s["name"]} for s in group],
                }
            )
    exact_groups.sort(key=lambda g: -g["count"])

    # Ближние дубли: Jaccard по мультимножеству токенов + minhash-LSH кандидаты
    sigs = []
    for s in symbols:
        sigs.append((s, _segmented_minhash(_token_hashes(s["tokens"]))))
    buckets: Dict[tuple, List[int]] = {}
    for idx, (_s, sig) in enumerate(sigs):
        for band in _lsh_bands(sig):
            buckets.setdefault(band, []).append(idx)

    seen: Set[tuple] = set()
    near: List[Dict[str, Any]] = []
    for band_indices in buckets.values():
        if len(band_indices) < 2:
            continue
        for i in range(len(band_indices)):
            for j in range(i + 1, len(band_indices)):
                ai, bj = band_indices[i], band_indices[j]
                if ai == bj:
                    continue
                key = (min(ai, bj), max(ai, bj))
                if key in seen:
                    continue
                seen.add(key)
                sim = _multiset_jaccard(sigs[ai][0]["tokens"], sigs[bj][0]["tokens"])
                if sim >= threshold:
                    near.append(
                        {
                            "similarity": round(sim, 3),
                            "a": {"file": sigs[ai][0]["file"], "name": sigs[ai][0]["name"]},
                            "b": {"file": sigs[bj][0]["file"], "name": sigs[bj][0]["name"]},
                        }
                    )
    near.sort(key=lambda x: -x["similarity"])

    return {
        "status": "ok",
        "files_scanned": len(files),
        "symbols_scanned": len(symbols),
        "scan_ms": round(scan_ms, 1),
        "exact_groups": exact_groups,
        "exact_count": len(exact_groups),
        "near_duplicates": near[:max_results],
        "near_count": len(near),
        "threshold": threshold,
    }
