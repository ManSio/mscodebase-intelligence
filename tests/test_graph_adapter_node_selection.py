"""Регрессии D1-D3 (2026-08-08): выбор узла в build_call_graph/get_callers.

Семья дефектов символьных инструментов (get_symbol_info/impact_analysis):
- D1: определение src/ затенялось experiments/ (одноразовые скрипты).
- D2: методы (qualified name "Class.method") не находились по голому имени.
- D3: extern-placeholder (пустой file_path) вытеснял реальное определение.

Корень: build_call_graph/get_callers брали find_nodes(name_pattern)[0] без
ранжирования; фикс — _find_nodes_flexible (union exact+suffix) + _pick_best_node.
"""
from src.core.graph import PropertyGraph
from src.core.search.graph_adapter import SymbolIndexAdapter


def _adapter(tmp_path):
    pg = PropertyGraph(str(tmp_path / "test.db"))
    return SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)


def test_d1_src_definition_beats_experiments_shadow(tmp_path):
    """build_call_graph('build_call_graph'): src/ метод, не тень experiments/."""
    ad = _adapter(tmp_path)
    ad.add_definitions("D:/Project/X/experiments/run_experiment_pagerank.py", [
        {"name": "build_call_graph", "line": 40, "kind": "function_definition"},
    ])
    ad.add_definitions("D:/Project/X/scripts/run_experiment_pagerank.py", [
        {"name": "build_call_graph", "line": 40, "kind": "function_definition"},
    ])
    ad.add_definitions("D:/Project/X/src/core/indexing/symbol_index.py", [
        {"name": "SymbolIndex.build_call_graph", "line": 480, "kind": "function_definition"},
    ])

    g = ad.build_call_graph("build_call_graph")
    defs = g["definition"]
    assert defs, "определение должно быть найдено"
    assert "/src/" in defs[0]["file"], f"src/ определение должно выиграть: {defs[0]}"
    assert defs[0]["line"] == 480, f"должна быть строка src-определения: {defs[0]}"


def test_d2_method_resolved_by_bare_name(tmp_path):
    """Метод Searcher._expand_graph_context находится по голому имени (D2)."""
    ad = _adapter(tmp_path)
    ad.add_definitions("D:/Project/X/src/core/search/engine.py", [
        {"name": "Searcher._expand_graph_context", "line": 1066, "kind": "function_definition"},
    ])

    g = ad.build_call_graph("_expand_graph_context")
    assert g["definition"], "метод должен резолвиться по голому имени (D2)"
    assert g["definition"][0]["file"].endswith("engine.py")
    assert g["definition"][0]["line"] == 1066


def test_d3_placeholder_does_not_shadow_real_definition(tmp_path):
    """extern-placeholder (пустой file_path) не вытесняет реальное определение (D3)."""
    ad = _adapter(tmp_path)
    # Сначала reference — создаёт placeholder с пустым file_path
    ad.add_references("D:/Project/X/src/other.py", [
        {"caller": "main", "callee": "_InterProcessLock", "line": 5},
    ])
    # Потом реальное определение
    ad.add_definitions("D:/Project/X/src/providers/reranker/llama_runner.py", [
        {"name": "_InterProcessLock", "line": 164, "kind": "class_definition"},
    ])

    g = ad.build_call_graph("_InterProcessLock")
    defs = g["definition"]
    assert defs, "определение должно быть найдено"
    assert defs[0]["file"], "file_path не должен быть пустым (D3)"
    assert defs[0]["file"].endswith("llama_runner.py")
    assert defs[0]["line"] == 164


def test_callers_merged_across_placeholder_and_real(tmp_path):
    """CALLS-рёбра на extern-placeholder не теряются при выборе real-узла."""
    ad = _adapter(tmp_path)
    # caller-узел существует (иначе add_edge дропается), reference до определения
    # → ребро/placeholder на extern
    ad.add_definitions("D:/Project/X/src/consumer.py", [
        {"name": "use_symbol", "line": 8, "kind": "function_definition"},
    ])
    ad.add_references("D:/Project/X/src/consumer.py", [
        {"caller": "use_symbol", "callee": "some_private_fn", "line": 10},
    ])
    ad.add_definitions("D:/Project/X/src/core/impl.py", [
        {"name": "some_private_fn", "line": 20, "kind": "function_definition"},
    ])

    g = ad.build_call_graph("some_private_fn", depth=1)
    assert g["definition"], "определение должно быть найдено"
    assert g["definition"][0]["file"].endswith("impl.py")
    # callers могут прийти из extern-placeholder — union-старт их сохраняет
    caller_files = {c["file"] for c in g["callers"]}
    assert caller_files, "callers не должны теряться из-за выбора real-узла"
    assert any(f and f.endswith("consumer.py") for f in caller_files), caller_files


def test_qualified_symbol_includes_bare_node_callers(tmp_path):
    ad = _adapter(tmp_path)
    ad.add_definitions("D:/Project/X/src/pipeline.py", [
        {"name": "Pipeline.process_articles", "line": 50, "kind": "method_definition"},
    ])
    ad.add_references("D:/Project/X/src/pipeline.py", [
        {"caller": "Pipeline.process_articles", "callee": "list_articles", "line": 55},
    ])
    ad.add_definitions("D:/Project/X/src/clients/devto.py", [
        {"name": "DevToClient.list_articles", "line": 30, "kind": "method_definition"},
    ])

    nodes = ad._find_nodes_flexible("DevToClient.list_articles", limit=20)
    has_bare = any(n.name == "list_articles" for n in nodes)
    assert has_bare, f"bare 'list_articles' node not found in: {[(n.name, n.qualified_name) for n in nodes]}"

    g = ad.build_call_graph("DevToClient.list_articles")
    caller_names = [c["symbol"] for c in g["callers"]]
    assert any("process_articles" in c for c in caller_names), (
        f"expected Pipeline.process_articles in callers, got: {g['callers']}"
    )
