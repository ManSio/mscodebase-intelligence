"""Graph Symbol Resolver module for MSCodeBase.

Resolves placeholder nodes (`__extern__` nodes) into real symbol nodes or
external dependencies, and cleans up unresolved nodes in a second pass.
"""

from __future__ import annotations

import importlib.util
import logging
import re
import sys
from typing import Dict, List, Tuple

from src.core.graph import EdgeType, Node, NodeLabel, PropertyGraph

logger = logging.getLogger(__name__)


def get_module_dot_path(file_path: str) -> str:
    """Converts a file path to its module dot-path representation."""
    p = file_path.replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    if p.startswith("/"):
        p = p[1:]
    # Remove file extension
    if "." in p:
        p = p.rsplit(".", 1)[0]
    return p.replace("/", ".")


def resolve_relative_import(base_dot_path: str, relative_path: str) -> str:
    """Resolves relative import paths (e.g. '.graph_adapter') to absolute dot-paths."""
    if not relative_path.startswith("."):
        return relative_path

    parts = base_dot_path.split(".")
    # The first pop is always for removing the current file/module name
    if parts:
        parts.pop()

    # Count the number of leading dots
    leading_dots = 0
    for char in relative_path:
        if char == ".":
            leading_dots += 1
        else:
            break

    # Pop one additional level for each dot beyond the first
    for _ in range(leading_dots - 1):
        if parts:
            parts.pop()

    # Strip the leading dots from the relative path and join
    rel_strip = relative_path[leading_dots:]
    if rel_strip:
        parts.append(rel_strip)

    return ".".join(parts)


def parse_import_text(text: str) -> List[Tuple[str, str]]:
    """Parses import text lines and returns list of (imported_symbol, full_import_path)."""
    results = []
    # Handle "from ... import ..."
    from_import_match = re.search(r'from\s+([\w\.]+)\s+import\s+([\w\s,]+)', text)
    if from_import_match:
        module_path = from_import_match.group(1)
        imports_part = from_import_match.group(2)
        # Split by comma for multiple imports
        for imp in imports_part.split(','):
            imp = imp.strip()
            if not imp:
                continue
            # Handle "x as y"
            if " as " in imp:
                parts = imp.split(" as ")
                imported_name = parts[0].strip()
                alias_name = parts[1].strip()
                results.append((alias_name, f"{module_path}.{imported_name}"))
                results.append((imported_name, f"{module_path}.{imported_name}"))
            else:
                results.append((imp, f"{module_path}.{imp}"))
    else:
        # Handle "import ..."
        import_match = re.search(r'import\s+([\w\.]+)(?:\s+as\s+(\w+))?', text)
        if import_match:
            module_path = import_match.group(1)
            alias_name = import_match.group(2)
            if alias_name:
                results.append((alias_name, module_path))
            results.append((module_path.split('.')[-1], module_path))
    return results


def is_external_or_stdlib(module_name: str) -> bool:
    """Checks if a module name is a standard library module or an external package."""
    if not module_name:
        return False
    # Builtin modules
    if module_name in sys.builtin_module_names:
        return True

    # Common stdlib modules fallback list
    stdlib_modules = {
        "os", "sys", "json", "math", "re", "collections", "datetime", "urllib", "http",
        "hashlib", "time", "pathlib", "functools", "typing", "subprocess", "logging",
        "ctypes", "sqlite3", "tempfile", "shutil", "ast", "inspect", "enum", "abc",
        "threading", "queue", "socket", "select", "asyncio", "xml", "csv", "uuid",
        "copy", "argparse", "weakref", "platform", "importlib", "traceback", "trace"
    }
    top_level = module_name.split(".")[0]
    if top_level in stdlib_modules:
        return True

    # Check if we can find it in the environment as stdlib or third party
    try:
        spec = importlib.util.find_spec(top_level)
        if spec is not None:
            origin = spec.origin
            if origin:
                origin_str = str(origin).replace("\\", "/").lower()
                if "site-packages" in origin_str or "dist-packages" in origin_str or "lib" in origin_str:
                    return True
            else:
                return True
    except (ImportError, ValueError, TypeError):
        pass

    common_external = {
        "pydantic", "fastapi", "httpx", "lancedb", "numpy", "pytest", "yaml", "jinja2", "uvicorn"
    }
    if top_level in common_external:
        return True

    return False


def redirect_edges(
    graph: PropertyGraph,
    placeholder_node: Node,
    target_node: Node,
    confidence_score: float,
    resolver_type: str,
):
    """Copies incoming and outgoing edges from placeholder_node to target_node with resolution metadata."""
    # Redirect incoming edges
    incoming = graph.get_neighbors(placeholder_node.qualified_name, direction="incoming")
    for caller_node, edge, depth in incoming:
        source_qname = caller_node.qualified_name
        target_qname = target_node.qualified_name

        edge_props = dict(edge.properties)
        edge_props.update({
            "confidence": "RESOLVED",
            "confidence_score": confidence_score,
            "resolver": resolver_type,
        })

        graph.add_edge(
            source_qname=source_qname,
            target_qname=target_qname,
            type=edge.type,
            weight=edge.weight,
            properties=edge_props
        )

    # Redirect outgoing edges
    outgoing = graph.get_neighbors(placeholder_node.qualified_name, direction="outgoing")
    for callee_node, edge, depth in outgoing:
        source_qname = target_node.qualified_name
        target_qname = callee_node.qualified_name

        edge_props = dict(edge.properties)
        edge_props.update({
            "confidence": "RESOLVED",
            "confidence_score": confidence_score,
            "resolver": resolver_type,
        })

        graph.add_edge(
            source_qname=source_qname,
            target_qname=target_qname,
            type=edge.type,
            weight=edge.weight,
            properties=edge_props
        )


