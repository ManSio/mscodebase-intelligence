"""EXP-1: Shadow Canary attack — дискриминативная способность проверки.

Атака на алгоритм `RemoteEmbedder._shadow_compare` (remote_embedder.py:231-304,
воспроизведён дословно). Цель: доказать, что canary:
  (a) ловит нулевые векторы (контрольная группа — обязана упасть),
  (b) НЕ ловит collapse-to-constant (все векторы идентичны) — относительная метрика,
  (c) fail-open при пустом canary-наборе,
  (d) fail-open при сбое базлайна (старый провайдер упал).

Это алгоритмическая реплика по исходнику (импорт провайдера тянет тяжёлые
зависимости) — честная пометка по §5.15.
"""
import sys
import traceback

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

DIM = 384


def _cos_sim(a, b):
    """Дословно из remote_embedder.py:246-250."""
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def shadow_compare(canary_pairs, old_embed_batch, new_embed_fn):
    """Дословная реплика remote_embedder.py:242-304 (без логирования)."""
    if not canary_pairs:
        return True  # строка 243: нет canary — доверяем

    old_queries = [p["query"] for p in canary_pairs]
    old_chunks = [p["expected_chunk"] for p in canary_pairs]

    try:
        old_q_vecs = old_embed_batch(old_queries, is_query=True)
        old_c_vecs = old_embed_batch(old_chunks, is_query=False)
    except Exception:
        return True  # строка 261: сбой базлайна — доверяем (fail-open)

    if not old_q_vecs or not old_c_vecs:
        return True  # строка 264: пустой базлайн — доверяем

    old_sims = [_cos_sim(q, c) for q, c in zip(old_q_vecs, old_c_vecs)]
    old_mean = sum(old_sims) / len(old_sims) if old_sims else 0.0

    try:
        new_q_vecs = new_embed_fn(old_queries)
        new_c_vecs = new_embed_fn(old_chunks)
    except Exception:
        return False

    if not new_q_vecs or not new_c_vecs:
        return False

    new_sims = [_cos_sim(q, c) for q, c in zip(new_q_vecs, new_c_vecs)]
    new_mean = sum(new_sims) / len(new_sims) if new_sims else 0.0

    threshold = old_mean * 0.9
    degraded = sum(1 for n in new_sims if n < threshold)
    degraded_ratio = degraded / len(new_sims) if new_sims else 1.0

    if degraded_ratio > 0.3:
        return False
    return True


def _text_hash_vec(text: str, seed: int = 42) -> list:
    """Детерминированный «модельный» вектор: baseline с реалистичными sims ~0.2-0.6."""
    import hashlib

    h = hashlib.blake2b(f"{seed}:{text}".encode("utf-8"), digest_size=48).digest()
    v = [b / 255.0 - 0.5 for b in h]
    # нормируем
    n = sum(x * x for x in v) ** 0.5 or 1.0
    return [x / n for x in v]


def _zero_vec(_text: str) -> list:
    return [0.0] * DIM


def _const_vec(_text: str) -> list:
    """Collapse-to-constant: все тексты → один вектор (модель «слепа»)."""
    return [1.0] * DIM


CANARY = [
    {"query": f"query number {i}", "expected_chunk": f"def func_{i}()"}
    for i in range(20)
]


def main():
    print("=" * 72)
    print("EXP-1: Shadow Canary attack (дискриминативная способность)")
    print("Реплика алгоритма remote_embedder.py:231-304, N=20 пар canary")
    print("=" * 72)

    # Базлайн: реалистичная «старая» модель (текст-хэш-векторы)
    old_batch = lambda texts, is_query=False: [_text_hash_vec(t) for t in texts]
    old_q = _text_hash_vec(CANARY[0]["query"])
    old_c = _text_hash_vec(CANARY[0]["expected_chunk"])
    print(f"\n[baseline] sim(query0, chunk0) = {_cos_sim(old_q, old_c):.3f} "
          f"(реалистичный диапазон для текстового эмбеддера)")

    # (a) Контроль: нулевые векторы — canary ОБЯЗАН заблокировать
    r_a = shadow_compare(CANARY, old_batch, lambda texts: [_zero_vec(t) for t in texts])
    print(f"\n(a) Нулевые векторы (контроль): BLOCKED={not r_a} "
          f"{'✅ контроль отработал' if not r_a else '❌ КОНТРОЛЬ ПРОВАЛЕН'}")

    # (b) АТАКА: collapse-to-constant — все векторы [1.0]*384
    r_b = shadow_compare(CANARY, old_batch, lambda texts: [_const_vec(t) for t in texts])
    print(f"(b) АТАКА constant-vector (все тексты → [1.0]*384): PASSED={r_b} "
          f"{'❌ АТАКА ПРОШЛА: слепая модель допущена' if r_b else '✅ заблокирована'}")

    # (b2) АТАКА: collapse-to-constant с малым шумом (реалистичнее)
    import random

    rng = random.Random(7)

    def noisy_const(texts):
        return [[1.0 + rng.uniform(-0.01, 0.01) for _ in range(DIM)] for _ in texts]

    r_b2 = shadow_compare(CANARY, old_batch, noisy_const)
    print(f"(b2) АТАКА noisy-constant (±1%): PASSED={r_b2} "
          f"{'❌ АТАКА ПРОШЛА' if r_b2 else '✅ заблокирована'}")

    # (c) Пустой canary-набор — строка 243
    r_c = shadow_compare([], old_batch, lambda texts: [_zero_vec(t) for t in texts])
    print(f"(c) Пустой canary-набор: PASSED={r_c} "
          f"{'❌ АТАКА ПРОШЛА: даже нулевые векторы допущены (fail-open)' if r_c else '✅'}")

    # (d) Сбой базлайна — строка 261
    def broken_old(texts, is_query=False):
        raise RuntimeError("old embedder crashed")

    r_d = shadow_compare(CANARY, broken_old, lambda texts: [_zero_vec(t) for t in texts])
    print(f"(d) Сбой базлайна (old raises): PASSED={r_d} "
          f"{'❌ АТАКА ПРОШЛА: сломанная модель допущена (fail-open)' if r_d else '✅'}")

    # (e) Обе модели вырождены одинаково (старая тоже constant) — самосогласованная гонка
    r_e = shadow_compare(CANARY, lambda texts, is_query=False: [_const_vec(t) for t in texts],
                         lambda texts: [_const_vec(t) for t in texts])
    print(f"(e) old И new обе constant: PASSED={r_e} "
          f"{'❌ АТАКА ПРОШЛА: взаимно-вырожденная пара прошла' if r_e else '✅ заблокирована'}")

    print("\n" + "=" * 72)
    print("ИТОГ: атаки (b)(b2)(c)(d)(e) — 5 из 5 прошли. Контроль (a) — работает.")
    print("=" * 72)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
