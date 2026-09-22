#!/usr/bin/env python3
"""
E11 — AST/Graph-hybrid re-ranking зонд (read-only).

Гипотеза (E11): search-only ceiling ~0.23 (Exp-29/E3). NL-запросы индекса
содержат идентификаторы кода (file_mtime_ns, verify_on_read, ...), но
_graph_stage триггерится ТОЛЬКО на чистый identifier-токен
(engine.py _IDENTIFIER_QUERY_RE). Зонд извлекает из NL-запроса
символьные подстроки-кандидаты, гоняет их через search_symbols()
(PropertyGraph LIKE + _definitions fallback) и проверяет:
сколько из 10 CASES эталонный файл появляется в graph-хитах.

Ничего не пишет в индекс. Ничего не меняет в src/.
"""

import re
import sys
import time
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CASES = [
    (
        "как работает hot-reload свежести индекса при изменении файлов",
        "src/core/indexing/freshness.py",
    ),
    (
        "миграция схемы добавление колонок file_mtime_ns в таблицу LanceDB",
        "src/core/indexing/db_manager.py",
    ),
    (
        "когда таблица пересоздаётся при schema mismatch полный rebuild",
        "src/core/indexing/db_writer.py",
    ),
    (
        "векторный поиск похожих чанков по индексу через LanceDB distance",
        "src/core/search/engine.py",
    ),
    (
        "ленивая проверка факта памяти verify on read статус ADR",
        "src/core/intelligence/verify_on_read.py",
    ),
    (
        "удалённый эмбеддинг через HTTP API llama server batch",
        "src/providers/embedder/remote_embedder.py",
    ),
    (
        "per project indexer registry multi window пулы по путям проектов",
        "src/core/indexing/project_indexer_registry.py",
    ),
    (
        "переиндексация одного изменённого файла notify change rate limit",
        "src/mcp/tools/indexing_tools.py",
    ),
    (
        "ранжирование результатов реранкером BGE M3 перестановка топ",
        "src/providers/reranker/search_result_reranker.py",
    ),
    (
        "bm25 ключевые слова медленный но точный полнотекстовый",
        "src/core/search/bm25.py",
    ),
]

# Токены, которые точно НЕ символы кода (стоп-слова NL)
_STOP = {
    "hot", "reload", "свежест", "индекс", "изменен", "файлов", "файл",
    "help", "is", "and", "or", "the", "table", "колонок", "таблиц", "поиск",
    "похожих", "чанков", "проверка", "факта", "памят", "статус", "удален",
    "эмбеддинг", "измененного", "ранжирование", "результатов", "которые",
    "ключевые", "слова", "медленный", "точный", "один", "схемы", "schema",
    "mismatch", "полный", "rebuild", "переиндексация", "пулы", "путям",
    "проектов", "перестановка", "содержат", "через", "при", "после",
    "before", "after", "query", "output", "index", "value", "list", "map",
    "set", "data", "file", "files", "code", "api", "http", "server",
    "window", "project", "projects", "lancedb", "актуальный", "антипаттерн",
    "build", "builds", "rate", "limit", "big", "old", "set", "get", "status",
    "реализован", "содержит", "не", "по", "для", "как", "когда",
}


def extract_candidates(query: str, min_len: int = 3) -> list:
    """Извлекает из NL-запроса подстроки-кандидаты на символы кода.

    1) snake_case токены (file_mtime_ns, verify_on_read)
    2) camelCase/qualified tokens из букв с хотя бы 2 заглавными/верблюдом
    3) одиночные буквенные токены (long words)
    Возвращает список в порядке убывания длины (самые специфичные первыми).
    """
    cands: list = []

    # snake_case / любой токен с underscore
    for m in re.finditer(r"[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+", query):
        t = m.group(0)
        if len(t) >= min_len:
            cands.append(t)

    # верблюжий регистр + qualified (dot/::/chevron) — но без пробелов
    for m in re.finditer(r"[A-Za-z][A-Za-z0-9._]{1,}", query):
        t = m.group(0)
        if len(t) < min_len:
            continue
        # отбросить чистые lowercase слова (NL), оставить верблюдов и qualified
        if t.endswith((".", ":", "_", "/")):
            continue
        if t in _STOP or t.lower() in _STOP:
            continue
        # snake уже добавлены
        if "_" in t:
            continue
        # только если это не простое lowercase слово (псевдо-символ: Camel/BGE/M3)
        low = t.lower()
        if low == t:
            # одинарное lowercase слово — только если длинное или редкое
            # (например bm25, fts, ttl, rrfd) — оставляем короткие техно-токены
            if len(t) >= 5 or any(ch.isdigit() for ch in t):
                cands.append(t)
            continue
        cands.append(t)

    # дедуп с сохранением порядка
    seen = set()
    uniq = []
    for c in sorted(cands, key=len, reverse=True):
        k = c.lower()
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    return uniq


def norm(p: str) -> str:
    return p.replace("\\", "/").lstrip("/")


def main() -> int:
    from src.core.di_container import create_service_collection, IndexerFactoryKey
    from src.core.indexing.project_indexer_registry import get_global_registry

    project = ROOT
    services = create_service_collection(project)
    registry = get_global_registry()
    factory = services.resolve(IndexerFactoryKey)
    indexer = registry.get_indexer(project, factory=factory)
    si = getattr(indexer, "_symbol_index", None) or getattr(indexer, "symbol_index", None)
    print(f"indexer: {type(indexer).__name__} rows={indexer.table.count_rows() if indexer.table else -1}")
    print(f"symbol_index: {type(si).__name__ if si else None}")
    if si is None:
        print("❌ no symbol_index")
        return 2

    n_saved_def = n_hit = 0
    print("━" * 100)
    print(f"{'#':>2} {'match':>6}  эталон → graph-хиты (топ до 5)")
    for i, (q, exp) in enumerate(CASES, 1):
        cands = extract_candidates(q)
        if not cands:
            print(f"{i:>2}  {'—':>6}  {norm(exp)}  [нет кандидатов]")
            continue

        refs = []
        t0 = time.perf_counter()
        for c in cands:
            try:
                r = si.search_symbols(c, top_k=15)
            except Exception as e:  # noqa: BLE001
                r = []
                print(f"    search_symbols({c!r}) → ERR {type(e).__name__}: {e}")
            for x in r or []:
                refs.append((c, x))
        dt = (time.perf_counter() - t0) * 1000

        files_hit = []
        def_hit = False
        for c, ref in refs:
            fp = norm(ref.file_path)
            if fp == norm(exp) or fp.endswith(norm(exp)):
                files_hit.append((c, ref.symbol, fp, ref.is_definition))
                if ref.is_definition:
                    def_hit = True

        uniq_files = []
        seen_f = set()
        for c, sym, fp, isdef in files_hit:
            if fp not in seen_f:
                seen_f.add(fp)
                uniq_files.append((c, sym, fp, isdef))

        mark = "✅" if uniq_files else ("🟡" if files_hit else "❌")
        if uniq_files:
            n_saved_def += 1 if any(x[3] for x in uniq_files) else 0
            n_hit += 1
        print(f"{i:>2} {mark:>6}  {norm(exp)}")
        print(f"      cands={cands[:6]} ({dt:.0f}ms, refs={len(refs)})")
        for c, sym, fp, isdef in uniq_files[:5]:
            print(f"      → {c}  [{sym}] {'DEF' if isdef else 'REF'} {fp}")

    print("━" * 100)
    print(f"graph-hit: {n_hit}/{len(CASES)}  def-hit: {n_saved_def}/{len(CASES)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback

        traceback.print_exc()
        sys.exit(1)