"""
Grammar probe v2: enumerate node types from compiled tree-sitter grammars.

Зона исследователя (полигон). Вместо node-types.json (не поставляется в колёсах)
перечисляем ВСЕ имена узлов прямо из скомпилированного Language объекта
через Language.node_kind_for_id — это истина для установленной версии грамматики.

Запуск:
    ./venv/Scripts/python.exe experiments/universal-engine/study-detectors/grammar_probe.py

Результат — на stdout: по каждому языку кандидаты имён узлов по категориям
(imports / calls / conditions / assignments). Сверка с parser.py — вручную,
результат — в docs/research/universal-engine-study/05-grammar-node-kinds.md.
"""

import importlib.metadata as m
import re
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

CATEGORY_PATTERNS = {
    "imports": re.compile(
        r"(import|require|include|use|export|using|source_statement|load)"
    ),
    "calls": re.compile(
        r"(call|invocation|invoke|new_expression|send|command|apply|method_call|function_call)"
    ),
    "conditions": re.compile(
        r"(^if|_if|if_statement|if_expression|if_clause|else|for_|while|with_|try|catch|except|match|case|switch|loop|ternary|conditional|do_statement|repeat)"
    ),
    "assignments": re.compile(
        r"(assign|declarator|var_spec|val_definition|var_definition|let_declaration|property_declaration|init_declarator|send_statement|field_declaration|variable|binding|typed_parameter)"
    ),
}

SKIP_NAMES = {"tree-sitter", "tree-sitter-language-pack"}

# (модуль, аргументы имени языка) — как в parser.py
PACKAGES = [
    ("tree-sitter-python", "tree_sitter_python", [("python", "language")]),
    ("tree-sitter-rust", "tree_sitter_rust", [("rust", "language")]),
    ("tree-sitter-typescript", "tree_sitter_typescript", [("typescript", "language_typescript"), ("tsx", "language_tsx")]),
    ("tree-sitter-javascript", "tree_sitter_javascript", [("js", "language"), ("jsx", "language")]),
    ("tree-sitter-go", "tree_sitter_go", [("go", "language")]),
    ("tree-sitter-java", "tree_sitter_java", [("java", "language")]),
    ("tree-sitter-c-sharp", "tree_sitter_c_sharp", [("cs", "language")]),
    ("tree-sitter-ruby", "tree_sitter_ruby", [("rb", "language")]),
    ("tree-sitter-php", "tree_sitter_php", [("php", "language_php")]),
    ("tree-sitter-kotlin", "tree_sitter_kotlin", [("kt", "language")]),
    ("tree-sitter-swift", "tree_sitter_swift", [("swift", "language")]),
    ("tree-sitter-c", "tree_sitter_c", [("c", "language")]),
    ("tree-sitter-cpp", "tree_sitter_cpp", [("cpp", "language"), ("cxx", "language"), ("hpp", "language")]),
    ("tree-sitter-scala", "tree_sitter_scala", [("scala", "language")]),
    ("tree-sitter-dart", "tree_sitter_dart", [("dart", "language")]),
    ("tree-sitter-bash", "tree_sitter_bash", [("sh", "language"), ("bash", "language")]),
    ("tree-sitter-sql", "tree_sitter_sql", [("sql", "language")]),
    ("tree-sitter-yaml", "tree_sitter_yaml", [("yaml", "language")]),
    ("tree-sitter-toml", "tree_sitter_toml", [("toml", "language")]),
    ("tree-sitter-html", "tree_sitter_html", [("html", "language")]),
    ("tree-sitter-css", "tree_sitter_css", [("css", "language")]),
    ("tree-sitter-hcl", "tree_sitter_hcl", [("hcl", "language")]),
]


def get_language(mod, getter_name):
    """Возвращает Language объект: LANGUAGE-атрибут (новый API) или обёртка PyCapsule."""
    from tree_sitter import Language as TS_Language

    candidate = getattr(mod, "LANGUAGE", None)
    if candidate is not None and isinstance(candidate, TS_Language):
        return candidate
    if not getter_name:
        return None
    fn = getattr(mod, getter_name, None)
    if fn is None:
        return None
    try:
        val = fn()
    except (TypeError, ValueError):
        return None
    if isinstance(val, TS_Language):
        return val
    try:
        return TS_Language(val)  # PyCapsule
    except (TypeError, ValueError):
        return None


def node_kinds(lang):
    """Все (kind, named) из Language через перечисление id.

    Идёт от 0 до 2048; пустые id в середине диапазона пропускаем,
    останавливаемся после 16 подряд пустых (диапазон id плотный по спеке
    tree-sitter, но некоторые грамматики оставляют дырки).
    """
    kinds = []
    empty_run = 0
    for i in range(2048):
        try:
            kind = lang.node_kind_for_id(i)
        except Exception:  # noqa: BLE001 — probe
            break
        if not kind:
            empty_run += 1
            if empty_run > 16:
                break
            continue
        empty_run = 0
        try:
            named = lang.node_kind_is_named(i)
        except Exception:  # noqa: BLE001 — probe
            named = True
        kinds.append((kind, named))
    return kinds


def main():
    print("# node kinds per grammar (enumerated from compiled Language)\n")
    for dist_name, mod_name, variants in PACKAGES:
        try:
            dist = m.distribution(dist_name)
            _ = dist  # убеждаемся, что пакет установлен
            mod = __import__(mod_name)
        except Exception as exc:  # noqa: BLE001 — probe
            print(f"## {dist_name}: NOT INSTALLED ({exc})")
            continue
        all_named = set()
        all_any = set()
        lang_src = []
        for label, getter in variants:
            lang = get_language(mod, getter)
            if lang is None:
                continue
            kinds = node_kinds(lang)
            named = {k for k, is_named in kinds if is_named}
            any_k = {k for k, _ in kinds}
            all_named |= named
            all_any |= any_k
            lang_src.append(label)
        if not all_any:
            print(f"## {dist_name}: LANGUAGE OBJECT FAIL")
            continue
        print(f"## {dist_name} [{','.join(lang_src)}] (named: {len(all_named)}, total: {len(all_any)})")
        for cat, pat in CATEGORY_PATTERNS.items():
            hits = sorted({t for t in all_named if pat.search(t)})
            hits_any = sorted({t for t in all_any if pat.search(t) and t not in all_named})
            shown = ", ".join(hits[:16]) + (" …" if len(hits) > 16 else "")
            if hits_any:
                shown += f"   [anon: {', '.join(hits_any[:6])}]"
            print(f"  {cat} ({len(hits)}): {shown}")
        print()
    print("DONE")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback

        traceback.print_exc()
        sys.exit(1)