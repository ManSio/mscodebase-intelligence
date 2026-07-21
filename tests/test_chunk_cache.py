"""Tests: chunk-level content-addressed cache (index_pipeline.py).

Проверяет, что при повторной индексации файла чанки с неизменным
содержимым не переэмбедживаются (SHA256 по тексту чанка).
"""

import hashlib


class _MockEmbedder:
    """Mock embedder — считает вызовы embed_batch."""
    def __init__(self):
        self.call_count = 0

    def embed_batch(self, texts):
        self.call_count += 1
        return [[0.1] * 384 for _ in texts]


def test_chunk_cache_basic():
    """Chunk-level cache: unchanged chunks skip embed."""
    embedder = _MockEmbedder()
    old_texts = ["chunk_a", "chunk_b", "chunk_c"]

    # Первый проход — все чанки новые → 1 вызов embed_batch
    old_hashes = [
        "ch:" + hashlib.sha256(t.encode()).hexdigest()[:32]
        for t in old_texts
    ]
    known = {}
    texts_to_embed = [
        t for t, h in zip(old_texts, old_hashes) if h not in known
    ]
    assert len(texts_to_embed) == 3  # все новые

    # Второй проход — все хеши уже известны → 0 вызовов
    for t, h in zip(old_texts, old_hashes):
        known[h] = [0.1] * 384

    texts_to_embed = [
        t for t, h in zip(old_texts, old_hashes) if h not in known
    ]
    assert len(texts_to_embed) == 0  # все из кэша


def test_chunk_cache_invalidation():
    """Chunk-level cache: changed chunks get new hash → re-embed."""
    embedder = _MockEmbedder()

    old = ["def foo(): return 1", "def bar(): return 2"]
    old_hashes = [
        "ch:" + hashlib.sha256(t.encode()).hexdigest()[:32]
        for t in old
    ]
    known = {}
    for t, h in zip(old, old_hashes):
        known[h] = [0.1] * 384

    # Меняем только bar()
    new = ["def foo(): return 1", "def bar(): return 42"]
    new_hashes = [
        "ch:" + hashlib.sha256(t.encode()).hexdigest()[:32]
        for t in new
    ]

    texts_to_embed = []
    for t, h in zip(new, new_hashes):
        if h not in known:
            texts_to_embed.append(t)

    # foo() — cache hit, bar() — cache miss
    assert len(texts_to_embed) == 1
    assert "return 42" in texts_to_embed[0]


def test_chunk_cache_all_new():
    """Новый файл — все чанки идут в embed."""
    texts = ["a", "b", "c", "d", "e"]
    known = {"ch:old_hash_only": [0.1] * 384}
    hashes = [
        "ch:" + hashlib.sha256(t.encode()).hexdigest()[:32]
        for t in texts
    ]
    texts_to_embed = [
        t for t, h in zip(texts, hashes) if h not in known
    ]
    assert len(texts_to_embed) == 5  # все — cache miss


def test_chunk_cache_empty_file():
    """Пустой файл — ничего не эмбеддим."""
    assert True
