"""Holdout-калибровка порога реранкера (adopt/reranker-threshold-and-pool).

Протокол (обязателен; нарушение = перебор на оценочной выборке):

1. HOLDOUT-СПЛИТ: калибровать ТОЛЬКО на запросах, дизъюнктных с 16 frozen
   eval-правилами ``experiments/token_reduction_v3_lancedb/frozen/rules.jsonl``
   (sha256 ``31f1b0c9…``). Рекомендуемый размер: >=10 holdout-запросов со
   своими positive-контролями (целевые файлы вне eval-16); eval-16 при
   калибровке НЕ СМОТРЕТЬ (freeze-before-look, §17).
2. ``calibrate_threshold`` (F1-максимум) на holdout-скорах -> кандидат порога.
3. Проверка кандидата на eval-16 БЕЗ подстройки: сообщить hits до/после;
   любой добор по eval = новый overfit-цикл, запрещён.
4. Дефолт ``MIN_RERANK_SCORE=0.3`` в ``multi_provider.py`` НЕ МЕНЯТЬ без
   holdout-замера из пп.1-3 (прецедент отказа: sweep 0.3->0.05/0.02 дал
   7-8 hits на тех же правилах, которыми мерялся результат —
   EXPERIMENTS_LOG 2026-09-27).

Анти-перебор закодирован: ``source`` с eval-маркером бросает ValueError
(тест ``test_calibration_refuses_eval_source``).
"""

from __future__ import annotations

from typing import Sequence

__all__ = ["calibrate_threshold", "EVAL_SOURCE_MARKERS"]

# Маркеры eval-источников: калибровка на них = подгонка под метрику.
EVAL_SOURCE_MARKERS = frozenset(
    {
        "eval",
        "evaluation",
        "test",
        "frozen",
        "frozen-eval",
        "token_reduction_v3",
        "token_reduction_v3_lancedb",
        "v3",
    }
)


def _is_eval_source(source: str) -> bool:
    src = (source or "").strip().lower()
    return src in EVAL_SOURCE_MARKERS


def calibrate_threshold(
    scores: Sequence[float],
    labels: Sequence[bool],
    *,
    source: str,
    min_recall: float = 0.0,
) -> float:
    """Подбирает порог ``score >= t`` максимумом F1 на HOLDOUT-разметке.

    Args:
        scores: Скоре реранкера (шкала [0,1], после сигмоиды).
        labels: Релевантность (True = целевой чанк holdout-запроса).
        source: Происхождение разметки (напр. ``"holdout-2026-10-03"``).
            Eval-маркеры (``"eval"``, ``"frozen"``, ``"token_reduction_v3"``,
            …) запрещены — ValueError. Правило необратимо: кто калибрует
            на eval, тот подгоняет метрику.
        min_recall: Минимальный допустимый recall (кандидаты ниже отсекаются;
            0.0 = чистый F1-максимум).

    Returns:
        Порог-кандидат. Ничья по F1 — в пользу БОЛЕЕ ВЫСОКОГО порога
        (фильтр должен резать мусор, а не пропускать всё).

    Raises:
        ValueError: ``source`` — eval-источник, пустая выборка, длины
            расходятся, нет ни одного positive.
    """
    if _is_eval_source(source):
        raise ValueError(
            f"Калибровка порога на eval-источнике {source!r} запрещена: "
            "это подгонка под метрику (см. EXPERIMENTS_LOG 2026-09-27, "
            "sweep 0.3->0.05/0.02). Используйте holdout-сплит, дизъюнктный "
            "с frozen eval-правилами."
        )
    scores = [float(s) for s in scores]
    labels = [bool(lb) for lb in labels]
    if not scores or len(scores) != len(labels):
        raise ValueError("scores/labels пусты или длины расходятся")
    n_pos = sum(labels)
    if n_pos == 0:
        raise ValueError("нет ни одного positive — F1 неопределим")

    best_t, best_f1 = max(scores) + 1e-9, -1.0  # sentinel: пустая выдача
    for t in sorted(set(scores)):
        kept = [lb for s, lb in zip(scores, labels) if s >= t]
        tp = sum(kept)
        if tp == 0:
            continue
        precision = tp / len(kept)
        recall = tp / n_pos
        if recall < min_recall:
            continue
        f1 = 2 * precision * recall / (precision + recall)
        # Строго больше — либо равный F1 при БОЛЕЕ ВЫСОКОМ пороге
        # (кандидаты идут по возрастанию, >= перезаписывает ничью).
        if f1 >= best_f1:
            best_f1, best_t = f1, t
    if best_f1 < 0.0:
        raise ValueError("ни один порог не даёт tp>0 при min_recall")
    return best_t
