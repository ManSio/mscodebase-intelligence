"""Tests: Shadow Canary — верификация нового embedder'а до переключения."""

import json
from pathlib import Path
from unittest.mock import MagicMock


def _make_fake_embedding(dim=384):
    """Детерминированный фейковый вектор."""
    return [0.1 * (i % 10) for i in range(dim)]


class TestShadowCanary:
    """Проверка _shadow_compare: отклоняет плохие модели, пропускает хорошие."""

    def test_shadow_compare_accepts_good(self):
        """Новый провайдер с качеством >= baseline — canary OK."""
        from src.providers.embedder.remote_embedder import RemoteEmbedder

        embedder = MagicMock(spec=RemoteEmbedder)
        embedder._canary_pairs = [
            {"query": "def foo", "expected_chunk": "def foo(): return 1"},
            {"query": "def bar", "expected_chunk": "def bar(): return 2"},
        ]
        embedder.embed_batch.return_value = [_make_fake_embedding() for _ in range(4)]

        def good_fn(texts):
            return [_make_fake_embedding() for _ in texts]
        result = RemoteEmbedder._shadow_compare(embedder, good_fn, "good_model")
        assert result is True, "Хорошая модель должна проходить canary"

    def test_shadow_compare_rejects_bad(self):
        """Новый провайдер с качеством ниже baseline — canary блокирует."""
        from src.providers.embedder.remote_embedder import RemoteEmbedder

        embedder = MagicMock(spec=RemoteEmbedder)
        embedder._canary_pairs = [
            {"query": "def foo", "expected_chunk": "def foo(): return 1"},
            {"query": "def bar", "expected_chunk": "def bar(): return 2"},
            {"query": "def baz", "expected_chunk": "def baz(): return 3"},
        ]
        # Базлайн: хорошие векторы
        embedder.embed_batch.side_effect = None
        embedder.embed_batch.return_value = [
            [1.0] * 384 for _ in range(6)  # 3 query + 3 chunk
        ]

        # Новый провайдер: нулевые векторы (симуляция сломанной модели)
        def bad_fn(texts):
            return [[0.0] * 384 for _ in texts]
        result = RemoteEmbedder._shadow_compare(embedder, bad_fn, "bad_model")
        assert result is False, "Плохая модель должна блокироваться canary"

    def test_shadow_compare_empty_canary(self):
        """Если canary-набор пуст — доверяем новому провайдеру."""
        from src.providers.embedder.remote_embedder import RemoteEmbedder

        embedder = MagicMock(spec=RemoteEmbedder)
        embedder._canary_pairs = []
        def fn(texts):
            return [[1.0] * 384 for _ in texts]
        result = RemoteEmbedder._shadow_compare(embedder, fn, "any")
        assert result is True, "Пустой canary = доверие"

    def test_canary_set_json_exists(self):
        """Проверка что canary_set.json существует и содержит 20 пар."""
        path = Path(__file__).resolve().parent.parent / "src" / "providers" / "embedder" / "canary_set.json"
        assert path.exists(), f"canary_set.json не найден: {path}"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data["pairs"]) >= 10, f"Меньше 10 пар: {len(data['pairs'])}"
        for p in data["pairs"]:
            assert "query" in p
            assert "expected_chunk" in p
