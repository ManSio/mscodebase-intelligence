"""Детекция сообществ (Leiden) на PropertyGraph — ОПЦИОНАЛЬНЫЙ модуль.

⚠️ Лицензионное примечание: leidenalg (GPL-3.0) и igraph (GPL-2.0) —
copyleft-зависимости, НЕ совместимые с MIT-дистрибуцией как обязательные.
Они вынесены в optional extra:

    pip install mscodebase-intelligence[community]

Без них detect_communities() возвращает статус not_installed с инструкцией
(MIT-ядро при этом не затронуто).

Рёбра: по умолчанию только семантические (CALLS/IMPORTS/DECORATES/OVERRIDES/
DATA_FLOWS/ASSIGNED_FROM). CO_CHANGES_WITH не смешивается с семантикой —
см. audit.md «Change Coupling может засорить граф».
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("mscodebase.community_detection")

# Семантические рёбра по умолчанию (CO_CHANGES_WITH — отдельно, не смешивать)
DEFAULT_EDGE_TYPES = (
    "CALLS",
    "ASYNC_CALLS",
    "IMPORTS",
    "DECORATES",
    "OVERRIDES",
    "DATA_FLOWS",
    "ASSIGNED_FROM",
)

# Защита от OOM (урок P1-1 shortest_path): большие графы режутся с явным
# статусом too_large, а не падением.
_MAX_NODES = 20_000
_MAX_EDGES = 200_000


def detect_communities(
    graph,
    edge_types: Optional[Sequence[str]] = None,
    max_nodes: int = _MAX_NODES,
    max_edges: int = _MAX_EDGES,
    resolution: float = 1.0,
    seed: int = 42,
    top_communities: int = 20,
) -> Dict[str, Any]:
    """Leiden-детекция сообществ на PropertyGraph.

    Args:
        graph: PropertyGraph (src/core/graph.py, SQLite-бэкенд).
        edge_types: типы рёбер для построения adjacency. По умолчанию —
            семантические (DEFAULT_EDGE_TYPES).
        max_nodes/max_edges: защитные лимиты (OOM-guard).
        resolution: параметр плотности CPM (больше = более мелкие сообщества).
        seed: детерминированность запуска.
        top_communities: сколько крупнейших сообществ вернуть.

    Returns:
        {"status": "ok"|"not_installed"|"too_large", ...}
    """
    try:
        import igraph as ig
        import leidenalg as la
    except ImportError:
        return {
            "status": "not_installed",
            "message": (
                "Leiden требует copyleft-зависимости (GPL-3.0/GPL-2.0). "
                "Установите: pip install mscodebase-intelligence[community]"
            ),
        }

    names, files, pairs = _load_adjacency(
        graph, edge_types or list(DEFAULT_EDGE_TYPES), max_nodes, max_edges
    )
    if pairs.get("too_large"):
        return {
            "status": "too_large",
            "message": f"Граф превышает защитный лимит ({pairs['reason']}): "
            f"используйте max_nodes/max_edges меньше",
            "limit": pairs["reason"],
        }
    if len(names) < 2 or not pairs["pairs"]:
        return {"status": "ok", "communities": 0, "communities_list": []}

    g = ig.Graph(
        n=len(names),
        edges=[(s, t) for s, t, _w in pairs["pairs"]],
        edge_attrs={"weight": [w for _s, _t, w in pairs["pairs"]]},
    )
    g.vs["name"] = names
    g.vs["file"] = files

    partition = la.find_partition(
        g,
        la.CPMVertexPartition,
        weights="weight",
        resolution_parameter=resolution,
        seed=seed,
    )
    membership = list(partition.membership)
    return _format_result(g, membership, top_communities)


def _load_adjacency(
    graph,
    edge_types: Sequence[str],
    max_nodes: int,
    max_edges: int,
) -> Tuple[List[str], List[str], Dict[str, Any]]:
    """Загружает (names, files, pairs) из SQLite PropertyGraph.

    Исключает служебные узлы: Project/File/Folder/Package и placeholder
    __extern__ (нереальные символы-заглушки).
    """
    conn = graph._get_conn()
    placeholders = ",".join("?" * len(edge_types))

    nodes = conn.execute(
        """SELECT id, qualified_name, file_path FROM nodes
            WHERE qualified_name NOT LIKE '%.__extern__.%'
              AND label NOT IN ('Project', 'File', 'Folder', 'Package')
            ORDER BY id LIMIT ?""",
        (max_nodes,),
    ).fetchall()
    if len(nodes) >= max_nodes:
        return [], [], {"too_large": True, "reason": "nodes"}

    id_to_idx = {row[0]: idx for idx, row in enumerate(nodes)}
    names = [row[1] for row in nodes]
    files = [row[2] for row in nodes]

    edge_rows = conn.execute(
        f"""SELECT e.source_id, e.target_id, e.weight
            FROM edges e
            JOIN nodes s ON e.source_id = s.id
            JOIN nodes t ON e.target_id = t.id
            WHERE e.type IN ({placeholders})
              AND s.qualified_name NOT LIKE '%.__extern__.%'
              AND t.qualified_name NOT LIKE '%.__extern__.%'
              AND s.label NOT IN ('Project', 'File', 'Folder', 'Package')
              AND t.label NOT IN ('Project', 'File', 'Folder', 'Package')
            LIMIT ?""",
        (*edge_types, max_edges),
    ).fetchall()

    # Агрегация весов: мультирёбра (разные типы между парой) складываются
    weight_by_pair: Dict[Tuple[int, int], float] = {}
    for src_id, tgt_id, w in edge_rows:
        si = id_to_idx.get(src_id)
        ti = id_to_idx.get(tgt_id)
        if si is None or ti is None or si == ti:
            continue
        key = (si, ti) if si < ti else (ti, si)
        weight_by_pair[key] = weight_by_pair.get(key, 0.0) + (w or 1.0)

    pairs = [(s, t, w) for (s, t), w in weight_by_pair.items()]
    if len(edge_rows) >= max_edges:
        return [], [], {"too_large": True, "reason": "edges"}
    return names, files, {"pairs": pairs}


def _format_result(g, membership: List[int], top_communities: int) -> Dict[str, Any]:
    """Формирует результат: сообщества по убыванию размера + статистика."""
    if not membership:
        return {"status": "ok", "communities": 0, "communities_list": []}

    by_comm: Dict[int, List[int]] = {}
    for idx, c in enumerate(membership):
        by_comm.setdefault(c, []).append(idx)

    communities = []
    for c, idxs in sorted(by_comm.items(), key=lambda kv: -len(kv[1])):
        files = Counter(g.vs[i]["file"] for i in idxs if g.vs[i]["file"])
        symbols = [g.vs[i]["name"] for i in idxs[:10]]
        top_files = [
            {"file": f, "count": n} for f, n in files.most_common(5)
        ]
        communities.append(
            {
                "community_id": int(c),
                "size": len(idxs),
                "files": top_files,
                "sample_symbols": symbols,
            }
        )

    return {
        "status": "ok",
        "communities": len(communities),
        "nodes_analyzed": len(membership),
        "communities_list": communities[:top_communities],
    }
