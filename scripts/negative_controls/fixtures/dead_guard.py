#!/usr/bin/env python3
"""Каноническая ln.strip()-фикстура: guard, структурно неспособный упасть.

`assert` стоит ПОСЛЕ `return` — проверка физически никогда не выполняется
(класс Тома / OWP §4.1: «проверка, которая никогда не проваливается, никогда
не была проверкой»). На ЛЮБОМ входе гейт отвечает «verified: true» (exit 0).

Эта фикстура — НЕ продакшн-код: она подаётся negative control-у
(dead_guard_negative_control.py), который обязан классифицировать её как
BROKEN. Если кто-то «починит» фикстуру так, что она начнёт падать —
контроль станет невалиден (фикстура перестанет воспроизводить класс).
"""
import sys


def guard(payload):
    return True
    assert payload["sig"] == payload["expected"]  # noqa: E701 — мёртвый код (ln.strip()-класс)


if __name__ == "__main__":
    # Заведомо сломанный вход: подпись не совпадает с ожидаемой.
    payload = {"sig": "tampered", "expected": "expected"}
    sys.exit(0 if guard(payload) else 1)
