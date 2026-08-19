"""Trust-гейт UX (Фаза 4, план §5.2) — промпт издателя и resolver.

trust_resolver(manifest, sha256, drift) -> bool — единственная точка принятия
решения в load-гейте. Здесь — форматирование читаемого промпта для оператора и
фабрики resolver'ов: auto-approve (тесты/доверенные среды) и operator-решатель
(по умолчанию deny — неинтерактивный сервер не должен сам хеллй-грузить плагины).
"""
from __future__ import annotations

from typing import Callable, Optional


def trust_prompt(manifest, sha256: str) -> str:
    """Читаемое описание плагина для промпта одобрения (name/version/publisher/sha)."""
    return "\n".join([
        "A plugin requests approval to load:",
        f"  id:        {manifest.id}",
        f"  name:      {manifest.name}",
        f"  version:   {manifest.version}",
        f"  publisher: {manifest.source or 'unknown'}",
        f"  sha256:    {sha256}",
        f"  platform:  {','.join(manifest.platform)}",
        f"  tools:     {','.join(manifest.tools)}",
        f"  requires_engine: {manifest.requires_engine_version}",
    ])


def make_trust_resolver(
    decide: Optional[Callable[[str], bool]] = None,
    *,
    auto_approve: bool = False,
    sink: Callable[[str], None] = None,
) -> Callable:
    """Фабрика trust_resolver для load-гейта.

    decide(prompt) -> bool: операторское решение (может писать в UI/лог).
    auto_approve=True: доверять без промпта (ТОЛЬКО тесты/изолированная среда).
    sink(prompt): куда писать промпт (по умолч. print); None — скрыть.
    По умолчанию (decide=None, auto_approve=False) — fail-closed deny.
    """
    if auto_approve:
        return lambda manifest, sha, drift: True

    def _resolver(manifest, sha, drift):
        if decide is None and sink is None:
            return False  # нечего показывать/решать — мгновенный fail-closed deny
        prompt = trust_prompt(manifest, sha)
        if drift:
            prompt += "\n  [DRIFT] содержимое изменилось с прошлого доверия — переодобрить?"
        if sink is not None:
            sink(prompt)
        if decide is not None:
            return bool(decide(prompt))
        return False  # безусловный deny — сервер не грузит без явного решения

    return _resolver


# Явный fail-closed resolver (эквивалент resolver=None, но именованный).
DENY_ALL = lambda manifest, sha, drift: False  # noqa: E731
