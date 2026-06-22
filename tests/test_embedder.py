"""
Тесты для Embedder.
Все проверки адаптивные — не привязаны к конкретной модели.
"""

import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_model_dir():
    """Создаёт временную папку для моделей."""
    temp_dir = Path(tempfile.mkdtemp())
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.mark.slow
def test_embedder_download_and_load(temp_model_dir):
    """Тест скачивания и загрузки модели."""
    from src.core.embedder import Embedder

    embedder = Embedder(model_dir=temp_model_dir, model_name="BAAI/bge-m3")
    assert embedder.load(), "Модель должна загрузиться"
    assert embedder.session is not None
    assert embedder.tokenizer is not None
    # Размерность определена автоматически
    assert embedder.dimension > 0


@pytest.mark.slow
def test_embedder_single_text(temp_model_dir):
    """Тест эмбеддинга одного текста."""
    from src.core.embedder import Embedder

    embedder = Embedder(model_dir=temp_model_dir, model_name="BAAI/bge-m3")
    embedder.load()

    embedding = embedder.embed("Hello, world!")

    assert isinstance(embedding, list)
    # Размерность динамическая — берём из модели
    assert len(embedding) == embedder.dimension
    assert all(isinstance(x, float) for x in embedding)


@pytest.mark.slow
def test_embedder_batch(temp_model_dir):
    """Тест батч-эмбеддинга."""
    from src.core.embedder import Embedder

    embedder = Embedder(model_dir=temp_model_dir, model_name="BAAI/bge-m3")
    embedder.load()

    texts = ["Hello", "World", "Test"]
    embeddings = embedder.embed_batch(texts)

    assert len(embeddings) == 3
    assert all(len(emb) == embedder.dimension for emb in embeddings)


@pytest.mark.slow
def test_embedder_similarity(temp_model_dir):
    """Тест, что похожие тексты имеют близкие эмбеддинги."""
    import numpy as np

    from src.core.embedder import Embedder

    embedder = Embedder(model_dir=temp_model_dir, model_name="BAAI/bge-m3")
    embedder.load()

    emb1 = np.array(embedder.embed("Python is a programming language"))
    emb2 = np.array(embedder.embed("Python is a coding language"))
    emb3 = np.array(embedder.embed("The weather is nice today"))

    # Косинусное сходство
    sim_12 = np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2))
    sim_13 = np.dot(emb1, emb3) / (np.linalg.norm(emb1) * np.linalg.norm(emb3))

    # Похожие тексты должны иметь большее сходство
    assert sim_12 > sim_13, "Похожие тексты должны быть ближе"


@pytest.mark.slow
def test_embedder_api_prefixes(temp_model_dir):
    """Тест, что префиксы правильно определяются для разных моделей."""
    from src.core.embedder import _detect_prefixes

    # BGE-M3
    q, d = _detect_prefixes("BAAI/bge-m3")
    assert "Represent this sentence" in q
    assert d == ""

    # E5
    q, d = _detect_prefixes("intfloat/multilingual-e5-small")
    assert q == "query: "
    assert d == "passage: "

    # Неизвестная модель — без префиксов
    q, d = _detect_prefixes("some-random-model")
    assert q == ""
    assert d == ""


@pytest.mark.slow
def test_embedder_dimension_detection(temp_model_dir):
    """Тест, что размерность определяется автоматически при загрузке."""
    from src.core.embedder import Embedder

    embedder = Embedder(model_dir=temp_model_dir, model_name="BAAI/bge-m3")
    assert embedder.dimension == 1024  # fallback до загрузки

    embedder.load()
    # После загрузки — реальная размерность
    assert embedder.dimension > 0
    # BGE-M3 имеет размерность 1024
    assert embedder.dimension == 1024
