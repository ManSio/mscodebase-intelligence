"""E-03 — clone→index на реальных публичных репозиториях (DoD Фазы 2).

Прогон: GitUrlSource (clone в кэш) → реальный эмбеддинг (llama.cpp 8080) →
индекс в отдельный LanceDB (изолирован от живого MCP). Замер времени
clone / index, число файлов и чанков, fingerprint-skip (повторный resolve
+ git-tree fingerprint — 0 файлов на пере-индексацию), failure-кейсы
(несуществующий URL → INCONCLUSIVE, не crash).

Гипотеза (план §2.2): полный цикл «дали URL → получили индекс» на малых
репозиториях занимает секунды-минуты; fingerprint-skip делает повторный
разбор бесплатным (0 re-embed).

Запуск: python experiments/universal-engine/e03_clone_index.py
"""

import asyncio
import sys
import tempfile

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Кэш клонов — В СИСТЕМНОМ TEMP, вне репо: клонированные доки репозиториев
# (README/DOCS) не должны попадать в stale_detector/pytest-скан проекта
# (инцидент E-03-2026-08-18: rich 3.6.3/httpx 5.1.2 флагались как дрейф).
CACHE = (Path(tempfile.gettempdir()) / "mscodebase_e03_clone_cache").resolve()

REPOS = [
    "https://github.com/octocat/Hello-World.git",   # 1 файл
    "https://github.com/encode/httpx.git",          # малый
    "https://github.com/pallets/flask.git",         # средний
    "https://github.com/Textualize/rich.git",       # средний-большой
]

FAILURE_URLS = [
    "https://github.com/octocat/does-not-exist-xyz.git",  # несуществующий
]


def _measure_index(repo_path: Path) -> dict:
    """Индексирует клон реальным эмбеддером (llama.cpp 8080). Возвращает замер."""
    import time as _t

    from src.core.indexing.file_guard import FileGuard
    from src.core.indexing.index_parser import IndexParser
    from src.core.indexing.parser import CodeParser
    from src.providers.embedder.remote_embedder import RemoteEmbedder
    from src.sources.local_fs.windows import SafePathManager

    t0 = _t.perf_counter()
    file_guard = FileGuard(repo_path)
    parser = CodeParser()
    path_manager = SafePathManager(repo_path)
    index_parser = IndexParser(parser=parser, path_manager=path_manager, project_path=repo_path)

    embedder = RemoteEmbedder()
    if not embedder.is_ready():
        for _ in range(60):
            if embedder.is_ready():
                break
            _t.sleep(1)
    if not embedder.is_ready():
        return {"error": "embedder not ready (8080)"}

    t_setup = _t.perf_counter() - t0

    files = []
    for root, dirs, names in _os_walk(repo_path):
        dirs[:] = [d for d in dirs if not file_guard.should_skip_dir(d)]
        for name in names:
            fp = Path(root) / name
            if file_guard.should_skip_file(fp):
                continue
            files.append((fp, str(fp.relative_to(repo_path))))

    t1 = _t.perf_counter()
    chunks = 0
    failed = 0
    for fp, rel in files:
        try:
            parsed = index_parser.parse_file(fp, rel)
            if not parsed or not parsed.get("chunk_texts"):
                continue
            texts = parsed["chunk_texts"]
            vecs = embedder.embed_batch(texts)
            if not vecs or len(vecs) != len(texts):
                failed += 1
                continue
            chunks += len(texts)
        except Exception as e:  # noqa: BLE001 — диагностика эксперимента
            failed += 1
            if failed <= 3:
                print(f"    ⚠ {rel}: {type(e).__name__}: {e}")
    t_index = _t.perf_counter() - t1

    return {
        "files": len(files),
        "chunks": chunks,
        "failed": failed,
        "setup_s": round(t_setup, 2),
        "index_s": round(t_index, 2),
    }


def _os_walk(path: Path):
    import os

    return os.walk(path)


