"""redact.py — вырезает credential-подобные строки НА ДОСТАВКЕ (перед инъекцией в контекст агента).

Зачем: наш «secret gate» — это commit-gate; канал доставки (хук → `python -m src.cli` → текст
заметки в контексте модели) через коммит НЕ проходит. Заметка про auth-сбой может нести ключ как
evidence — и он утечёт в контекст каждого агента, на котором заметка сработает. См. E8/Exp 20.

Идея и принцип (prefix-anchored, не entropy) — по design из Tom Jones, crystal-memory,
`scripts/redact.py` (Apache-2.0). Реализация наша; код не вендорился.

⛔ ЭТО НЕ ГРАНИЦА БЕЗОПАСНОСТИ. Ловит только ИЗВЕСТНЫЕ ФОРМЫ по структурному префиксу. Новый формат,
секрет разбитый по строкам или записанный словами — проходит. Снижает цену случайности, но не
делает канал безопасным для секретов. Якоря на префикс, а не на энтропию/слово «key», чтобы не
резать легитимные hex-дайджесты, хеши коммитов и пути.

Чистая stdlib, без I/O. `redact(text)` не бросает на странном входе.
"""
from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

__all__ = ["redact", "redacted_count", "PLACEHOLDER"]

PLACEHOLDER = "[REDACTED:{kind}]"

# (kind, compiled pattern). Префикс-анкоренные — см. docstring.
PATTERNS = (
    ("aws-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("private-key", re.compile(
        r"-----BEGIN[ A-Z]*PRIVATE KEY-----.*?-----END[ A-Z]*PRIVATE KEY-----", re.S)),
    ("anthropic", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    ("openai", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{32,}")),
    ("github-token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b")),
    ("github-pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{50,}\b")),
    ("slack", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}")),
    ("google-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("stripe", re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    ("jwt", re.compile(
        r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
    # URL со встроенными кредами. Намеренно НЕ матчит голый user@host.
    ("url-cred", re.compile(r"\b(?P<scheme>[a-z][a-z0-9+.\-]*)://[^\s/:@]+:[^\s/@]+@")),
    # `Authorization: Bearer <token>` — только значение, и только если достаточно длинное.
    ("bearer", re.compile(r"(?i)(?P<lead>\bbearer\s+)(?P<tok>[A-Za-z0-9_\-\.=]{24,})")),
)

# ⛔ Присваивание ≠ секрет. `KEY=` чаще shell-пример/имя переменной, чем живой кред.
# Режем присваивание ТОЛЬКО если значение тоже похоже на кред: длинное и не плейсхолдер/путь/число.
_ASSIGN = re.compile(
    r"(?i)(?P<lead>\b(?:api[_\-]?key|secret|token|passwd|password|access[_\-]?key)\b\s*[:=]\s*)"
    r"(?P<q>[\"']?)(?P<val>[A-Za-z0-9_\-\.+/=]{20,})(?P=q)")
_PLACEHOLDERISH = re.compile(
    r"(?i)^(?:x{3,}|\.{3,}|<.*>|\$\{?[a-z_]+\}?|your[_\-].*|example.*|changeme|redacted|"
    r"[a-z_]*placeholder[a-z_]*|none|null|true|false)$")


def _looks_like_a_value(val: str) -> bool:
    """Кред, а не путь/число/ссылка на env/плейсхолдер."""
    if _PLACEHOLDERISH.match(val):
        return False
    if val.startswith(("/", "./", "~", "$")) or ("/" in val and val.count("/") > 1):
        return False
    if re.fullmatch(r"[0-9.]+", val):
        return False
    return bool(re.search(r"[A-Za-z]", val) and re.search(r"[0-9_\-.+/=]", val))


def redact(text: str, counter: Optional[Dict[str, int]] = None) -> str:
    """Возвращает `text` с вырезанными credential-подобными подстроками. Не бросает."""
    if not text or not isinstance(text, str):
        return text
    out = text
    for kind, pattern in PATTERNS:
        def _sub(m, kind=kind):
            if counter is not None:
                counter[kind] = counter.get(kind, 0) + 1
            if kind == "bearer":
                return m.group("lead") + PLACEHOLDER.format(kind=kind)
            if kind == "url-cred":
                return f"{m.group('scheme')}://" + PLACEHOLDER.format(kind=kind) + "@"
            return PLACEHOLDER.format(kind=kind)
        out = pattern.sub(_sub, out)

    def _assign(m):
        if not _looks_like_a_value(m.group("val")):
            return m.group(0)
        if counter is not None:
            counter["assignment"] = counter.get("assignment", 0) + 1
        return m.group("lead") + m.group("q") + PLACEHOLDER.format(kind="assignment") + m.group("q")
    return _ASSIGN.sub(_assign, out)


def redacted_count(text: str) -> Tuple[str, Dict[str, int]]:
    """(redacted_text, {kind: n}) — чтобы вызывающий мог СКАЗАТЬ, что отредактировал."""
    counter: Dict[str, int] = {}
    return redact(text, counter), counter
