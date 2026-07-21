"""Token Savings utilities for search results.

CRG pattern: measure token economy when filtering search results.
"""

from typing import List


def count_tokens(text: str) -> int:
    """Оценка количества токенов (простая эвристика: 1 токен ≈ 4 символа).

    CRG использует tiktoken, но для простоты используем длину текста.
    Точность не критична — важна разница "до" vs "после" фильтрации.
    """
    return max(1, len(text) // 4)


def calculate_token_savings(results: List[dict], total_available: int = 0) -> dict:
    """Вычисляет экономию токенов при поиске.

    Args:
        results: Результаты поиска (уже отфильтрованы)
        total_available: Общее количество токенов в индексе (для сравнения)

    Returns:
        {tokens_used, tokens_saved, savings_percent}
    """
    tokens_used = sum(
        count_tokens(r.get("text", "")) + count_tokens(r.get("text_full", ""))
        for r in results
    )
    if total_available > 0:
        tokens_saved = total_available - tokens_used
        savings_percent = round(100 * tokens_saved / total_available, 1) if total_available > 0 else 0
    else:
        # Оценка: если брали top-5 из 1000 чанков со средним 200 токенов
        tokens_saved = tokens_used * 995  # примерно
        savings_percent = 99.5

    return {
        "tokens_used": tokens_used,
        "tokens_saved": tokens_saved,
        "savings_percent": savings_percent,
    }
