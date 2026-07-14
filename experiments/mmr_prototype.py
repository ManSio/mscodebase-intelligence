"""
MMR (Maximal Marginal Relevance) Prototype для MSCodeBase.
Запуск: python experiments/mmr_prototype.py

Тестирует MMR на реальных данных поиска MSCodeBase и сравнивает с текущим pipeline.
"""
import sys
import os
import time
import json
import numpy as np
from pathlib import Path

# Добавляем корень проекта в путь
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ─── MMR Implementation (pure numpy, 20 строк) ──────────────────

def mmr_rerank(
    query_vector: np.ndarray,
    doc_vectors: np.ndarray,
    doc_scores: np.ndarray,
    lambda_param: float = 0.6,
    top_k: int = 5,
) -> tuple[list[int], list[float]]:
    """MMR-реранкинг: баланс релевантности и разнообразия.

    Args:
        query_vector: Нормализованный вектор запроса (shape: [D])
        doc_vectors: Нормализованные векторы документов (shape: [N, D])
        doc_scores: Исходные оценки релевантности (shape: [N])
        lambda_param: Баланс (0=max diversity, 1=max relevance)
        top_k: Сколько результатов вернуть

    Returns:
        indices: Индексы отобранных документов (в порядке отбора)
        mmr_scores: Финальные MMR-оценки
    """
    n = len(doc_scores)
    selected = []
    candidate_mask = np.ones(n, dtype=bool)

    # Нормализуем scores в [0,1] для совместимости
    scores_norm = doc_scores.copy()
    if scores_norm.max() > scores_norm.min():
        scores_norm = (scores_norm - scores_norm.min()) / (scores_norm.max() - scores_norm.min())

    for _ in range(min(top_k, n)):
        if candidate_mask.sum() == 0:
            break

        candidates = np.where(candidate_mask)[0]

        # Relevance term: lambda * Sim(Q, D_i)
        relevance = lambda_param * scores_norm[candidates]

        # Diversity term: -(1-lambda) * max(Sim(D_i, D_j)) for j in selected
        if selected:
            # Cosine similarity between candidates and all selected
            sim_to_selected = doc_vectors[candidates] @ doc_vectors[selected].T
            diversity = (1 - lambda_param) * sim_to_selected.max(axis=1)
        else:
            diversity = np.zeros(len(candidates))

        mmr = relevance - diversity
        best_idx = candidates[mmr.argmax()]

        selected.append(int(best_idx))
        candidate_mask[best_idx] = False

    return selected, [float(scores_norm[i]) for i in selected]


# ─── Тест на реальных данных МSCodeBase ─────────────────────────

def test_mmr_on_project():
    """Тестирует MMR, подключаясь к реальному search engine MSCodeBase."""
    print("=" * 65)
    print("🔬 MMR Prototype Test на MSCodeBase")
    print("=" * 65)

    # Подключаем search engine
    try:
        from src.core.config import settings
        from src.core.search.engine import Searcher
        from src.core.di_container import ServiceCollection
        from src.core.indexer import Indexer
        from src.core.remote_embedder import RemoteEmbedder
    except ImportError as e:
        print(f"❌ Не могу импортировать модули MSCodeBase: {e}")
        print("   Запустите из корня проекта: python experiments/mmr_prototype.py")
        return

    # Создаём минимальный DI контейнер для получения indexer + embedder
    print("\n📦 Инициализация сервисов...")
    try:
        services = ServiceCollection()
        services.add_singleton(RemoteEmbedder)
        services.add_singleton(Indexer)
        services.resolve(RemoteEmbedder)  # форсируем инициализацию

        embedder = services.resolve(RemoteEmbedder)
        indexer = services.resolve(Indexer)

        # Создаём Searcher
        searcher = Searcher(indexer, embedder)
    except Exception as e:
        print(f"❌ Ошибка инициализации: {e}")
        # Используем fallback на прямые вызовы
        return test_mmr_fallback(searcher=None)

    # Тестовые запросы
    queries = [
        "def hybrid_search_async",
        "watchdog heartbeat monitoring",
        "embed_batch ONNX quantized",
        "reranker bge-m3 cross-encoder",
        "index_guard schema validation",
    ]

    results = []
    for query in queries:
        print(f"\n📝 Запрос: {query}")
        try:
            t0 = time.perf_counter()
            search_results = searcher.search(query, limit=10)
            dt = (time.perf_counter() - t0) * 1000
            print(f"   Поиск: {dt:.0f}ms, результатов: {len(search_results)}")

            if search_results:
                # Анализируем разнообразие
                files = [r.get("metadata", {}).get("file", "?") for r in search_results]
                unique_files = len(set(files))
                print(f"   Файлов: {unique_files}/{len(search_results)}")
                for r in search_results[:5]:
                    f = r.get("metadata", {}).get("file", "?")
                    s = r.get("final_score", 0)
                    print(f"     [{s:.3f}] {f}")

        except Exception as e:
            print(f"   ❌ {type(e).__name__}: {e}")

    print("\n" + "=" * 65)
    print("Тест завершён")
    print("=" * 65)


