"""Тесты chunk-level content-addressed cache (src/core/indexing/index_pipeline.py).

Проверяет РЕАЛЬНУЮ логику IndexPipeline.process_file: чанки с неизменным
SHA256-хэшем переиспользуют вектор из БД и не вызывают embed_batch.
Раньше тест сам повторял логику кэша вручную — теперь гоняется через
production-код с mock embedder/table.
"""

import hashlib
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd

from src.core.indexing.index_pipeline import IndexPipeline


def _chunk_hash(text: str) -> str:
    return "ch:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


class _CountingEmbedder:
    """Mock embedder: считает вызовы embed_batch, векторы детерминированы."""

    def __init__(self):
        self.call_count = 0
        self.embed_calls: list[list[str]] = []

    def embed_batch(self, texts):
        self.call_count += 1
        self.embed_calls.append(list(texts))
        # i-й текст получает вектор [0.1 + i] * 4 — по нему проверяем
        # соответствие "правильный вход → правильный выход".
        return [[0.1 + i] * 4 for i in range(len(texts))]


class _FakeTable:
    """Минимальная имитация LanceDB table для chunk-кэша (search/where/select/to_pandas)."""

    def __init__(self, known: dict):
        # known: chunk_hash -> vector
        self._known = known

    def search(self):
        return self

    def where(self, expr, prefilter=False):
        return self

    def select(self, cols):
        return self

    def to_pandas(self):
        rows = [{"chunk_hash": h, "vector": v} for h, v in self._known.items()]
        if rows:
            return pd.DataFrame(rows)
        return pd.DataFrame(columns=["chunk_hash", "vector"])


def _make_pipeline(embedder, table=None, chunk_texts=None):
    index_parser = MagicMock()
    index_parser.parse_file.return_value = {
        "chunk_texts": chunk_texts if chunk_texts is not None else [
            "def foo(): return 1",
            "def bar(): return 2",
        ],
        "_ast_symbols": (None, None),
        "chunk_texts_full": [],
        "chunk_metadatas": [],
        "health": {"score": 0.0, "band": ""},
    }
    return IndexPipeline(
        embedder=embedder,
        parser=None,  # без SymbolIndex-обновления
        index_parser=index_parser,
        symbol_index=MagicMock(),
        symbol_index_lock=threading.Lock(),
        project_path=Path("proj"),
        table=table,
    )


def test_chunk_cache_basic():
    """Первый прогон — все чанки новые → embed; второй — кэш из БД → 0 вызовов."""
    embedder = _CountingEmbedder()
    pipeline = _make_pipeline(embedder, chunk_texts=["chunk_a", "chunk_b", "chunk_c"])

    # Прогон 1: пустая таблица → все 3 чанка эмбеддятся
    known = {_chunk_hash(t): [0.1] * 4 for t in ["chunk_a", "chunk_b", "chunk_c"]}
    result1 = pipeline.process_file(
        "a.py", Path("proj/a.py"), "content1", current_hash="h1"
    )
    assert embedder.call_count == 1
    assert len(result1["chunk_texts"]) == 3
    assert result1["chunk_hashes"] == list(known.keys())

    # Прогон 2: таблица уже знает все хэши → embed_batch НЕ вызывается
    embedder2 = _CountingEmbedder()
    pipeline2 = _make_pipeline(embedder2, table=_FakeTable(known), chunk_texts=["chunk_a", "chunk_b", "chunk_c"])
    result2 = pipeline2.process_file(
        "a.py", Path("proj/a.py"), "content2", current_hash="h2"
    )
    assert embedder2.call_count == 0
    assert result2["embeddings"] == [[0.1] * 4] * 3


def test_chunk_cache_invalidation():
    """Изменённый чанк получает новый хэш → переэмбеддится, неизменный — из кэша."""
    old = ["def foo(): return 1", "def bar(): return 2"]
    new = ["def foo(): return 1", "def bar(): return 42"]

    # В БД известен только хэш неизменного foo
    known = {_chunk_hash(old[0]): [0.9] * 4}
    embedder = _CountingEmbedder()
    pipeline = _make_pipeline(embedder, table=_FakeTable(known), chunk_texts=new)

    result = pipeline.process_file(
        "mod.py", Path("proj/mod.py"), "content", current_hash="h3"
    )

    assert embedder.call_count == 1
    assert embedder.embed_calls == [["def bar(): return 42"]]
    # foo — вектор из БД [0.9]*4, bar — свеже-эмбедженный [0.1]*4 (индекс 0 в texts_to_embed)
    assert result["embeddings"][0] == [0.9] * 4
    assert result["embeddings"][1] == [0.1] * 4


def test_chunk_cache_all_new():
    """Новый файл — все чанки cache miss (чужой хэш в БД не совпадает)."""
    texts = ["a", "b", "c", "d", "e"]
    embedder = _CountingEmbedder()
    pipeline = _make_pipeline(
        embedder, table=_FakeTable({"ch:old_hash_only": [0.1] * 4}), chunk_texts=texts
    )

    result = pipeline.process_file("new.py", Path("proj/new.py"), "content", current_hash="h4")

    assert embedder.call_count == 1
    assert len(result["embeddings"]) == 5
    # каждый текст получил свой детерминированный вектор (i-й текст → [0.1 + i] * 4)
    assert result["embeddings"][0] == [0.1] * 4
    assert result["embeddings"][4] == [4.1] * 4


def test_chunk_cache_empty_file():
    """Пустое содержимое → None без вызова embedder."""
    embedder = _CountingEmbedder()
    pipeline = _make_pipeline(embedder)
    result = pipeline.process_file("empty.py", Path("proj/empty.py"), "   ", current_hash="h5")
    assert result is None
    assert embedder.call_count == 0


def test_chunk_cache_disabled_without_table():
    """table=None (кэш отключён) → embed_batch вызывается на каждом прогоне."""
    embedder = _CountingEmbedder()
    pipeline = _make_pipeline(embedder, table=None)

    pipeline.process_file("x.py", Path("proj/x.py"), "content", current_hash="h6")
    pipeline.process_file("x.py", Path("proj/x.py"), "content", current_hash="h6")

    assert embedder.call_count == 2


def test_chunk_cache_embeddings_match_input():
    """Корректность содержимого: правильный текст → правильный вектор (не только "не упало")."""
    texts = ["alpha", "beta", "gamma"]
    embedder = _CountingEmbedder()
    pipeline = _make_pipeline(embedder, table=_FakeTable({}), chunk_texts=texts)

    result = pipeline.process_file("m.py", Path("proj/m.py"), "content", current_hash="h7")

    # i-й текст обязан получить вектор [0.1 + i] * 4 — проверяем перестановки
    assert result["embeddings"][0] == [0.1] * 4  # alpha
    assert result["embeddings"][1] == [1.1] * 4  # beta
    assert result["embeddings"][2] == [2.1] * 4  # gamma

    # Кэш-прогон: те же тексты → те же векторы (из БД)
    known = {
        _chunk_hash(t): v
        for t, v in zip(texts, [[0.1] * 4, [1.1] * 4, [2.1] * 4])
    }
    embedder2 = _CountingEmbedder()
    pipeline2 = _make_pipeline(embedder2, table=_FakeTable(known), chunk_texts=texts)
    result2 = pipeline2.process_file("m.py", Path("proj/m.py"), "content", current_hash="h7b")

    assert embedder2.call_count == 0
    assert result2["embeddings"] == result["embeddings"]
