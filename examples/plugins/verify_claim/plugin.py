"""PoC-плагин verify_claim (Фаза 4, план §5).

Детерминированная VOR-проверка утверждения против необязательного списка якорей
(без LLM) — демонстрирует механизм плагина: manifest + entrypoint c TOOLS +
load-гейт + self-check. Полноценный LLM-VOR (`verify_on_read`) — расширение этого
инкремента.

Контракт in-process v1: модуль обязан экспортировать TOOLS = list[dict]
{"name", "description", "handler", ...}.
"""
from __future__ import annotations

from typing import List, Optional


def verify_claim(claim: str, anchors: Optional[List[str]] = None) -> str:
    """VOR-проверка (PoC): VERIFIED если claim найден в якорях, иначе UNKNOWN.

    args:
        claim: строка утверждения (что проверяем).
        anchors: необязательный список строк, по которым ищем.
    returns:
        VERIFIED / REFUTED / UNKNOWN (machine-verdict, три-state §11).
    """
    claim_s = (claim or "").strip().lower()
    if not claim_s:
        return "UNKNOWN"
    if not anchors:
        return "UNKNOWN"  # нет корпуса для проверки — честный INCONCLUSIVE
    hits = [a for a in anchors if claim_s in (a or "").lower()]
    if hits:
        return "VERIFIED"
    return "REFUTED"


TOOLS: List[dict] = [
    {
        "name": "verify_claim",
        "description": "VOR: детерминированная проверка утверждения против списка "
                       "якорей (PoC). Вердикты: VERIFIED / REFUTED / UNKNOWN.",
        "handler": verify_claim,
    },
]
