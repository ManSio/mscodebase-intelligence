"""EXP-3: Воспроизведение бага `ln.strip()` (Tom Jones, fintech) — 8 форм вызова.

Оригинал: gateway-верификатор фильтровал assert-строки вызывающей стороны по
`ln.strip()` (match), но ЭМИТИРОВАЛ сырую `ln` (исходный отступ). Извлечённые
строки дописывались в конец ответа модели:

    def add_two(a, b):
        return a + b + 1          # неверный ответ модели
        assert add_two(1,2) == 3  # assert (4-space из кода вызывающего)
                                 # попал ВНУТРЬ функции ПОСЛЕ return — мёртвый код

Valid Python, never executed, exit 0, gateway reports verified.
5 ложных проходов из 8 форм у fintech. Здесь — 8 СВОИХ форм (набор другой),
считаем честно; цель — доказать класс бага, а не повторить 5/8.

Модель верификатора: exec(module); exit 0 (не упало) = verified:true.
"""
import sys
import traceback

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")


def broken_extract_asserts(source: str):
    """Реплика бага: match по ln.strip(), emit сырой ln."""
    out = []
    for ln in source.splitlines():
        if "assert" in ln.strip():
            out.append(ln)  # ← БАГ: исходный отступ сохранён
    return out


def fixed_extract_asserts(source: str):
    """Правильно: emit ln.strip() — колонка 0, assert гарантированно top-level."""
    out = []
    for ln in source.splitlines():
        if "assert" in ln.strip():
            out.append(ln.strip())
    return out


def run_verifier(extract_fn, caller_test_source: str, answer_code: str) -> bool:
    """exit 0 = verified (True). Аналог финтех-gateway: assert'ы дописываются."""
    asserts = extract_fn(caller_test_source)
    module = answer_code + "\n" + "\n".join(asserts)
    try:
        exec(compile(module, "<verifier>", "exec"), {})
        return True  # скомпилировалось и импортировалось без падения → verified
    except AssertionError:
        return False  # assert реально выполнился и поймал неверный ответ
    except Exception:
        return False  # IndentationError и прочее — верификатор «упал»


# Неверный ответ модели: add_two(1,2) должен быть 3, модель возвращает 4
WRONG_ANSWER = "def add_two(a, b):\n    return a + b + 1"

# 8 форм вызова: где стоял assert в коде вызывающей стороны
CALLER_SHAPES = [
    ("1. assert top-level (col 0)",                  "assert add_two(1, 2) == 3"),
    ("2. assert 4-space в def (после return)",       "def t():\n    return 1\n    assert add_two(1, 2) == 3"),
    ("3. assert 4-space в def (до return)",          "def t():\n    assert add_two(1, 2) == 3\n    return 1"),
    ("4. assert 8-space в if (после return)",        "def t():\n    return 1\n    if True:\n        assert add_two(1, 2) == 3"),
    ("5. assert 8-space в if (до return)",           "def t():\n    if True:\n        assert add_two(1, 2) == 3\n    return 1"),
    ("6. assert 8-space в try",                      "def t():\n    return 1\n    try:\n        assert add_two(1, 2) == 3\n    except Exception:\n        pass"),
    ("7. assert 12-space (двойная вложенность)",     "def t():\n    if True:\n        if True:\n            assert add_two(1, 2) == 3"),
    ("8. assert 4-space последний стейтмент",        "def t():\n    x = 1\n    assert add_two(1, 2) == 3"),
]


def main():
    print("=" * 72)
    print("EXP-3: ln.strip() bug — 8 форм вызова, неверный ответ модели")
    print("add_two(1,2) должно быть 3; модель возвращает 4 → assert ОБЯЗАН упасть")
    print("=" * 72)

    fp_broken = 0
    fp_fixed = 0
    for label, shape in CALLER_SHAPES:
        rb = run_verifier(broken_extract_asserts, shape, WRONG_ANSWER)
        rf = run_verifier(fixed_extract_asserts, shape, WRONG_ANSWER)
        mb = "❌ FALSE PASS" if rb else "✅ поймал"
        mf = "❌ FALSE PASS" if rf else "✅ поймал"
        print(f"{label}")
        print(f"   broken (emit ln):    verified={rb} {mb}")
        print(f"   fixed  (emit strip): verified={rf} {mf}")
        if rb:
            fp_broken += 1
        if rf:
            fp_fixed += 1

    print("=" * 72)
    print(f"Сломанный экстрактор: {fp_broken}/{len(CALLER_SHAPES)} ложных проходов")
    print(f"Правильный экстрактор: {fp_fixed}/{len(CALLER_SHAPES)} ложных проходов")
    print("=" * 72)

    print("\nПример модуля, собранного СЛОМАННЫМ экстрактором (форма 2):")
    asserts = broken_extract_asserts(CALLER_SHAPES[1][1])
    print(WRONG_ANSWER + "\n" + "\n".join(asserts))
    print("→ assert на 4-space попал ВНУТРЬ add_two ПОСЛЕ return: мёртвый код.")
    print("  Valid Python, exit 0, verified:true — сигнатура проверки валидна, ответ неверен.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
