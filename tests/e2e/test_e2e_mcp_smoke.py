"""E2E smoke-тест через реальный путь (без моков): G-2 (ISSUE.md).

Сквозная проверка: реальный embedder (llama.cpp :8080) → реальная LanceDB
(временная, изолированная) → реальный поиск (Searcher.search_with_mode, fast).

В отличие от unit-тестов G-1 (моки MagicMock), здесь embedder НЕ мокается:
вектор запроса и вектор чанков получает реальный llama-server. Проверяется
корректность входа→выхода (§2.3): запрос про move_chunks_metadata обязан
вернуть чанк из src/core/indexing/file_move_manager.py.

Требования:
  - живой llama-server на 127.0.0.1:8080 (LLAMA_CPP_ENABLED=true);
  - EMBEDDING_DIMENSION не задан в .env (default 384, совпадает с llama.cpp).

Запуск (вне обычного pytest tests/):
    MSCODEBASE_E2E=1 python -m pytest tests/e2e/test_e2e_mcp_smoke.py -v

Без MSCODEBASE_E2E тест скипается — не ломает полный прогон/CI.
"""

import gc
import os
import shutil
import socket
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("MSCODEBASE_E2E") != "1",
    reason=(
        "E2E MCP smoke: требует живого llama-server (127.0.0.1:8080). "
        "Запуск: MSCODEBASE_E2E=1 python -m pytest tests/e2e/test_e2e_mcp_smoke.py -v"
    ),
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Реальные файлы кодовой базы — «правильный вход» для проверки входа→выхода.
_E2E_FILES = [
    PROJECT_ROOT / "src" / "core" / "indexing" / "file_move_manager.py",
    PROJECT_ROOT / "src" / "core" / "search" / "bm25.py",
    PROJECT_ROOT / "src" / "core" / "search" / "fts5_index.py",
]


def _llama_cpp_online() -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex(("127.0.0.1", 8080)) == 0
    except OSError:
        return False


@pytest.fixture(scope="module")
def e2e_stack(tmp_path_factory):
    """Реальный embedder + временная LanceDB + реальные файлы проекта."""
    from src.core.indexing.file_guard import FileGuard
    from src.core.indexing.indexer import Indexer
    from src.core.search.engine import Searcher
    from src.providers.embedder.remote_embedder import RemoteEmbedder

    assert _llama_cpp_online(), (
        "llama-server не отвечает на 127.0.0.1:8080. "
        "Запустите MCP (LLAMA_CPP_ENABLED=true) перед E2E-тестом."
    )

    embedder = RemoteEmbedder()
    # RemoteEmbedder.__init__ стартует 3 фоновых потока (init/scanner/preload):
    # _init_provider_async ставит mode="onnx" (LM Studio недоступен), и следующий
    # embed упадёт. Как server_factory (_start_llama_sync) — фиксируем llama_cpp
    # под _mode_lock ПОСЛЕ завершения инициализации и останавливаем сканер.
    embedder._init_thread.join(timeout=15)
    embedder._scanner_stop.set()
    with embedder._mode_lock:
        embedder.mode = "llama_cpp"
        assert embedder.mode == "llama_cpp"
    # Реальная размерность llama.cpp должна совпадать с конфигом (default 384).
    assert embedder.embedding_dim == 384, (
        f"EMBEDDING_DIMENSION={embedder.embedding_dim}, а llama.cpp отдаёт 384-dim. "
        "Уберите EMBEDDING_DIMENSION из .env."
    )

    db_dir = tmp_path_factory.mktemp("e2e_lancedb")
    project = PROJECT_ROOT / "src" / "core"
    file_guard = FileGuard(project)
    indexer = Indexer(
        db_dir, embedder, file_guard,
        project_path=project, enable_summaries=False,
    )

    # Индексируем реальные файлы кодовой базы (реальный embed через llama.cpp).
    indexed = 0
    for fp in _E2E_FILES:
        if indexer.index_file(fp, project):
            indexed += 1
    assert indexed >= 2, f"Ожидалось >= 2 проиндексированных файла, получено {indexed}"

    searcher = Searcher(indexer, embedder)
    indexer.searcher = searcher
    # Fast-путь не использует reranker (см. search_with_mode, MODE_FAST).
    searcher._multi_reranker = None
    searcher._multi_reranker_initialized = True

    yield searcher, indexer

    # LanceDB не имеет close(): освобождаем mmap-локи через GC, затем удаляем.
    gc.collect()
    shutil.rmtree(db_dir, ignore_errors=True)


def test_e2e_real_embed_returns_expected_file(e2e_stack):
    """Запрос про move_chunks_metadata → реальный чанк из file_move_manager.py.

    Проверка корректности входа→выхода (§2.3): правильный запрос попадает
    в правильный файл через полный реальный путь (embed → vector → FTS5).
    """
    searcher, _ = e2e_stack

    res = searcher.search_with_mode("move_chunks_metadata", mode="fast", limit=5)

    assert res["mode"] == "fast"
    assert res["cache_hit"] is False
    assert res["results"], "E2E: пустой результат для реального индекса"
    files = {r["metadata"]["file"] for r in res["results"]}
    assert any("file_move_manager" in f for f in files), (
        f"E2E: правильный вход не попал в правильный выход. Результаты: {sorted(files)}"
    )

    # Реальные чанки несут текст и score — не пустые декоративные записи.
    # Реальный формат результата: final_score (не score — так в unit-моке G-1).
    top = res["results"][0]
    assert top["text"].strip(), "E2E: чанк без текста"
    assert top.get("final_score", 0.0) > 0.0, "E2E: чанк без final_score"


def test_e2e_second_call_cache_hit_same_results(e2e_stack):
    """Повторный вызов того же запроса → cache_hit=True и тот же результат.

    Кэш работает на реальном стеке (P2-5), а не только на моках.
    """
    searcher, _ = e2e_stack

    first = searcher.search_with_mode("move_chunks_metadata", mode="fast", limit=5)
    second = searcher.search_with_mode("move_chunks_metadata", mode="fast", limit=5)

    assert second["cache_hit"] is True
    assert [r["metadata"]["file"] for r in second["results"]] == [
        r["metadata"]["file"] for r in first["results"]
    ]