class GraphSymbolResolver:
    """Two-pass Graph Symbol Resolver."""

    @staticmethod
    def resolve_all(graph: PropertyGraph) -> int:
        """Resolves all `__extern__` placeholder nodes in the graph to real nodes or dependencies.

        Returns:
            The number of resolved placeholder nodes.
        """
        resolved_count = 0

        with graph._lock:
            conn = graph._get_conn()

            # 1. Fetch all real nodes to build the lookup dictionary
            rows_real = conn.execute(
                "SELECT id, name, label, qualified_name, file_path, properties FROM nodes "
                "WHERE qualified_name NOT LIKE '%.__extern__.%'"
            ).fetchall()
            real_nodes = [Node.from_row(r) for r in rows_real]

            fqn_map: Dict[str, Node] = {}
            short_name_map: Dict[str, List[Node]] = {}
            import_path_map: Dict[str, Node] = {}

            for node in real_nodes:
                if node.properties.get("placeholder"):
                    continue

                fqn_map[node.qualified_name] = node

                if node.name not in short_name_map:
                    short_name_map[node.name] = []
                short_name_map[node.name].append(node)

                if node.file_path:
                    mod_dot_path = get_module_dot_path(node.file_path)
                    if mod_dot_path:
                        dot_path = f"{mod_dot_path}.{node.name}"
                        import_path_map[dot_path] = node

            # 2. Fetch all placeholder nodes
            rows_placeholder = conn.execute(
                "SELECT id, name, label, qualified_name, file_path, properties FROM nodes "
                "WHERE qualified_name LIKE '%.__extern__.%' OR json_extract(properties, '$.placeholder') = 1"
            ).fetchall()
            placeholder_nodes = [Node.from_row(r) for r in rows_placeholder]

            for node in placeholder_nodes:
                resolved = False
                caller_file = node.file_path

                # 3.1. Match by Import/FQN
                if caller_file:
                    project_name = node.qualified_name.split(".")[0]
                    file_qname = f"{project_name}.{caller_file}"
                    imports = graph.get_neighbors(file_qname, edge_type=EdgeType.IMPORTS, direction="outgoing")

                    for _, edge, _ in imports:
                        text = edge.properties.get("text", "")
                        if not text:
                            continue

                        imported_symbols = parse_import_text(text)
                        for imp_name, imp_full_path in imported_symbols:
                            caller_module_path = get_module_dot_path(caller_file)
                            imp_resolved_path = resolve_relative_import(caller_module_path, imp_full_path)

                            if node.name == imp_name:
                                target_node = import_path_map.get(imp_resolved_path)
                                if target_node:
                                    redirect_edges(graph, node, target_node, confidence_score=1.0, resolver_type="import")
                                    graph.delete_node(node.qualified_name)
                                    resolved = True
                                    resolved_count += 1
                                    break
                        if resolved:
                            break

                if resolved:
                    continue

                # 3.2. Match by Unique Global Name
                matching_nodes = short_name_map.get(node.name, [])
                if len(matching_nodes) == 1:
                    target_node = matching_nodes[0]
                    redirect_edges(graph, node, target_node, confidence_score=0.85, resolver_type="unique_global")
                    graph.delete_node(node.qualified_name)
                    resolved = True
                    resolved_count += 1
                    continue

                # 3.3. Stdlib / External Packages
                top_level = node.name.split(".")[0]
                if is_external_or_stdlib(top_level):
                    project_name = node.qualified_name.split(".")[0]
                    new_qname = f"{project_name}.dependency.{node.name}"

                    # Create or update DEPENDENCY node
                    graph.add_node(
                        name=node.name,
                        label=NodeLabel.DEPENDENCY,
                        qualified_name=new_qname,
                        file_path=node.file_path,
                        properties={
                            "dependency_type": "stdlib" if top_level in sys.builtin_module_names or top_level in {"os", "sys", "json", "math", "re"} else "external_package",
                            "package_name": top_level,
                            "unresolved": False,
                            "confidence": 1.0,
                        }
                    )

                    resolved_target = graph.get_node(new_qname)
                    if resolved_target:
                        redirect_edges(graph, node, resolved_target, confidence_score=1.0, resolver_type="stdlib")
                        graph.delete_node(node.qualified_name)
                        resolved = True
                        resolved_count += 1
                        continue

                # 3.4. Unresolved / Dynamic Fallback
                props = dict(node.properties)
                props.update({
                    "unresolved": True,
                    "confidence": 0.4,
                })
                graph.add_node(
                    name=node.name,
                    label=node.label,
                    qualified_name=node.qualified_name,
                    file_path=node.file_path,
                    properties=props
                )

        return resolved_count