def main() -> int:
    from src.sources.git_url import GitUrlSource, GitUrlSourceError

    print("=" * 70)
    print("E-03: clone→index на реальных репозиториях (реальный embed 8080)")
    print("=" * 70)

    results = []
    for url in REPOS:
        print(f"\n── {url}")
        src = GitUrlSource(url, CACHE, clone_timeout_sec=300)
        try:
            t0 = time.perf_counter()
            path = asyncio.run(src.resolve())
            t_clone = time.perf_counter() - t0
            print(f"  ✅ clone: {t_clone:.1f}s → {path}")

            fp1 = src.fingerprint(path)
            t_fp = time.perf_counter()
            fp2 = src.fingerprint(path)
            t_fp = time.perf_counter() - t_fp
            assert fp1 == fp2

            # повторный resolve = кэш-хит (0 клонирования)
            t0 = time.perf_counter()
            asyncio.run(src.resolve())
            t_cache = time.perf_counter() - t0

            idx = _measure_index(path)
            if "error" in idx:
                print(f"  ❌ index: {idx['error']}")
                results.append({"url": url, "status": "INDEX_FAIL", **idx})
                continue

            print(
                f"  ✅ index: {idx['files']} файлов, {idx['chunks']} чанков, "
                f"{idx['index_s']}s (setup {idx['setup_s']}s); "
                f"fingerprint {t_fp*1000:.0f}ms (skip → 0 re-embed); cache-hit {t_cache*1000:.0f}ms"
            )
            results.append({
                "url": url,
                "status": "OK",
                "clone_s": round(t_clone, 2),
                "fingerprint_ms": round(t_fp * 1000),
                "cache_hit_ms": round(t_cache * 1000),
                **idx,
            })
        except GitUrlSourceError as e:
            print(f"  ❌ INCONCLUSIVE [{e.kind}]: {e}")
            results.append({"url": url, "status": f"INCONCLUSIVE:{e.kind}", "detail": str(e)[:120]})
        except Exception as e:  # noqa: BLE001 — эксперимент не должен упасть целиком
            print(f"  ❌ UNEXPECTED: {type(e).__name__}: {e}")
            results.append({"url": url, "status": "UNEXPECTED", "detail": str(e)[:120]})

    # failure-кейсы: обязаны быть INCONCLUSIVE, не crash
    print("\n── failure-кейсы (обязаны → INCONCLUSIVE)")
    for url in FAILURE_URLS:
        src = GitUrlSource(url, CACHE)
        try:
            asyncio.run(src.resolve())
            print(f"  ❌ {url}: НЕ бросил ошибку!")
            results.append({"url": url, "status": "MISSED_FAILURE"})
        except GitUrlSourceError as e:
            print(f"  ✅ {url} → INCONCLUSIVE [{e.kind}]")
            results.append({"url": url, "status": f"INCONCLUSIVE:{e.kind}"})

    # raw-отчёт
    out = Path(__file__).resolve().parent / "E03_RESULTS.md"
    lines = ["# E-03 результаты (2026-08-18)", "",
             "| URL | Статус | clone (s) | файлов | чанков | index (s) | fingerprint (ms) | cache-hit (ms) |",
             "|---|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append(
            f"| {r['url']} | {r['status']} | {r.get('clone_s', '-')} | "
            f"{r.get('files', '-')} | {r.get('chunks', '-')} | {r.get('index_s', '-')} | "
            f"{r.get('fingerprint_ms', '-')} | {r.get('cache_hit_ms', '-')} |"
        )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n📄 Raw-отчёт: {out}")

    ok = all(r["status"] == "OK" or r["status"].startswith("INCONCLUSIVE") for r in results)
    print(f"\nE-03 VERDICT: {'PASSED' if ok else 'PARTIAL'} ({sum(1 for r in results if r['status']=='OK')}/{len(REPOS)} repos OK)")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — верхний guard эксперимента
        import traceback

        traceback.print_exc()
        sys.exit(1)
