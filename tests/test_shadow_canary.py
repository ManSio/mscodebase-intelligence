"""Tests: Shadow Canary — верификация нового embedder'а до переключения.

Обновлено 2026-08-12 (EXP-1 fail-closed): пустой canary / сбой базлайна /
collapse-to-constant / ниже абсолютного якоря — BLOCK, а не доверие.
Былые тесты использовали коллапс-фейки (одинаковый вектор на любой вход) —
само collapse-состояние, которое canary обязан ловить; заменены на per-pair
детерминированные векторы.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

from src.providers.embedder.remote_embedder import RemoteEmbedder, _vectors_collapsed


def _pair_vectors(n, dim=384):
    """n пар: query_i и chunk_i — ОДИН вектор (cos=1.0), между парами — разные.

    Отличается от старого `_make_fake_embedding` (одинаковый вектор на любой
    вход = collapse): здесь векторы пар различимы → дисперсия > 0.
    """
    return [[((i * 7 + k * 13) % 100) / 100.0 for k in range(dim)] for i in range(n)]


class TestVectorsCollapsed:
    def test_constant_vectors_collapsed(self):
        assert _vectors_collapsed([[1.0] * 384, [1.0] * 384]) is True

    def test_noisy_constant_collapsed(self):
        """±1% шум вокруг константы — всё ещё коллапс (EXP-1 b2)."""
        v = [[1.0 + 0.001 * (i + 1)] * 384 for i in range(3)]
        assert _vectors_collapsed(v) is True

    def test_distinct_vectors_not_collapsed(self):
        assert _vectors_collapsed(_pair_vectors(2)) is False

    def test_zero_vectors_collapsed(self):
        assert _vectors_collapsed([[0.0] * 384] * 4) is True

    def test_less_than_two_is_unverifiable(self):
        assert _vectors_collapsed([[1.0] * 384]) is True
        assert _vectors_collapsed([]) is True


class TestShadowCanary:
    """Проверка _shadow_compare: отклоняет плохие модели, пропускает хорошие."""

    def test_shadow_compare_accepts_good(self):
        """Новый провайдер с качеством >= baseline — canary OK."""
        embedder = MagicMock(spec=RemoteEmbedder)
        embedder._canary_pairs = [
            {"query": "def foo", "expected_chunk": "def foo(): return 1"},
            {"query": "def bar", "expected_chunk": "def bar(): return 2"},
        ]
        embedder.embed_batch.return_value = _pair_vectors(2)

        def good_fn(texts):
            return _pair_vectors(len(texts))
        result = RemoteEmbedder._shadow_compare(embedder, good_fn, "good_model")
        assert result is True, "Хорошая модель должна проходить canary"

    def test_shadow_compare_rejects_bad(self):
        """Новый провайдер с нулевыми векторами — canary блокирует."""
        embedder = MagicMock(spec=RemoteEmbedder)
        embedder._canary_pairs = [
            {"query": "def foo", "expected_chunk": "def foo(): return 1"},
            {"query": "def bar", "expected_chunk": "def bar(): return 2"},
            {"query": "def baz", "expected_chunk": "def baz(): return 3"},
        ]
        embedder.embed_batch.return_value = _pair_vectors(3)

        def bad_fn(texts):
            return [[0.0] * 384 for _ in texts]
        result = RemoteEmbedder._shadow_compare(embedder, bad_fn, "bad_model")
        assert result is False, "Плохая модель должна блокироваться canary"

    # ─── EXP-1 регрессии (fail-closed) ────────────────────────────────────

    def test_empty_canary_blocks(self):
        """Пустой canary-набор — BLOCK (fail-closed, EXP-1 (c)). Было: доверие."""
        embedder = MagicMock(spec=RemoteEmbedder)
        embedder._canary_pairs = []

        def fn(texts):
            return [[1.0] * 384 for _ in texts]
        result = RemoteEmbedder._shadow_compare(embedder, fn, "any")
        assert result is False, "Пустой canary = нет верификации → блокировать"

    def test_baseline_failure_blocks(self):
        """Сбой базлайна — BLOCK (fail-closed, EXP-1 (d)). Было: доверие."""
        embedder = MagicMock(spec=RemoteEmbedder)
        embedder._canary_pairs = [
            {"query": "def foo", "expected_chunk": "def foo(): return 1"},
            {"query": "def bar", "expected_chunk": "def bar(): return 2"},
        ]
        embedder.embed_batch.side_effect = RuntimeError("embedder down")

        def fn(texts):
            return _pair_vectors(len(texts))
        result = RemoteEmbedder._shadow_compare(embedder, fn, "any")
        assert result is False, "Сбой базлайна = нет верификации → блокировать"

    def test_collapse_to_constant_blocks(self):
        """Новый провайдер возвращает constant-векторы — BLOCK (EXP-1 (b)).

        Ключевая регрессия: constant-векторы дают sims=1.0 и проходили
        относительную метрику (старый код: PASSED). Ловит collapse-детектор.
        """
        embedder = MagicMock(spec=RemoteEmbedder)
        embedder._canary_pairs = [
            {"query": "def foo", "expected_chunk": "def foo(): return 1"},
            {"query": "def bar", "expected_chunk": "def bar(): return 2"},
        ]
        embedder.embed_batch.return_value = _pair_vectors(2)

        def collapsed_fn(texts):
            return [[1.0] * 384 for _ in texts]
        result = RemoteEmbedder._shadow_compare(embedder, collapsed_fn, "constant_model")
        assert result is False, "Collapse-to-constant обязан блокироваться"

    def test_baseline_below_absolute_quality_blocks(self):
        """Базлайн сам ниже абсолютного якоря — BLOCK (UNKNOWN, не доверие)."""
        embedder = MagicMock(spec=RemoteEmbedder)
        embedder._canary_pairs = [
            {"query": "def foo", "expected_chunk": "def foo(): return 1"},
            {"query": "def bar", "expected_chunk": "def bar(): return 2"},
        ]
        # Запросы и чанки — ортогональные векторы (cos=0 → old_mean=0)
        def baseline_side(texts, is_query=False):
            if is_query:
                return [[1.0] + [0.0] * 383, [0.0, 1.0] + [0.0] * 382]
            return [[0.0, 1.0] + [0.0] * 382, [1.0] + [0.0] * 383]

        embedder.embed_batch.side_effect = baseline_side

        def good_fn(texts):
            return _pair_vectors(len(texts))
        result = RemoteEmbedder._shadow_compare(embedder, good_fn, "any")
        assert result is False, "Вырожденный базлайн → UNKNOWN → блок"

    def test_new_below_absolute_quality_blocks(self):
        """Новый провайдер выше relative-порога, но ниже абсолютного якоря — BLOCK.

        Кейс EXP-1: old_mean=0.53 → relative threshold 0.477; new_mean=0.49
        проходит relative (0.49 > 0.477), но 0.49 < 0.5 (абсолютный якорь) → блок.
        """
        embedder = MagicMock(spec=RemoteEmbedder)
        embedder._canary_pairs = [
            {"query": "def foo", "expected_chunk": "def foo(): return 1"},
            {"query": "def bar", "expected_chunk": "def bar(): return 2"},
        ]
        sim_base, sim_new = 0.53, 0.49

        def aligned_pair(axis, sim):
            q = [0.0] * 384
            q[axis] = 1.0
            c = [0.0] * 384
            c[axis] = sim
            c[axis + 1] = (1 - sim * sim) ** 0.5
            return q, c

        def baseline_side(texts, is_query=False):
            pairs = [aligned_pair(0, sim_base), aligned_pair(2, sim_base)]
            return [p[0] if is_query else p[1] for p in pairs]

        embedder.embed_batch.side_effect = baseline_side

        # Новый провайдер: query→q', chunk→c' (cos=0.49), пары различимы (не коллапс)
        class WeakFn:
            def __init__(self):
                self._call = 0

            def __call__(self, texts):
                pairs = [aligned_pair(0, sim_new), aligned_pair(2, sim_new)]
                idx = 1 if self._call % 2 else 0  # 1-й вызов — queries, 2-й — chunks
                self._call += 1
                return [p[idx] for p in pairs]

        result = RemoteEmbedder._shadow_compare(embedder, WeakFn(), "weak_model")
        assert result is False, "Ниже абсолютного якоря → блок"

    def test_canary_set_json_exists(self):
        """Проверка что canary_set.json существует и содержит 20 пар."""
        path = Path(__file__).resolve().parent.parent / "src" / "providers" / "embedder" / "canary_set.json"
        assert path.exists(), f"canary_set.json не найден: {path}"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data["pairs"]) >= 10, f"Меньше 10 пар: {len(data['pairs'])}"
        for p in data["pairs"]:
            assert "query" in p
            assert "expected_chunk" in p
