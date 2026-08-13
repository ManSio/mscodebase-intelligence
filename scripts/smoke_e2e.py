#!/usr/bin/env python3
"""
Smoke E2E — реальная проверка живых сервисов MCP БЕЗ моков.

Инцидент 2026-08-13: «зелёный pytest ≠ работает». Два подтверждения:
  1) 7 search-тестов были зелёными по НЕВЕРНОЙ причине (MagicMock is_reindexing
     возвращал truthy → reindex fast-fail срабатывал «как надо», хотя реальный
     путь не проверялся);
  2) reranker не запускался весь день (PID-reuse в _is_pid_alive), а тесты
     этого не видели — они не поднимают реальные сервисы.

Правило AGENTS.md §7: для изменений в серверах/индексе «✅» в итоговом
отчёте = LIVE-SMOKE (этот скрипт), а не только полный pytest.

Что проверяет (реальные HTTP-вызовы + реальный индекс проекта):
  1. /health embedder (8080), reranker (8081), ONNX (9876)
  2. реальный embed через llama.cpp REST API — размерность вектора
  3. реальный rerank через /rerank — корректный порядок scores
  4. реальный поиск по реальному индексу проекта (DI → Searcher → search_with_mode)

Использование:
  python scripts/smoke_e2e.py                         # всё (сервисы + поиск)
  python scripts/smoke_e2e.py --services-only         # без поиска (быстрее)
  python scripts/smoke_e2e.py --project D:/Proj/X     # проект для поиска

Exit code: 0 = все проверки прошли; 1 = хотя бы одна упала.
"""

import argparse
import sys
from pathlib import Path

# §5.9 ENCODING SAFETY (Windows): cp1251 не кодирует эмодзи в отчёте
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 — переключение кодировки опционально
        pass

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None


def _setup_env():
    """Добавляет корень проекта в sys.path для import src.*."""
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def _health(url: str, timeout: float = 3.0) -> bool:
    try:
        if httpx is None:
            import urllib.request

            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.status == 200
        r = httpx.get(url, timeout=timeout)
        return r.status_code == 200
    except Exception:  # noqa: BLE001 — диагностика: собираем отчёт, не падаем
        return False


def check_services() -> dict:
    """Проверяет health всех трёх сервисов."""
    services = {
        "embedder": ("http://127.0.0.1:8080/health", 384),  # e5-small dim
        "reranker": ("http://127.0.0.1:8081/health", None),
        "onnx": ("http://127.0.0.1:9876/health", None),
    }
    report = {}
    for name, (url, _dim) in services.items():
        ok = _health(url)
        report[name] = "🟢" if ok else "🔴"
        if not ok:
            print(f"  [FAIL] {name}: {url} не отвечает")
    return report


def check_embed() -> tuple[bool, str]:
    """Реальный embed через llama.cpp REST API. Проверяет размерность."""
    try:
        r = httpx.post(
            "http://127.0.0.1:8080/v1/embeddings",
            json={"input": ["Проверка реального эмбеддинга smoke_e2e"]},
            timeout=15.0,
        )
        r.raise_for_status()
        data = r.json()
        vec = data["data"][0]["embedding"]
        dim = len(vec)
        ok = dim == 384
        return ok, f"dim={dim} (e5-small: 384) {'✅' if ok else '❌'}"
    except Exception as e:  # noqa: BLE001 — диагностика
        return False, f"embed error: {e}"


def check_rerank() -> tuple[bool, str]:
    """Реальный rerank через /rerank. Проверяет порядок scores.

    llama.cpp /rerank отвечает МАССИВОМ: [{"index": n, "score": s}, ...]
    (не {"results": [...]}) — обрабатываем оба формата.
    """
    try:
        r = httpx.post(
            "http://127.0.0.1:8081/rerank",
            json={
                "query": "как запустить индексацию",
                "texts": [
                    "Сегодня хорошая погода для прогулки",
                    "intel_trigger_reindex запускает переиндексацию проекта",
                    "Рецепт борща с капустой",
                ],
            },
            timeout=15.0,
        )
        r.raise_for_status()
        data = r.json()
        results = data if isinstance(data, list) else data.get("results", [])
        ok = len(results) == 3 and results[0]["index"] == 1  # релевантный текст первым
        return ok, f"top={results[0]['index'] if results else '?'} {'✅' if ok else '❌'}"
    except Exception as e:  # noqa: BLE001 — диагностика
        return False, f"rerank error: {e}"


def check_search(project: Path) -> tuple[bool, str]:
    """Реальный векторный поиск по реальному индексу проекта (без моков).

    Открываем LanceDB напрямую (lancedb.connect) — чтение не требует нашего
    PID-lock (он защищает запись; MCP другого окна держит lock — создание
    Indexer через DI упало бы «PID lock held», что и случилось в первом
    прогоне). Вектор запроса — реальный embed через llama.cpp (8080).
    """
    try:
        import lancedb

        from src.core.artifact_paths import get_db_path

        # Корень БД = <index_dir>/index_<proj>_<hash>.db (внутри таблица codebase_chunks)
        db = lancedb.connect(str(get_db_path(project)))
        names = db.table_names()
        if not names:
            return False, "в индексе нет таблиц (проект не индексирован)"
        table = db.open_table(names[0])
        # Реальный embed запроса через llama.cpp
        r = httpx.post(
            "http://127.0.0.1:8080/v1/embeddings",
            json={"input": ["def __init__ class initialization"]},
            timeout=15.0,
        )
        r.raise_for_status()
        vec = r.json()["data"][0]["embedding"]
        df = table.search(vec).limit(3).to_pandas()
        n = len(df)
        ok = n > 0
        return ok, f"таблица={names[0]}, results={n} {'✅' if ok else '❌'}"
    except Exception as e:  # noqa: BLE001 — диагностика
        return False, f"search error: {e}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke E2E — реальные сервисы MCP")
    parser.add_argument("--services-only", action="store_true",
                        help="только health+embed+rerank (без поиска)")
    parser.add_argument("--project", default=None, help="проект для реального поиска")
    args = parser.parse_args()

    _setup_env()
    print("🧪 Smoke E2E — реальные сервисы (без моков)")
    print("━" * 50)
    failures = 0

    # 1. Health
    print("1. Health сервисов:")
    svc = check_services()
    for name, status in svc.items():
        print(f"   {status} {name}")
    if any(v == "🔴" for v in svc.values()):
        print("   ⚠️ Часть сервисов не отвечает — embed/rerank проверки могут упасть")
        failures += 1

    # 2. Embed
    print("2. Реальный embed (llama.cpp):")
    ok, msg = check_embed()
    print(f"   {'✅' if ok else '❌'} {msg}")
    failures += 0 if ok else 1

    # 3. Rerank
    print("3. Реальный rerank (BGE-M3):")
    ok, msg = check_rerank()
    print(f"   {'✅' if ok else '❌'} {msg}")
    failures += 0 if ok else 1

    # 4. Search (реальный индекс)
    if not args.services_only:
        print("4. Реальный поиск по индексу проекта:")
        project = Path(args.project).resolve() if args.project else Path.cwd()
        ok, msg = check_search(project)
        print(f"   {'✅' if ok else '❌'} {msg}")
        failures += 0 if ok else 1

    print("━" * 50)
    if failures == 0:
        print(f"✅ SMOKE E2E: PASSED (проверок: {3 if args.services_only else 4})")
        return 0
    print(f"❌ SMOKE E2E: FAILED ({failures} проверок)")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — диагностика
        import traceback

        traceback.print_exc()
        sys.exit(1)
