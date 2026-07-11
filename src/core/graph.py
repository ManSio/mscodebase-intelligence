"""
Property Graph — персистентный типизированный граф знаний на SQLite.

Заменяет устаревшие Dict-хранилища (GraphRAGQueryEngine._graph,
RelationExtractor._graph, SymbolIndex._call_graph) единым персистентным
property graph с типизированными узлами и рёбрами.

Архитектура:
    Node: (id, name, label, qualified_name, file_path, properties JSON)
    Edge: (id, source_id, target_id, type, weight, properties JSON)

    - qualified_name UNIQUE — единственный источник истины для символов
    - properties JSON — для произвольных метаданных
    - Индексы по label, qualified_name, type — субмиллисекундные выборки

Совместимость:
    - SymbolIndex — адаптер SymbolIndexAdapter оборачивает PropertyGraph
      в интерфейс SymbolIndex (get_call_chain, search_symbols, impact...)
    - GraphRAGQueryEngine — адаптер GraphRAGAdapter оборачивает PropertyGraph
      в интерфейс query_impact / query_dependencies / query_feature

Фаза 1: PropertyGraph + адаптеры (обратная совместимость)
Фаза 2: Cypher-like query engine + dead code detection
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────
# Типы узлов (Node Labels)
# ────────────────────────────────────────────────────────────

class NodeLabel:
    """Канонические типы узлов графа."""
    PROJECT = "Project"
    PACKAGE = "Package"
    FOLDER = "Folder"
    FILE = "File"
    MODULE = "Module"
    CLASS = "Class"
    FUNCTION = "Function"
    METHOD = "Method"
    INTERFACE = "Interface"
    ENUM = "Enum"
    TYPE = "Type"
    ROUTE = "Route"
    RESOURCE = "Resource"
    TEST = "Test"
    VARIABLE = "Variable"


# ────────────────────────────────────────────────────────────
# Типы рёбер (Edge Types)
# ────────────────────────────────────────────────────────────

class EdgeType:
    """Канонические типы рёбер графа."""
    CONTAINS_PACKAGE = "CONTAINS_PACKAGE"
    CONTAINS_FOLDER = "CONTAINS_FOLDER"
    CONTAINS_FILE = "CONTAINS_FILE"
    DEFINES = "DEFINES"
    DEFINES_METHOD = "DEFINES_METHOD"
    IMPORTS = "IMPORTS"
    CALLS = "CALLS"
    HTTP_CALLS = "HTTP_CALLS"
    ASYNC_CALLS = "ASYNC_CALLS"
    IMPLEMENTS = "IMPLEMENTS"
    INHERITS = "INHERITS"
    HANDLES = "HANDLES"
    USAGE = "USAGE"
    CONFIGURES = "CONFIGURES"
    WRITES = "WRITES"
    MEMBER_OF = "MEMBER_OF"
    TESTS = "TESTS"
    USES_TYPE = "USES_TYPE"
    FILE_CHANGES_WITH = "FILE_CHANGES_WITH"
    CO_CHANGES = "CO_CHANGES"
    BUG_CORRELATES = "BUG_CORRELATES"
    DATA_FLOWS = "DATA_FLOWS"
    SIMILAR_TO = "SIMILAR_TO"
    SEMANTICALLY_RELATED = "SEMANTICALLY_RELATED"
    EMITS = "EMITS"
    LISTENS_ON = "LISTENS_ON"
    ASSIGNED_FROM = "ASSIGNED_FROM"


# ────────────────────────────────────────────────────────────
# Data Classes
# ────────────────────────────────────────────────────────────

class Node:
    """Узел графа."""

    __slots__ = ("id", "name", "label", "qualified_name", "file_path", "properties")

    def __init__(
        self,
        id: Optional[int] = None,
        name: str = "",
        label: str = NodeLabel.FILE,
        qualified_name: str = "",
        file_path: str = "",
        properties: Optional[Dict[str, Any]] = None,
    ):
        self.id = id
        self.name = name
        self.label = label
        self.qualified_name = qualified_name
        self.file_path = file_path
        self.properties = properties or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "label": self.label,
            "qualified_name": self.qualified_name,
            "file_path": self.file_path,
            "properties": self.properties,
        }

    @classmethod
    def from_row(cls, row: tuple) -> "Node":
        """Создаёт Node из строки SQLite (id, name, label, qualified_name, file_path, properties)."""
        return cls(
            id=row[0],
            name=row[1],
            label=row[2],
            qualified_name=row[3],
            file_path=row[4] or "",
            properties=json.loads(row[5]) if row[5] else {},
        )

    def __repr__(self) -> str:
        return f"Node({self.id}, {self.name}, {self.label})"


class Edge:
    """Ребро графа."""

    __slots__ = ("id", "source_id", "target_id", "type", "weight", "properties")

    def __init__(
        self,
        id: Optional[int] = None,
        source_id: int = 0,
        target_id: int = 0,
        type: str = EdgeType.CALLS,
        weight: float = 1.0,
        properties: Optional[Dict[str, Any]] = None,
    ):
        self.id = id
        self.source_id = source_id
        self.target_id = target_id
        self.type = type
        self.weight = weight
        self.properties = properties or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "type": self.type,
            "weight": self.weight,
            "properties": self.properties,
        }

    @classmethod
    def from_row(cls, row: tuple) -> "Edge":
        """Создаёт Edge из строки SQLite (id, source_id, target_id, type, weight, properties)."""
        return cls(
            id=row[0],
            source_id=row[1],
            target_id=row[2],
            type=row[3],
            weight=row[4],
            properties=json.loads(row[5]) if row[5] else {},
        )

    def __repr__(self) -> str:
        return f"Edge({self.id}, {self.source_id} -{self.type}-> {self.target_id})"


# ────────────────────────────────────────────────────────────
# Property Graph Engine
# ────────────────────────────────────────────────────────────

class PropertyGraph:
    """
    Персистентный property graph на SQLite.

    Хранит типизированные узлы и рёбра с JSON-свойствами.
    Все операции потокобезопасны (threading.RLock).

    Особенности:
    - qualified_name UNIQUE — дедупликация символов на уровне БД
    - Индексы: label, qualified_name, edge_type
    - WAL mode — конкурентные чтения без блокировок
    - Batch-операции для массовой загрузки
    """

    def __init__(self, db_path: Union[str, Path]):
        self._db_path = Path(db_path)
        self._lock = threading.RLock()
        self._conn: Optional["sqlite3.Connection"] = None
        self._open_count = 0  # для reopen после закрытия

    # ── Управление подключением ────────────────────────────

    def _get_conn(self):
        """Ленивое открытие SQLite."""
        if self._conn is None:
            import sqlite3

            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA cache_size=-64000")       # 64 MB page cache
            self._conn.execute("PRAGMA mmap_size=268435456")     # 256 MB mmap
            self._init_schema()
        return self._conn

    def _init_schema(self):
        """Инициализация схемы БД."""
        conn = self._conn
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                label TEXT NOT NULL DEFAULT 'File',
                qualified_name TEXT UNIQUE NOT NULL,
                file_path TEXT NOT NULL DEFAULT '',
                properties TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
                target_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
                type TEXT NOT NULL DEFAULT 'CALLS',
                weight REAL NOT NULL DEFAULT 1.0,
                properties TEXT NOT NULL DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_nodes_label ON nodes(label);
            CREATE INDEX IF NOT EXISTS idx_nodes_qname ON nodes(qualified_name);
            CREATE INDEX IF NOT EXISTS idx_nodes_file ON nodes(file_path);
            CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(type);
            CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
            CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_edges_unique
                ON edges(source_id, target_id, type);
        """)
        conn.commit()

    def close(self):
        """Закрывает подключение к БД."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    self._conn.commit()
                    self._conn.close()
                except Exception as e:
                    logger.debug(f"PropertyGraph close: {e}")
                finally:
                    self._conn = None

    @property
    def db_path(self) -> Path:
        return self._db_path

    # ── Node CRUD ──────────────────────────────────────────

    def add_node(
        self,
        name: str,
        label: str = NodeLabel.FILE,
        qualified_name: str = "",
        file_path: str = "",
        properties: Optional[Dict[str, Any]] = None,
    ) -> Node:
        """Добавляет узел. Если qualified_name уже существует — обновляет свойства.

        Args:
            name: Короткое имя узла (например, "MyClass", "process_order")
            label: Тип узла (NodeLabel.*)
            qualified_name: Уникальное полное имя (например, "project.file.MyClass")
            file_path: Путь к файлу (относительный)
            properties: Произвольные метаданные

        Returns:
            Node — созданный или обновлённый узел
        """
        qname = qualified_name or name
        props_json = json.dumps(properties or {}, ensure_ascii=False)

        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """INSERT INTO nodes (name, label, qualified_name, file_path, properties)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(qualified_name) DO UPDATE SET
                       name=excluded.name,
                       label=excluded.label,
                       file_path=excluded.file_path,
                       properties=excluded.properties""",
                (name, label, qname, file_path, props_json),
            )
            conn.commit()

            # Возвращаем созданную запись
            row = conn.execute(
                "SELECT id, name, label, qualified_name, file_path, properties "
                "FROM nodes WHERE qualified_name = ?",
                (qname,),
            ).fetchone()
            return Node.from_row(row)

    def get_node(self, qualified_name: str) -> Optional[Node]:
        """Получает узел по qualified_name."""
        with self._lock:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT id, name, label, qualified_name, file_path, properties "
                "FROM nodes WHERE qualified_name = ?",
                (qualified_name,),
            ).fetchone()
            return Node.from_row(row) if row else None

    def get_node_by_id(self, node_id: int) -> Optional[Node]:
        """Получает узел по ID."""
        with self._lock:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT id, name, label, qualified_name, file_path, properties "
                "FROM nodes WHERE id = ?",
                (node_id,),
            ).fetchone()
            return Node.from_row(row) if row else None

    def delete_node(self, qualified_name: str) -> bool:
        """Удаляет узел (и все его рёбра по CASCADE).

        Returns:
            True если узел был удалён
        """
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "DELETE FROM nodes WHERE qualified_name = ?", (qualified_name,)
            )
            conn.commit()
            return conn.total_changes > 0

    def find_nodes(
        self,
        label: Optional[str] = None,
        name_pattern: Optional[str] = None,
        file_path: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Node]:
        """Поиск узлов по фильтрам.

        Args:
            label: Фильтр по типу узла (NodeLabel.*)
            name_pattern: LIKE-паттерн для имени (например, "%Handler%")
            file_path: Фильтр по файлу
            limit: Максимум результатов
            offset: Смещение (для пагинации)

        Returns:
            Список Node
        """
        conditions: List[str] = []
        params: List[Any] = []

        if label:
            conditions.append("label = ?")
            params.append(label)
        if name_pattern:
            conditions.append("(name LIKE ? OR qualified_name LIKE ?)")
            params.extend([name_pattern, name_pattern])
        if file_path:
            conditions.append("file_path = ?")
            params.append(file_path)

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = (
            f"SELECT id, name, label, qualified_name, file_path, properties "
            f"FROM nodes WHERE {where} ORDER BY name LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])

        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(sql, params).fetchall()
            return [Node.from_row(r) for r in rows]

    def find_nodes_by_property(
        self,
        label: Optional[str] = None,
        property_key: str = "",
        property_value: str = "",
        name_pattern: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Node]:
        """Поиск узлов по значению в JSON properties.

        Использует SQLite json_extract для фильтрации.

        Args:
            label: Фильтр по типу узла
            property_key: Ключ в JSON properties (например, "function_scope")
            property_value: Искомое значение
            name_pattern: LIKE-паттерн для имени (доп. фильтр)
            limit: Максимум результатов
            offset: Смещение

        Returns:
            Список Node
        """
        conditions: List[str] = []
        params: List[Any] = []

        if label:
            conditions.append("label = ?")
            params.append(label)
        if property_key and property_value:
            conditions.append(f"json_extract(properties, '$.{property_key}') = ?")
            params.append(property_value)
        if name_pattern:
            conditions.append("(name LIKE ? OR qualified_name LIKE ?)")
            params.extend([name_pattern, name_pattern])

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = (
            f"SELECT id, name, label, qualified_name, file_path, properties "
            f"FROM nodes WHERE {where} ORDER BY name LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])

        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(sql, params).fetchall()
            return [Node.from_row(r) for r in rows]

    def get_edges_by_properties(
        self,
        edge_type: Optional[str] = None,
        property_key: str = "",
        property_value: str = "",
        limit: int = 100,
    ) -> List[Tuple[Node, Node, "Edge"]]:
        """Поиск рёбер по типу и JSON properties.

        Возвращает (source_node, target_node, edge) для каждого ребра.

        Args:
            edge_type: Фильтр по типу ребра (EdgeType.*)
            property_key: Ключ в JSON properties (например, "scope_id")
            property_value: Искомое значение
            limit: Максимум результатов

        Returns:
            Список (source_node, target_node, edge)
        """
        conditions: List[str] = []
        params: List[Any] = []

        if edge_type:
            conditions.append("e.type = ?")
            params.append(edge_type)
        if property_key and property_value:
            conditions.append(f"json_extract(e.properties, '$.{property_key}') = ?")
            params.append(property_value)

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"""
            SELECT e.id, e.source_id, e.target_id, e.type, e.weight, e.properties,
                   s.id AS s_id, s.name AS s_name, s.label AS s_label,
                   s.qualified_name AS s_qname, s.file_path AS s_file,
                   s.properties AS s_props,
                   t.id AS t_id, t.name AS t_name, t.label AS t_label,
                   t.qualified_name AS t_qname, t.file_path AS t_file,
                   t.properties AS t_props
            FROM edges e
            JOIN nodes s ON e.source_id = s.id
            JOIN nodes t ON e.target_id = t.id
            WHERE {where}
            ORDER BY e.id
            LIMIT ?
        """
        params.append(limit)

        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(sql, params).fetchall()
            from .graph import Edge  # local import to avoid circular
            results = []
            for r in rows:
                src = Node(
                    id=r["s_id"], name=r["s_name"], label=r["s_label"],
                    qualified_name=r["s_qname"], file_path=r["s_file"],
                    properties=json.loads(r["s_props"]),
                )
                tgt = Node(
                    id=r["t_id"], name=r["t_name"], label=r["t_label"],
                    qualified_name=r["t_qname"], file_path=r["t_file"],
                    properties=json.loads(r["t_props"]),
                )
                edge = Edge.from_row(r)
                results.append((src, tgt, edge))
            return results

    def count_nodes(self, label: Optional[str] = None) -> int:
        """Количество узлов (опционально по label)."""
        with self._lock:
            conn = self._get_conn()
            if label:
                row = conn.execute(
                    "SELECT COUNT(*) FROM nodes WHERE label = ?", (label,)
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()
            return row[0]

    # ── Edge CRUD ──────────────────────────────────────────

    def add_edge(
        self,
        source_qname: str,
        target_qname: str,
        type: str = EdgeType.CALLS,
        weight: float = 1.0,
        properties: Optional[Dict[str, Any]] = None,
    ) -> Optional[Edge]:
        """Добавляет ребро между двумя узлами (по qualified_name).

        Автоматически создаёт узлы, если их нет (с label=File).
        Если ребро уже существует — обновляет weight.

        Args:
            source_qname: qualified_name исходного узла
            target_qname: qualified_name целевого узла
            type: Тип ребра (EdgeType.*)
            weight: Вес ребра
            properties: Произвольные метаданные

        Returns:
            Edge или None если узлы не найдены
        """
        props_json = json.dumps(properties or {}, ensure_ascii=False)

        with self._lock:
            conn = self._get_conn()

            # Находим ID узлов (или создаём заглушки)
            source = conn.execute(
                "SELECT id FROM nodes WHERE qualified_name = ?", (source_qname,)
            ).fetchone()
            target = conn.execute(
                "SELECT id FROM nodes WHERE qualified_name = ?", (target_qname,)
            ).fetchone()

            if not source or not target:
                return None

            conn.execute(
                """INSERT INTO edges (source_id, target_id, type, weight, properties)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(source_id, target_id, type) DO UPDATE SET
                       weight=excluded.weight,
                       properties=excluded.properties""",
                (source[0], target[0], type, weight, props_json),
            )
            conn.commit()

            row = conn.execute(
                "SELECT id, source_id, target_id, type, weight, properties "
                "FROM edges WHERE source_id = ? AND target_id = ? AND type = ?",
                (source[0], target[0], type),
            ).fetchone()
            return Edge.from_row(row) if row else None

    def add_edge_by_ids(
        self,
        source_id: int,
        target_id: int,
        type: str = EdgeType.CALLS,
        weight: float = 1.0,
        properties: Optional[Dict[str, Any]] = None,
    ) -> Optional[Edge]:
        """Добавляет ребро по ID узлов."""
        props_json = json.dumps(properties or {}, ensure_ascii=False)

        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """INSERT INTO edges (source_id, target_id, type, weight, properties)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(source_id, target_id, type) DO UPDATE SET
                       weight=excluded.weight,
                       properties=excluded.properties""",
                (source_id, target_id, type, weight, props_json),
            )
            conn.commit()

            row = conn.execute(
                "SELECT id, source_id, target_id, type, weight, properties "
                "FROM edges WHERE source_id = ? AND target_id = ? AND type = ?",
                (source_id, target_id, type),
            ).fetchone()
            return Edge.from_row(row) if row else None

    def delete_edge(self, source_qname: str, target_qname: str, type: str) -> bool:
        """Удаляет ребро."""
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """DELETE FROM edges WHERE source_id IN
                       (SELECT id FROM nodes WHERE qualified_name = ?)
                   AND target_id IN (SELECT id FROM nodes WHERE qualified_name = ?)
                   AND type = ?""",
                (source_qname, target_qname, type),
            )
            conn.commit()
            return conn.total_changes > 0

    # ── Траверсал ──────────────────────────────────────────

    def get_neighbors(
        self,
        qualified_name: str,
        edge_type: Optional[str] = None,
        direction: str = "outgoing",
        max_depth: int = 1,
    ) -> List[Tuple[Node, Edge, int]]:
        """Обход графа от узла.

        Args:
            qualified_name: Стартовый узел
            edge_type: Фильтр по типу ребра (None = все типы)
            direction: 'outgoing' (из узла), 'incoming' (в узел), 'both'
            max_depth: Глубина обхода (1 = прямые соседи)

        Returns:
            Список (соседний_узел, ребро, глубина)
        """
        node = self.get_node(qualified_name)
        if not node:
            return []

        results: List[Tuple[Node, Edge, int]] = []
        visited: Set[int] = {node.id}
        current_level: Set[int] = {node.id}

        for depth in range(max_depth):
            if not current_level:
                break

            next_level: Set[int] = set()
            for nid in current_level:
                edges_data = self._get_edges_for_node(nid, edge_type, direction)
                for edge_row, neighbor_id in edges_data:
                    if neighbor_id in visited:
                        continue
                    visited.add(neighbor_id)
                    neighbor = self.get_node_by_id(neighbor_id)
                    if neighbor:
                        edge = Edge.from_row(edge_row)
                        results.append((neighbor, edge, depth + 1))
                        next_level.add(neighbor_id)

            current_level = next_level

        return results

    def _get_edges_for_node(
        self,
        node_id: int,
        edge_type: Optional[str] = None,
        direction: str = "outgoing",
    ) -> List[Tuple[sqlite3.Row, int]]:
        """Внутренний метод получения рёбер для узла."""
        conn = self._get_conn()

        queries = []
        if direction in ("outgoing", "both"):
            sql = "SELECT * FROM edges WHERE source_id = ?"
            params: List[Any] = [node_id]
            if edge_type:
                sql += " AND type = ?"
                params.append(edge_type)
            queries.append((sql, params, "target_id"))

        if direction in ("incoming", "both"):
            sql = "SELECT * FROM edges WHERE target_id = ?"
            params = [node_id]
            if edge_type:
                sql += " AND type = ?"
                params.append(edge_type)
            queries.append((sql, params, "source_id"))

        results = []
        for sql, params, neighbor_col in queries:
            rows = conn.execute(sql, params).fetchall()
            for row in rows:
                neighbor_id = row[neighbor_col]
                results.append((row, neighbor_id))

        return results

    def shortest_path(
        self,
        source_qname: str,
        target_qname: str,
        edge_type: Optional[str] = None,
        max_depth: int = 10,
    ) -> List[Tuple[Node, Edge]]:
        """BFS кратчайший путь между двумя узлами.

        Returns:
            Список (узел, ребро) от source до target, или [] если путь не найден
        """
        source = self.get_node(source_qname)
        target = self.get_node(target_qname)
        if not source or not target:
            return []

        if source.id == target.id:
            return [(source, None)]

        with self._lock:
            conn = self._get_conn()
            visited: Set[int] = {source.id}
            queue: List[List[Tuple[int, Optional[int]]]] = [[(source.id, None)]]

            for _ in range(max_depth):
                if not queue:
                    break
                next_queue: List[List[Tuple[int, Optional[int]]]] = []

                for path in queue:
                    last_id = path[-1][0]
                    edges_sql = (
                        "SELECT id, source_id, target_id, type, weight, properties "
                        "FROM edges WHERE source_id = ?"
                    )
                    params: List[Any] = [last_id]
                    if edge_type:
                        edges_sql += " AND type = ?"
                        params.append(edge_type)

                    rows = conn.execute(edges_sql, params).fetchall()
                    for row in rows:
                        neighbor_id = row["target_id"]
                        if neighbor_id in visited:
                            continue
                        visited.add(neighbor_id)

                        new_path = path + [(neighbor_id, row["id"])]
                        if neighbor_id == target.id:
                            # Восстанавливаем полный путь
                            return self._reconstruct_path(new_path)

                        next_queue.append(new_path)

                queue = next_queue

            return []  # Путь не найден

    def _reconstruct_path(
        self, path_ids: List[Tuple[int, Optional[int]]]
    ) -> List[Tuple[Node, Edge]]:
        """Восстанавливает путь из ID в Node/Edge."""
        result = []
        for i, (node_id, edge_id) in enumerate(path_ids):
            node = self.get_node_by_id(node_id)
            edge = None
            if edge_id is not None:
                conn = self._get_conn()
                row = conn.execute("SELECT * FROM edges WHERE id = ?", (edge_id,)).fetchone()
                if row:
                    edge = Edge.from_row(row)
            result.append((node, edge))
        return result

    # ── Аналитика ─────────────────────────────────────────

    def detect_dead_code(self) -> List[Node]:
        """Находит функции/методы без входящих CALLS-рёбер.

        Исключает entry points (main, run, start, handle и т.д.)

        Returns:
            Список узлов-кандидатов на dead code
        """
        entry_points = {"main", "run", "start", "handle", "entry", "bootstrap", "init_app"}

        with self._lock:
            conn = self._get_conn()
            return self._detect_dead_code_impl(conn, entry_points)

    def _detect_dead_code_impl(
        self, conn, entry_points: Set[str]
    ) -> List[Node]:
        placeholders = ",".join("?" for _ in entry_points)
        rows = conn.execute(
            f"""SELECT n.id, n.name, n.label, n.qualified_name, n.file_path, n.properties
                FROM nodes n
                WHERE n.label IN ('Function', 'Method')
                  AND n.name NOT IN ({placeholders})
                AND NOT EXISTS (
                    SELECT 1 FROM edges e
                    WHERE e.target_id = n.id
                      AND e.type IN ('CALLS', 'ASYNC_CALLS')
                )
                ORDER BY n.file_path, n.name
                LIMIT 200""",
            tuple(entry_points),
        ).fetchall()
        return [Node.from_row(r) for r in rows]

    def get_node_stats(self) -> Dict[str, int]:
        """Статистика по типам узлов."""
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT label, COUNT(*) as cnt FROM nodes GROUP BY label ORDER BY cnt DESC"
            ).fetchall()
            return {row["label"]: row["cnt"] for row in rows}

    def get_edge_stats(self) -> Dict[str, int]:
        """Статистика по типам рёбер."""
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT type, COUNT(*) as cnt FROM edges GROUP BY type ORDER BY cnt DESC"
            ).fetchall()
            return {row["type"]: row["cnt"] for row in rows}

    def get_graph_summary(self) -> Dict[str, Any]:
        """Сводка по графу."""
        with self._lock:
            conn = self._get_conn()
            node_count = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            edge_count = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
            file_count = conn.execute(
                "SELECT COUNT(DISTINCT file_path) FROM nodes WHERE file_path != ''"
            ).fetchone()[0]
            return {
                "total_nodes": node_count,
                "total_edges": edge_count,
                "total_files": file_count,
                "node_labels": self.get_node_stats(),
                "edge_types": self.get_edge_stats(),
            }

    # ── Batch операции ─────────────────────────────────────

    def begin_batch(self):
        """Начинает batch-режим (отключает авто-коммит).

        Использовать с with:
            pg.begin_batch()
            for ...: pg.add_node(...)
            pg.commit_batch()
        """
        conn = self._get_conn()
        conn.execute("BEGIN TRANSACTION")

    def commit_batch(self):
        """Завершает batch и коммитит."""
        conn = self._get_conn()
        conn.commit()

    def batch_add_nodes(self, nodes: List[Dict[str, Any]]) -> int:
        """Массовое добавление узлов в одной транзакции.

        Args:
            nodes: Список словарей с полями name, label, qualified_name, file_path, properties

        Returns:
            Количество добавленных/обновлённых узлов
        """
        count = 0
        with self._lock:
            conn = self._get_conn()
            conn.execute("BEGIN TRANSACTION")
            try:
                for n in nodes:
                    qname = n.get("qualified_name", n["name"])
                    props_json = json.dumps(n.get("properties", {}), ensure_ascii=False)
                    conn.execute(
                        """INSERT INTO nodes (name, label, qualified_name, file_path, properties)
                           VALUES (?, ?, ?, ?, ?)
                           ON CONFLICT(qualified_name) DO UPDATE SET
                               name=excluded.name, label=excluded.label,
                               file_path=excluded.file_path, properties=excluded.properties""",
                        (
                            n["name"],
                            n.get("label", NodeLabel.FILE),
                            qname,
                            n.get("file_path", ""),
                            props_json,
                        ),
                    )
                    count += 1
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return count

    def batch_add_edges(self, edges: List[Dict[str, Any]]) -> int:
        """Массовое добавление рёбер в одной транзакции.

        Args:
            edges: Список словарей с полями source_qname, target_qname, type, weight, properties

        Returns:
            Количество добавленных/обновлённых рёбер
        """
        count = 0
        with self._lock:
            conn = self._get_conn()
            conn.execute("BEGIN TRANSACTION")
            try:
                for e in edges:
                    source = conn.execute(
                        "SELECT id FROM nodes WHERE qualified_name = ?",
                        (e["source_qname"],),
                    ).fetchone()
                    target = conn.execute(
                        "SELECT id FROM nodes WHERE qualified_name = ?",
                        (e["target_qname"],),
                    ).fetchone()

                    if not source or not target:
                        logger.warning(
                            f"Skipping edge: node not found "
                            f"({e.get('source_qname')} -> {e.get('target_qname')})"
                        )
                        continue

                    props_json = json.dumps(e.get("properties", {}), ensure_ascii=False)
                    conn.execute(
                        """INSERT INTO edges (source_id, target_id, type, weight, properties)
                           VALUES (?, ?, ?, ?, ?)
                           ON CONFLICT(source_id, target_id, type) DO UPDATE SET
                               weight=excluded.weight, properties=excluded.properties""",
                        (
                            source[0],
                            target[0],
                            e.get("type", EdgeType.CALLS),
                            e.get("weight", 1.0),
                            props_json,
                        ),
                    )
                    count += 1
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return count

    # ── Экспорт/Иморт (Team-Shared Artifact) ──────────────

    def export_compressed(self, output_path: Path, compression_level: int = 9) -> Path:
        """Экспортирует граф в zstd-сжатый файл.

        Снимает индексы, VACUUM INTO, zstd-сжимает.
        Подготовка для team-shared artifact (Фаза 3).

        Args:
            output_path: Путь к выходному .zst файлу
            compression_level: Уровень сжатия zstd (1-22)

        Returns:
            Путь к созданному файлу
        """
        import subprocess
        import sys

        with self._lock:
            conn = self._get_conn()

            # Снимаем индексы перед дампом
            conn.executescript("""
                DROP INDEX IF EXISTS idx_nodes_label;
                DROP INDEX IF EXISTS idx_nodes_qname;
                DROP INDEX IF EXISTS idx_nodes_file;
                DROP INDEX IF EXISTS idx_edges_type;
                DROP INDEX IF EXISTS idx_edges_source;
                DROP INDEX IF EXISTS idx_edges_target;
                DROP INDEX IF EXISTS idx_edges_unique;
            """)
            conn.commit()

            # VACUUM INTO
            temp_db = output_path.with_suffix(".tmp.db")
            conn.execute("VACUUM INTO ?", (str(temp_db),))
            conn.commit()

            # Восстанавливаем индексы
            self._init_schema()
            conn.commit()

        # zstd-сжатие
        try:
            import zstandard

            with open(temp_db, "rb") as fin:
                data = fin.read()
            compressed = zstandard.compress(data, compression_level)
            output_path.write_bytes(compressed)
        except ImportError:
            # fallback: system zstd
            subprocess.run(
                [sys.executable, "-m", "zstandard", f"-{compression_level}",
                 str(temp_db), "-o", str(output_path)],
                check=True,
            )

        temp_db.unlink()
        logger.info(f"Graph exported: {temp_db.stat().st_size / 1024:.0f} KB -> "
                    f"{output_path} ({len(compressed) / 1024:.0f} KB zstd)")
        return output_path

    def import_compressed(self, input_path: Path) -> int:
        """Импортирует zstd-сжатый граф.

        Распаковывает, загружает в SQLite, запускает инкрементальную
        индексацию (добавляет только новые записи).

        Args:
            input_path: Путь к .zst файлу

        Returns:
            Количество импортированных узлов
        """
        import tempfile

        # Распаковка
        try:
            import zstandard

            data = input_path.read_bytes()
            decompressed = zstandard.decompress(data)
        except ImportError:
            import subprocess
            import sys

            result = subprocess.run(
                [sys.executable, "-m", "zstandard", "-d", str(input_path)],
                capture_output=True,
            )
            decompressed = result.stdout

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(decompressed)

        # Загружаем во временную БД, мержим
        import sqlite3

        src_conn = sqlite3.connect(str(tmp_path))
        src_conn.row_factory = sqlite3.Row

        with self._lock:
            conn = self._get_conn()
            conn.execute("BEGIN TRANSACTION")
            try:
                # Копируем узлы (IGNORE — не перезаписываем существующие)
                conn.execute("""
                    INSERT OR IGNORE INTO nodes (name, label, qualified_name, file_path, properties)
                    SELECT name, label, qualified_name, file_path, properties
                    FROM tmp.nodes
                """)
                node_count = conn.total_changes

                # Копируем рёбра (IGNORE)
                conn.execute("""
                    INSERT OR IGNORE INTO edges (source_id, target_id, type, weight, properties)
                    SELECT
                        COALESCE(dst.id, src.id),
                        COALESCE(dst2.id, src2.id),
                        e.type, e.weight, e.properties
                    FROM tmp.edges e
                    LEFT JOIN nodes dst ON dst.qualified_name = (
                        SELECT qualified_name FROM tmp.nodes WHERE id = e.source_id
                    )
                    LEFT JOIN nodes dst2 ON dst2.qualified_name = (
                        SELECT qualified_name FROM tmp.nodes WHERE id = e.target_id
                    )
                """)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        src_conn.close()
        tmp_path.unlink()

        logger.info(f"Graph imported: {node_count} new nodes")
        return node_count

    # ── Очистка ───────────────────────────────────────────

    def clear(self):
        """Очищает граф (все узлы и рёбра)."""
        with self._lock:
            conn = self._get_conn()
            conn.execute("DELETE FROM edges")
            conn.execute("DELETE FROM nodes")
            conn.commit()

    def clear_project(self, project_prefix: str):
        """Удаляет все узлы проекта (qualified_name STARTS WITH)."""
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "DELETE FROM nodes WHERE qualified_name LIKE ? || '%'",
                (project_prefix,),
            )
            conn.commit()

    def remove_file(self, file_path: str) -> int:
        """Удаляет все узлы и рёбра для файла. Возвращает количество удалённых узлов.

        Рёбра удаляются каскадно (ON DELETE CASCADE).
        """
        with self._lock:
            conn = self._get_conn()
            cur = conn.execute("DELETE FROM nodes WHERE file_path = ?", (file_path,))
            deleted = cur.rowcount
            conn.commit()
            return deleted


# Экспорт
__all__ = [
    "NodeLabel",
    "EdgeType",
    "Node",
    "Edge",
    "PropertyGraph",
]
