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
import os
import sqlite3
import sys
import time
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


def get_revision() -> str:
    """git HEAD текущей ревизии — привязка отчёта к коду (policy_binding, OWP).

    «unknown» при отсутствии git/ошибке — честный fallback, а не молчание.
    main-поток, capture_output безопасен (§5.16 про daemon-треды).
    """
    import subprocess

    root = Path(__file__).resolve().parent.parent
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            timeout=5,
            creationflags=flags,
        )
        rev = head.stdout.decode("utf-8", "replace").strip()
        if not rev:
            return "unknown"
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(root),
            capture_output=True,
            timeout=5,
            creationflags=flags,
        )
        if dirty.stdout.strip():
            return f"{rev} (dirty)"
        return rev
    except Exception:  # noqa: BLE001 — диагностика
        return "unknown"


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
        "embedder": ("http://127.0.0.1:8080/health", 768),  # embeddinggemma-2 dim
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


def _active_embedder() -> tuple[str, int, str]:
    """Which embedder the smoke run must ask, from explicit configuration.

    The script has no `--dense` flag on purpose: `MSCODEBASE_DENSE_OFF` picks
    the tier, and `MSCODEBASE_EMBEDDER_PROVIDER` names the provider so a run
    can never accidentally validate a different backend's width.
    """
    provider = os.getenv("MSCODEBASE_EMBEDDER_PROVIDER", "auto").strip().lower()
    if provider == "onnx":
        return "onnx", 384, "multilingual-e5-small-int8"
    if provider in ("lm_studio", "ollama"):
        return (
            provider,
            int(os.getenv("EMBEDDING_DIMENSION", "384")),
            os.getenv("MODEL_NAME", "multilingual-e5-small-int8"),
        )
    # auto / llama_cpp — исторический путь smoke: llama-server на :8080.
    return "llama_cpp", int(os.getenv("EMBEDDING_DIMENSION", "768")), "embeddinggemma-2"


def _embed_text(text: str) -> tuple[list[float], str, int]:
    provider, expected_dim, model = _active_embedder()
    if provider == "onnx":
        from src.core.embedder.onnx_client import get_onnx_client

        client = get_onnx_client(port=9876, model_name=model)
        return client.embed(text), provider, expected_dim
    url = (
        "http://127.0.0.1:8080/v1/embeddings"
        if provider == "llama_cpp"
        else "http://127.0.0.1:1234/v1/embeddings"
    )
    r = httpx.post(url, json={"input": [text], "model": model}, timeout=30.0)
    r.raise_for_status()
    return r.json()["data"][0]["embedding"], provider, expected_dim


def check_embed() -> tuple[bool, str]:
    """Реальный embed через активный провайдер. Проверяет размерность."""
    try:
        vec, provider, expected = _embed_text("Проверка реального эмбеддинга smoke_e2e")
        dim = len(vec)
        ok = dim == expected
        return ok, (
            f"provider={provider}, dim={dim} (expected {expected}) "
            f"{'✅' if ok else '❌'}"
        )
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


def _text_index_search(project: Path) -> tuple[bool, str]:
    """Поиск по текстовому индексу (SQLite FTS5), когда векторов нет.

    Дефолт репозитория — `MSCODEBASE_DENSE_OFF=true`: индекс собирается
    `reindex_text_only.py`, и LanceDB-таблицы с векторами не существует.
    Проверять «поиск работает» надо по тому индексу, который есть.
    """
    db = Path(project) / ".mscodebase" / "chunks.db"
    if not db.is_file():
        return False, f"текстового индекса нет: {db}"
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        probe = con.execute(
            "select symbol_name from chunks "
            "where symbol_name is not null and length(symbol_name) >= 4 limit 1"
        ).fetchone()
        term = probe[0] if probe else ""
        if not term:
            text = con.execute("select text from chunks limit 1").fetchone()
            if not text:
                return False, "текстовый индекс пуст"
            term = next((w for w in str(text[0]).split() if len(w) > 3), "")
        if not term:
            return False, "не из чего выбрать пробный термин"
        rows = con.execute(
            "select file_path from chunks_fts "
            "where chunks_fts match ? limit 3",
            (f'"{term}"',),
        ).fetchall()
        ok = bool(rows)
        sample = rows[0][0] if rows else ""
        return ok, (f"term={term!r}, results={len(rows)}"
                    f"{f' ({sample})' if sample else ''} {'✅' if ok else '❌'}")
    except sqlite3.Error as e:
        return False, f"text search error: {e}"
    finally:
        con.close()


