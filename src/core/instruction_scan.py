"""
Instruction Scan — детектор инструкционных паттернов в тексте чанков.

Проблема (AIShellJack arXiv 2509.22040, SoK arXiv 2601.17548): репозиторий —
это attack surface. README/комментарии/issues могут нести вредоносные
инструкции ("ignore previous instructions", "run this command"), которые
агент может принять за команды, а не за данные.

Подход: НЕ фильтрация (SoK: filtering не работает), а МАРКИРОВКА. Сканер
находит паттерны в тексте результата поиска и добавляет metadata-флаг —
агент видит предупреждение и трактует чанк как данные, не как authority.
Сканирование на выдаче (топ-N результатов), не в индексе: дёшево
(микросекунды на 10×1KB), не требует реиндекса, не трогает хранилище.

Важно: флаги АДВИЗОРНЫЕ. Они никогда не блокируют поиск/выдачу — только
информируют (trust_boundary + policy docs/TRUST_BOUNDARY.md).
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List

__all__ = [
    "scan_instruction_risk",
    "has_instruction_risk",
    "INSTRUCTION_PATTERNS",
]

logger = logging.getLogger("instruction_scan")

# Категория → список regex-паттернов (lower-case текст на входе).
# Паттерны консервативные: ловят явные императивы и переопределения ролей,
# избегая ложных срабатываний на обычном коде.
INSTRUCTION_PATTERNS: Dict[str, List[str]] = {
    "role_hijack": [
        r"ignore (all )?(previous|prior|earlier) (instructions|commands|prompts|rules)",
        r"disregard (all )?(previous|prior|earlier) (instructions|commands|rules)",
        r"you are (now )?(an? )?(ai|assistant|agent|coder|expert)[^\\n]{0,40}(without|that must)",
        r"act as (if you were|an? )?(an? )?(ai|assistant|agent|shell)",
        r"system prompt",
    ],
    "imperative": [
        r"^run (the )?(following )?(command|script|code)",
        r"^execute (the |this )?(following |script |command)",
        r"^do not (tell|mention|reveal|say|inform|report)",
        r"^never (tell|mention|reveal|say|inform)",
        r"^delete (the )?(file|files|directory|repo)",
        r"^remove (the )?(file|files)",
        r"^send (the )?(content|file|data|token)",
        r"^exfiltrate",
    ],
    "shell": [
        r"\brm -rf\b",
        r"\bcurl (http|ftp)",
        r"\bwget (http|ftp)",
        r"\bsudo \\w+",
        r"\bchmod 777\b",
        r"\bgit clone (http|ftp|ssh)",
        r"\\b(powershell|cmd\\.exe|bash -c)\\b",
    ],
    "secrets": [
        r"api[_-]?key\\s*=\\s*['\\\"][A-Za-z0-9]{16,}",
        r"password\\s*=\\s*['\\\"][^'\\\"]{8,}",
        r"token\\s*=\\s*['\\\"][A-Za-z0-9._-]{16,}",
        r"secret\\s*=\\s*['\\\"][A-Za-z0-9]{16,}",
    ],
}

# Компилируем один раз при импорте.
_COMPILED: Dict[str, List[re.Pattern]] = {
    cat: [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in patterns]
    for cat, patterns in INSTRUCTION_PATTERNS.items()
}

_MAX_FLAGS = 4  # предохранитель: не раздуваем metadata


def scan_instruction_risk(text: str) -> List[str]:
    """Возвращает список сработавших категорий (пусто — риск не найден).

    Args:
        text: текст чанка (сырой, до обрезки)

    Returns:
        Список категорий: ["role_hijack"], ["imperative", "shell"], ...
    """
    if not text:
        return []
    lowered = text[:20000]  # защита от гигантских чанков
    flags: List[str] = []
    for cat, patterns in _COMPILED.items():
        for pat in patterns:
            if pat.search(lowered):
                flags.append(cat)
                break
        if len(flags) >= _MAX_FLAGS:
            break
    return flags


def has_instruction_risk(text: str) -> bool:
    """True, если в тексте найден хотя бы один инструкционный паттерн."""
    return bool(scan_instruction_risk(text))
