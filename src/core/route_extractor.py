"""
Route Extractor — автоматическое извлечение HTTP-маршрутов из кода.

Создаёт Route nodes и HANDLES/HTTP_CALLS edges в PropertyGraph.

Поддерживаемые фреймворки:
  - Flask:     @app.route('/path', methods=['GET'])
  - FastAPI:   @app.get('/path'), @app.post('/path'), @router.get(...)
  - Django:    path('url/', view), re_path(...) в urls.py
  - Express:   app.get('/path', handler), router.post(...)
  - Next.js:   файловая конвенция page.tsx, route.ts, api/route.ts

Использование:
    extractor = RouteExtractor(graph, project_root)
    routes = extractor.extract_from_file(file_path, content)
    # → создаёт Route nodes + HANDLES edges в PropertyGraph
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from src.core.graph import EdgeType, NodeLabel, PropertyGraph
from src.core.graph_adapter import SymbolIndexAdapter

logger = logging.getLogger(__name__)


# ── Паттерны для детекции роутов ─────────────────────────

# Flask: @app.route('/path', methods=['GET'])
_FLASK_ROUTE = re.compile(
    r'@\w+\.route\s*\(\s*[\'"]([^\'"]+)[\'"]\s*(?:,\s*methods\s*=\s*\[([^\]]*)\])?',
    re.IGNORECASE,
)

# FastAPI: @app.get('/path'), @app.post('/path'), @router.get(...)
_FASTAPI_ROUTE = re.compile(
    r'@\w+\.(get|post|put|delete|patch|options|head)\s*\(\s*[\'"]([^\'"]+)[\'"]',
    re.IGNORECASE,
)

# Django: path('url/', view_func) или re_path(...)
_DJANGO_PATH = re.compile(
    r'(?:path|re_path)\s*\(\s*[\'"]([^\'"]+)[\'"]\s*,\s*(\w+(?:\.\w+)*)',
    re.IGNORECASE,
)

# Express: app.get('/path', handler), router.post(...)
_EXPRESS_ROUTE = re.compile(
    r'(?:app|router|route)\.(get|post|put|delete|patch|options|head|all)\s*\(\s*[\'"]([^\'"]+)[\'"]',
    re.IGNORECASE,
)

# Next.js API route: export async function GET(req) / POST(req)
_NEXTJS_API = re.compile(
    r'export\s+(?:async\s+)?function\s+(GET|POST|PUT|DELETE|PATCH)\s*\(',
    re.IGNORECASE,
)

# Django URL patterns: path('admin/', admin.site.urls)
_DJANGO_INCLUDE = re.compile(
    r"path\s*\(\s*['\"]((?:[^'\"]*))['\"]\s*,\s*include\s*\(",
    re.IGNORECASE,
)


class RouteExtractor:
    """Извлекает HTTP-маршруты из кода и создаёт соответствующие узлы графа.

    Анализирует файлы проектов на наличие декораторов маршрутизации
    (Flask, FastAPI) и конфигураций URL (Django, Express, Next.js).
    """

    def __init__(
        self,
        graph: PropertyGraph,
        project_root: Optional[Path] = None,
        symbol_adapter: Optional[SymbolIndexAdapter] = None,
    ):
        self._graph = graph
        self._project_root = project_root or Path.cwd()
        self._symbol_adapter = symbol_adapter

    def extract_from_file(
        self,
        file_path: Path,
        content: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Извлекает маршруты из одного файла.

        Args:
            file_path: Путь к файлу
            content: Содержимое файла (если None — читает с диска)

        Returns:
            Список словарей:
            [{
                "method": "GET" | "POST" | ...,
                "path": "/api/users",
                "handler": "get_users",
                "framework": "flask" | "fastapi" | "django" | "express" | "nextjs",
                "line": 42,
                "file": "src/api.py",
            }]
        """
        rel_path = self._rel_path(file_path)
        ext = file_path.suffix.lower()

        if content is None:
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                return []

        routes: List[Dict[str, Any]] = []

        # Выбираем детектор по расширению
        if ext == ".py":
            routes.extend(self._detect_flask(content, rel_path))
            routes.extend(self._detect_fastapi(content, rel_path))
            routes.extend(self._detect_django(content, rel_path))

        elif ext in (".js", ".jsx", ".ts", ".tsx"):
            routes.extend(self._detect_express(content, rel_path))
            routes.extend(self._detect_nextjs(content, rel_path))

        # Опционально: создаём узлы графа
        for route in routes:
            self._create_route_nodes(route)

        return routes

    def extract_from_project(
        self,
        project_path: Optional[Path] = None,
    ) -> List[Dict[str, Any]]:
        """Обходит проект и извлекает все маршруты.

        Args:
            project_path: Корень проекта (по умолчанию self._project_root)

        Returns:
            Список всех найденных маршрутов
        """
        root = project_path or self._project_root
        all_routes: List[Dict[str, Any]] = []
        extensions = {".py", ".js", ".jsx", ".ts", ".tsx"}

        for ext in extensions:
            for file_path in root.rglob(f"*{ext}"):
                # Пропускаем node_modules, .venv, __pycache__
                skip_parts = {
                    "node_modules", ".venv", "venv", "__pycache__",
                    ".git", "dist", "build", ".mypy_cache",
                }
                parts = set(file_path.relative_to(root).parts)
                if parts & skip_parts:
                    continue

                try:
                    routes = self.extract_from_file(file_path)
                    all_routes.extend(routes)
                except Exception as e:
                    logger.debug(f"Route extraction failed for {file_path}: {e}")

        logger.info(
            f"Route extraction: {len(all_routes)} routes in {root.name}"
        )
        return all_routes

    # ── Детекторы ────────────────────────────────────────

    def _detect_flask(
        self, content: str, rel_path: str
    ) -> List[Dict[str, Any]]:
        """Flask: @app.route('/path', methods=['GET'])"""
        routes = []
        for match in _FLASK_ROUTE.finditer(content):
            path = match.group(1)
            methods_str = match.group(2) or "GET"

            # Парсим методы
            methods = [m.strip().strip("'\"") for m in methods_str.split(",")] if methods_str else ["GET"]
            methods = [m.upper() for m in methods if m]

            # Пытаемся найти имя функции-обработчика (следующая def строка)
            handler = self._find_handler_after(content, match.end())

            for method in methods:
                routes.append({
                    "method": method,
                    "path": path,
                    "handler": handler,
                    "framework": "flask",
                    "line": content[:match.start()].count("\n") + 1,
                    "file": rel_path,
                })

        return routes

    def _detect_fastapi(
        self, content: str, rel_path: str
    ) -> List[Dict[str, Any]]:
        """FastAPI: @app.get('/path'), @router.post(...)"""
        routes = []
        for match in _FASTAPI_ROUTE.finditer(content):
            method = match.group(1).upper()
            path = match.group(2)
            handler = self._find_handler_after(content, match.end())

            routes.append({
                "method": method,
                "path": path,
                "handler": handler,
                "framework": "fastapi",
                "line": content[:match.start()].count("\n") + 1,
                "file": rel_path,
            })

        return routes

    def _detect_django(
        self, content: str, rel_path: str
    ) -> List[Dict[str, Any]]:
        """Django: path('url/', view_func) или include(...)"""
        routes = []
        prefix = self._detect_url_prefix(content, rel_path)

        for match in _DJANGO_PATH.finditer(content):
            raw_path = match.group(1)
            handler = match.group(2)

            # Полный путь с учётом префикса
            full_path = urljoin(prefix, raw_path) if prefix else raw_path

            # Django по умолчанию назначает GET (и HEAD, POST для view)
            routes.append({
                "method": "ANY",
                "path": full_path,
                "handler": handler,
                "framework": "django",
                "line": content[:match.start()].count("\n") + 1,
                "file": rel_path,
            })

        return routes

    def _detect_express(
        self, content: str, rel_path: str
    ) -> List[Dict[str, Any]]:
        """Express: app.get('/path', handler), router.post(...)"""
        routes = []
        for match in _EXPRESS_ROUTE.finditer(content):
            method = match.group(1).upper()
            path = match.group(2)

            # Пытаемся найти имя handler (второй аргумент)
            handler = self._find_handler_in_args(content, match.end())

            routes.append({
                "method": method if method != "ALL" else "ANY",
                "path": path,
                "handler": handler,
                "framework": "express",
                "line": content[:match.start()].count("\n") + 1,
                "file": rel_path,
            })

        return routes

    def _detect_nextjs(
        self, content: str, rel_path: str
    ) -> List[Dict[str, Any]]:
        """Next.js: export async function GET(req) / route.ts"""
        routes = []
        is_route_handler = "route." in rel_path or "api/" in rel_path or "pages/" in rel_path

        if not is_route_handler:
            return routes

        # Извлекаем путь из файловой структуры
        path_from_file = self._nextjs_path_from_file(rel_path)

        for match in _NEXTJS_API.finditer(content):
            method = match.group(1).upper()

            routes.append({
                "method": method,
                "path": path_from_file,
                "handler": method,  # handler = HTTP метод
                "framework": "nextjs",
                "line": content[:match.start()].count("\n") + 1,
                "file": rel_path,
            })

        return routes

    # ── Хелперы ──────────────────────────────────────────

    def _find_handler_after(self, content: str, pos: int) -> str:
        """Ищет определение функции (def handler) после позиции."""
        after = content[pos:]
        match = re.search(r'def\s+(\w+)\s*\(', after)
        if match:
            return match.group(1)
        # Async вариант
        match = re.search(r'async\s+def\s+(\w+)\s*\(', after)
        if match:
            return match.group(1)
        return ""

    def _find_handler_in_args(self, content: str, pos: int) -> str:
        """Ищет имя обработчика в аргументах вызова (Express)."""
        after = content[pos:]
        # Ищем identifier, не начинающийся с / и не 'require'
        match = re.search(r',\s*(\w+)\s*[,)]', after)
        if match:
            name = match.group(1)
            if name not in ("require", "import", "router"):
                return name
        return ""

    def _detect_url_prefix(self, content: str, rel_path: str) -> str:
        """Определяет URL-префикс для Django urls.py."""
        # Ищем urlpatterns = [path('prefix/', include(...))]
        match = _DJANGO_INCLUDE.search(content)
        if match:
            return match.group(1)
        return ""

    def _nextjs_path_from_file(self, rel_path: str) -> str:
        """Извлекает URL-путь из файловой структуры Next.js.

        Примеры:
            app/api/users/route.ts -> /api/users
            app/users/page.tsx -> /users
            pages/api/auth.ts -> /api/auth
        """
        path = Path(rel_path)
        parts = list(path.parts)

        # Убираем app/ или pages/ в начале
        while parts and parts[0] in ("app", "pages", "src"):
            parts.pop(0)

        # Убираем route.ts, page.tsx, api/route.ts
        filtered = []
        for p in parts:
            if p in ("route.ts", "route.js", "page.tsx", "page.js", "layout.tsx", "loading.tsx"):
                break
            # Динамические сегменты [id] -> :id
            p = re.sub(r'\[(\w+)\]', r':\1', p)
            filtered.append(p)

        if not filtered:
            return "/"

        path_str = "/" + "/".join(filtered)
        return path_str or "/"

    def _rel_path(self, file_path: Path) -> str:
        """Относительный путь от корня проекта."""
        try:
            return str(file_path.relative_to(self._project_root).as_posix())
        except ValueError:
            return str(file_path.as_posix())

    # ── Создание узлов графа ─────────────────────────────

    def _create_route_nodes(self, route: Dict[str, Any]) -> None:
        """Создаёт Route node + HANDLES edge в PropertyGraph.

        Номенклатура:
            Route node qualified_name: "{project}.{file}.{method}:{path}"
            HANDLES edge: Route → Function (handler)
        """
        project_name = self._project_root.name
        method = route["method"]
        path = route["path"]
        handler = route["handler"]
        file_path = route["file"]
        framework = route["framework"]

        if not handler:
            return

        qualified_name = f"{project_name}.{file_path}.{method}:{path}"
        handler_qname = f"{project_name}.{file_path}.{handler}"

        # Route node
        self._graph.add_node(
            name=f"{method} {path}",
            label=NodeLabel.ROUTE,
            qualified_name=qualified_name,
            file_path=file_path,
            properties={
                "method": method,
                "path": path,
                "handler": handler,
                "framework": framework,
                "line": route.get("line", 0),
            },
        )

        # HANDLES edge: Route → Function
        # Убеждаемся что Function node существует
        if self._symbol_adapter and self._symbol_adapter.has_symbol(handler):
            self._graph.add_edge(
                source_qname=qualified_name,
                target_qname=handler_qname,
                type=EdgeType.HANDLES,
                weight=1.0,
                properties={
                    "framework": framework,
                    "method": method,
                    "path": path,
                },
            )

    def get_routes_summary(self) -> Dict[str, Any]:
        """Сводка по всем маршрутам в PropertyGraph."""
        routes = self._graph.find_nodes(label=NodeLabel.ROUTE, limit=5000)

        frameworks: Dict[str, int] = {}
        methods: Dict[str, int] = {}

        for route in routes:
            fw = route.properties.get("framework", "unknown")
            frameworks[fw] = frameworks.get(fw, 0) + 1
            m = route.properties.get("method", "ANY")
            methods[m] = methods.get(m, 0) + 1

        return {
            "total_routes": len(routes),
            "frameworks": dict(sorted(frameworks.items(), key=lambda x: -x[1])),
            "methods": dict(sorted(methods.items(), key=lambda x: -x[1])),
        }


__all__ = ["RouteExtractor"]