def test_mmr_fallback(searcher=None):
    """Fallback: тест MMR на синтетических данных + анализ результатов текущего поиска."""
    print("\n📊 Fallback: тест MMR на random-данных + анализ реального поиска")

    # Генерируем синтетические векторы (100 документов, 768d)
    np.random.seed(42)
    n_docs = 100
    n_dim = 768

    query_vec = np.random.randn(n_dim).astype(np.float32)
    query_vec /= np.linalg.norm(query_vec)

    doc_vecs = np.random.randn(n_docs, n_dim).astype(np.float32)
    doc_vecs /= np.linalg.norm(doc_vecs, axis=1, keepdims=True)

    # Симулируем, что первые 30 документов — это копии одного (похожие векторы)
    base_vec = np.random.randn(n_dim).astype(np.float32)
    base_vec /= np.linalg.norm(base_vec)
    for i in range(30):
        noise = np.random.randn(n_dim).astype(np.float32) * 0.05
        doc_vecs[i] = base_vec + noise
        doc_vecs[i] /= np.linalg.norm(doc_vecs[i])

    # Cosine similarity как scores
    scores = doc_vecs @ query_vec

    print(f"\n📊 Синтетические данные: {n_docs} документов, {n_dim}d")
    print(f"   Первые 30 документов — почти копии (noise=0.05)")

    # Тест 1: Без MMR (top-5 по relevance)
    top5_relevance = np.argsort(-scores)[:5]
    print(f"\n【Без MMR】Top-5 (только relevance):")
    for i, idx in enumerate(top5_relevance):
        label = "🔄 КОПИЯ" if idx < 30 else "📄"
        print(f"   {i+1}. [{scores[idx]:.4f}] doc_{idx} {label}")

    # Тест 2: С MMR (lambda=0.6)
    mmr_indices, mmr_scores = mmr_rerank(query_vec, doc_vecs, scores, lambda_param=0.6, top_k=5)
    print(f"\n【С MMR】λ=0.6 Top-5:")
    for i, idx in enumerate(mmr_indices):
        label = "🔄 КОПИЯ" if idx < 30 else "📄"
        print(f"   {i+1}. [{mmr_scores[i]:.4f}] doc_{idx} {label}")

    # Тест 3: Влияние lambda
    print(f"\n【Влияние λ】на разнообразие:")
    for lam in [0.0, 0.3, 0.5, 0.7, 1.0]:
        indices, _ = mmr_rerank(query_vec, doc_vecs, scores, lambda_param=lam, top_k=5)
        copies = sum(1 for i in indices if i < 30)
        print(f"   λ={lam:.1f}: {copies}/5 копий, файлы={indices}")

    # Тест 4: Производительность
    print(f"\n【Производительность MMR】")
    for size in [50, 100, 500, 1000]:
        test_vecs = np.random.randn(size, n_dim).astype(np.float32)
        test_vecs /= np.linalg.norm(test_vecs, axis=1, keepdims=True)
        test_scores = test_vecs @ query_vec

        t0 = time.perf_counter()
        for _ in range(100):
            mmr_rerank(query_vec, test_vecs, test_scores, lambda_param=0.6, top_k=10)
        dt = (time.perf_counter() - t0) * 10  # avg per call

        print(f"   {size} docs → {dt:.2f}ms (top-10)")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--live":
        test_mmr_on_project()
    else:
        test_mmr_fallback()