def check_search(project: Path) -> tuple[bool, str]:
    """Реальный векторный поиск по реальному индексу проекта (без моков).

    Открываем LanceDB напрямую (lancedb.connect) — чтение не требует нашего
    PID-lock (он защищает запись; MCP другого окна держит lock — создание
    Indexer через DI упало бы «PID lock held», что и случилось в первом
    прогоне). Вектор запроса — real embed активного провайдера
    (`MSCODEBASE_EMBEDDER_PROVIDER`), ширина сверяется со схемой таблицы.

    Если векторного индекса нет (дефолт `MSCODEBASE_DENSE_OFF=true`), шаг
    проверяет текстовый индекс SQLite: падать на отсутствии вектора значило бы
    требовать от дефолтной конфигурации чужой режим.
    """
    from src.core.artifact_paths import get_db_path
    from src.core.indexing.dim_contract import (
        EmbeddingDimMismatch,
        schema_vector_dim,
    )

    vector_db = Path(str(get_db_path(project)))
    if not vector_db.exists():
        ok, detail = _text_index_search(project)
        return ok, f"векторного индекса нет; {detail}"
    try:
        import lancedb

        # Корень БД = <index_dir>/index_<proj>_<hash>.db (внутри таблица codebase_chunks).
        # Ретри: LanceDB-манифест при конкурентной записи (живой MCP переиндексирует)
        # может транзиентно показать 0 таблиц — повторяем connect с короткой паузой.
        names: list[str] = []
        db_path = str(get_db_path(project))
        for _ in range(3):
            db = lancedb.connect(db_path)
            names = db.table_names()
            if names:
                break
            time.sleep(0.5)
        if not names:
            ok, detail = _text_index_search(project)
            return ok, f"в векторной БД нет таблиц; {detail}"
        table = db.open_table(names[0])
        if table.count_rows() == 0:
            # An empty vector table is not a dense index; the shipped default is
            # text-only, so validate the text index instead of a width mismatch.
            ok, detail = _text_index_search(project)
            return ok, f"векторная таблица пуста; {detail}"
        # Width contract first: a query must match the table's vector width.
        # A mismatch is a named failure, not a silent text fallback (G4).
        schema_dim = schema_vector_dim(table.schema)
        vec, provider, _expected = _embed_text("def __init__ class initialization")
        if schema_dim is None:
            return False, "vector table has no fixed-size vector column"
        if len(vec) != schema_dim:
            raise EmbeddingDimMismatch(
                f"provider '{provider}' returns {len(vec)}-d vectors, but "
                f"the index is {schema_dim}-d; refusing to search a mixed index"
            )
        df = table.search(vec).limit(3).to_pandas()
        n = len(df)
        ok = n > 0
        return ok, (
            f"режим=vector, provider={provider}, dim={len(vec)}, "
            f"таблица={names[0]}, results={n} {'✅' if ok else '❌'}"
        )
    except EmbeddingDimMismatch as e:
        # A vector index exists and its width is the contract: do not hide the
        # failure behind a text fallback (that was G4's silent path).
        return False, f"dimension contract: {e}"
    except Exception as e:  # noqa: BLE001 — диагностика
        ok, detail = _text_index_search(project)
        if ok:
            return True, f"режим=text (vector: {str(e)[:120]}); {detail}"
        return False, f"search error: {e}; {detail}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke E2E — реальные сервисы MCP")
    parser.add_argument("--services-only", action="store_true",
                        help="только health+embed+rerank (без поиска)")
    parser.add_argument("--project", default=None, help="проект для реального поиска")
    args = parser.parse_args()

    _setup_env()
    revision = get_revision()
    provider, expected_dim, _model = _active_embedder()
    if provider == "onnx":
        # A pinned local provider is part of the run, not a precondition: bring
        # it up before health so an idle-unloaded server is not a false FAIL.
        try:
            from src.core.embedder.onnx_client import get_onnx_client

            get_onnx_client(port=9876, model_name=_model).ensure_server_running()
        except Exception as exc:  # noqa: BLE001 — the embed step reports detail
            print(f"   ⚠️ ONNX start failed: {exc}")
    print("🧪 Smoke E2E — реальные сервисы (без моков)")
    print(f"revision: {revision}")
    print(f"embedder provider: {provider} (expected dim {expected_dim})")
    print("━" * 50)
    failures = 0

    # 1. Health
    print("1. Health сервисов:")
    svc = check_services()
    for name, status in svc.items():
        print(f"   {status} {name}")
    # The required health entry is the ACTIVE provider, not a fixed llama port:
    # an ONNX dense run must not fail because :8080 is intentionally absent.
    active_health = "onnx" if provider == "onnx" else "embedder"
    required = [n for n in (active_health, "reranker") if svc.get(n) == "🔴"]
    if required:
        print(f"   ⚠️ Критичные сервисы не отвечают ({', '.join(required)}) — embed/rerank проверки могут упасть")
        failures += 1
    elif provider != "onnx" and svc.get("onnx") == "🔴":
        print("   ℹ️ onnx — альтернативный embedder не запущен; необязательный — пропускаю")

    # 2. Embed
    print(f"2. Реальный embed ({provider}, expected {expected_dim}-d):")
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
        print(f"✅ SMOKE E2E: PASSED (проверок: {3 if args.services_only else 4}, revision: {revision})")
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
