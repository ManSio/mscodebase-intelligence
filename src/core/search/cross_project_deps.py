"""
MSCodebase Intelligence — Cross-project dependency graph analyzer.

Строит граф зависимостей между проектами в моно-репо:
- Сканирует import/from между проектами
- Находит циклические зависимости
- Определяет общие интерфейсы
- Анализирует влияние изменений на другие проекты
"""

import ast
import logging
from collections import defaultdict, deque
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from src.core.multi_project_searcher import ProjectRegistry

__all__ = [
    "CrossProjectDependencyGraph",
    "get_cross_project_deps",
]
logger = logging.getLogger("cross_project_deps")

# Расширения файлов, которые сканируем на импорты
_PYTHON_EXTENSIONS = {".py"}
_JAVASCRIPT_EXTENSIONS = {".js", ".ts", ".jsx", ".tsx"}
_JAVA_EXTENSIONS = {".java", ".kt"}
_GO_EXTENSIONS = {".go"}
_RUST_EXTENSIONS = {".rs"}

_ALL_EXTENSIONS = (
    _PYTHON_EXTENSIONS
    | _JAVASCRIPT_EXTENSIONS
    | _JAVA_EXTENSIONS
    | _GO_EXTENSIONS
    | _RUST_EXTENSIONS
)


class CrossProjectDependencyGraph:
    """Граф зависимостей между проектами в моно-репо.

    Строит directed graph: project → [зависимые_проекты]
    на основе анализа import-выражений в исходном коде.
    """

    def __init__(self, project_registry: Optional[ProjectRegistry] = None):
        self.project_registry = project_registry
        self.registry = project_registry
        self._graph: Optional[Dict[str, Set[str]]] = None  # built lazily
        self._adjacency: Dict[str, Set[str]] = defaultdict(set)  # project → {зависимые}
        self._reverse_graph: Dict[str, Set[str]] = defaultdict(set)  # project → {зависимые_от}
        self._edge_imports: Dict[Tuple[str, str], List[str]] = defaultdict(list)  # (src, dst) → [imports]
        self._project_symbols: Dict[str, Set[str]] = {}  # project → {symbol_names}
        self._symbol_projects: Dict[str, Set[str]] = defaultdict(set)  # symbol → {projects}
        self._built = False

    def build_dependency_graph(self) -> Dict:
        """Строит граф зависимостей между проектами.

        Сканирует каждый проект на предмет import/from других проектов,
        строит directed graph и собирает статистику.

        Returns:
            Dict с ключами:
                - nodes: [{name, path, type}]
                - edges: [{source, target, imports, weight}]
                - stats: {total_projects, total_edges, cycles_count, shared_symbols_count}
        """
        self._adjacency.clear()
        self._reverse_graph.clear()
        self._edge_imports.clear()
        self._project_symbols.clear()
        self._symbol_projects.clear()

        if not self.registry:
            logger.info("Нет реестра проектов для анализа зависимостей")
            return {
                "nodes": [],
                "edges": [],
                "stats": {
                    "total_projects": 0,
                    "total_edges": 0,
                    "cycles_count": 0,
                    "shared_symbols_count": 0,
                },
            }

        projects = self.registry.list_projects()
        if not projects:
            logger.info("Нет зарегистрированных проектов для анализа зависимостей")
            return {
                "nodes": [],
                "edges": [],
                "stats": {
                    "total_projects": 0,
                    "total_edges": 0,
                    "cycles_count": 0,
                    "shared_symbols_count": 0,
                },
            }

        project_names = {name for name, _ in projects}
        logger.info(f"Сканирование зависимостей для {len(projects)} проектов")

        # Сканируем импорты каждого проекта
        project_imports: Dict[str, Dict[str, List[str]]] = {}
        for name, path in projects:
            try:
                imports = self._scan_imports(path)
                project_imports[name] = imports
                logger.debug(f"Проект {name}: найдено {sum(len(v) for v in imports.values())} кросс-импортов")
            except Exception as e:
                logger.error(f"Ошибка сканирования проекта {name}: {e}")
                project_imports[name] = {}

        # Строим граф
        for source_project, imports_by_target in project_imports.items():
            for target_project, imports in imports_by_target.items():
                if target_project in project_names and target_project != source_project:
                    self._adjacency[source_project].add(target_project)
                    self._reverse_graph[target_project].add(source_project)
                    key = (source_project, target_project)
                    self._edge_imports[key].extend(imports)

        # Собираем символы для поиска shared interfaces
        self._collect_project_symbols(projects)

        # Формируем результат
        nodes = []
        for name, path in projects:
            project_type = self._detect_project_type(path)
            nodes.append({
                "name": name,
                "path": str(path),
                "type": project_type,
            })

        edges = []
        for (source, target), imports in self._edge_imports.items():
            edges.append({
                "source": source,
                "target": target,
                "imports": list(set(imports)),
                "weight": len(set(imports)),
            })

        cycles = self._find_cycles_internal()
        shared = self._find_shared_internal()

        stats = {
            "total_projects": len(projects),
            "total_edges": len(edges),
            "cycles_count": len(cycles),
            "shared_symbols_count": len(shared),
        }

        self._built = True
        logger.info(
            f"Граф зависимостей построен: {stats['total_projects']} проектов, "
            f"{stats['total_edges']} рёбер, {stats['cycles_count']} циклов"
        )

        return {
            "nodes": nodes,
            "edges": edges,
            "stats": stats,
        }

    def get_project_dependencies(
        self, project_name: str, direction: str = "both"
    ) -> Dict:
        """Возвращает зависимости конкретного проекта.

        Args:
            project_name: Имя проекта
            direction: "down" (зависит от), "up" (зависимые), "both"

        Returns:
            Dict с ключами:
                - project: имя проекта
                - depends_on: [проекты от которых зависит]
                - depended_by: [проекты которые зависят от него]
                - shared_symbols: [{symbol, projects}]
        """
        if not self._built:
            self.build_dependency_graph()

        result = {
            "project": project_name,
            "depends_on": [],
            "depended_by": [],
            "shared_symbols": [],
        }

        if direction in ("down", "both"):
            result["depends_on"] = sorted(self._adjacency.get(project_name, set()))

        if direction in ("up", "both"):
            result["depended_by"] = sorted(self._reverse_graph.get(project_name, set()))

        # Находим общие символы с зависимыми проектами
        related_projects = set(result["depends_on"]) | set(result["depended_by"])
        if project_name in self._project_symbols:
            project_syms = self._project_symbols[project_name]
            for symbol, sym_projects in self._symbol_projects.items():
                if symbol in project_syms and len(sym_projects) > 1:
                    other_projects = sym_projects - {project_name}
                    if other_projects & related_projects:
                        result["shared_symbols"].append({
                            "symbol": symbol,
                            "projects": sorted(sym_projects),
                        })

        return result

    def _find_shared_internal(self) -> List[Dict]:
        """Внутренняя версия find_shared_interfaces без lazy build."""
        shared = []
        for symbol, projects in self._symbol_projects.items():
            if len(projects) > 1:
                potential_conflict = self._check_symbol_conflict(symbol, projects)
                shared.append({
                    "symbol": symbol,
                    "projects": sorted(projects),
                    "potential_conflict": potential_conflict,
                })
        shared.sort(key=lambda x: (-len(x["projects"]), x["symbol"]))
        return shared

    def _find_cycles_internal(self) -> List[List[str]]:
        """Внутренняя версия find_circular_dependencies без lazy build."""
        cycles = []
        visited: Set[str] = set()
        for project in set(self._adjacency.keys()) | set(self._reverse_graph.keys()):
            if project not in visited:
                path: List[str] = []
                self._find_cycles_dfs(self._adjacency, project, visited, path, cycles)
        unique_cycles = self._deduplicate_cycles(cycles)
        return unique_cycles

    def find_shared_interfaces(self) -> List[Dict]:
        """Находит общие интерфейсы между проектами.

        Символы/классы, которые определены в нескольких проектах.

        Returns:
            List[{symbol, projects: [], potential_conflict: bool}]
        """
        if not self._built:
            self.build_dependency_graph()

        shared = []
        for symbol, projects in self._symbol_projects.items():
            if len(projects) > 1:
                # Потенциальный конфликт если символ импортируется из нескольких проектов
                potential_conflict = self._check_symbol_conflict(symbol, projects)
                shared.append({
                    "symbol": symbol,
                    "projects": sorted(projects),
                    "potential_conflict": potential_conflict,
                })

        # Сортируем по количеству проектов (наиболее конфликтные первыми)
        shared.sort(key=lambda x: (-len(x["projects"]), x["symbol"]))
        return shared

    def find_circular_dependencies(self) -> List[List[str]]:
        """Находит циклические зависимости между проектами.

        Returns:
            Список циклов: [["backend", "shared", "backend"]]
        """
        if not self._built:
            self.build_dependency_graph()

        cycles = []
        visited: Set[str] = set()

        for project in set(self._adjacency.keys()) | set(self._reverse_graph.keys()):
            if project not in visited:
                path: List[str] = []
                self._find_cycles_dfs(self._adjacency, project, visited, path, cycles)

        # Дедупликация циклов (нормализуем начало цикла)
        unique_cycles = self._deduplicate_cycles(cycles)
        return unique_cycles

    def get_dependency_path(
        self, from_project: str, to_project: str
    ) -> List[str]:
        """Находит кратчайший путь зависимости между проектами.

        Использует BFS для поиска кратчайшего пути.

        Args:
            from_project: Начальный проект
            to_project: Целевой проект

        Returns:
            Список проектов-пути или пустой список если путь не найден
        """
        if not self._built:
            self.build_dependency_graph()

        if from_project == to_project:
            return [from_project]

        # BFS
        queue: deque[Tuple[str, List[str]]] = deque([(from_project, [from_project])])
        visited: Set[str] = {from_project}

        while queue:
            current, path = queue.popleft()
            for neighbor in self._adjacency.get(current, set()):
                if neighbor == to_project:
                    return path + [neighbor]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))

        return []

    def analyze_impact(self, project_name: str) -> Dict:
        """Анализирует влияние изменений в проекте на другие.

        Args:
            project_name: Имя проекта

        Returns:
            Dict с ключами:
                - project: имя проекта
                - directly_affected: [непосредственно зависимые проекты]
                - transitively_affected: [транзитивно зависимые проекты]
                - risk_level: "low" | "medium" | "high" | "critical"
        """
        if not self._built:
            self.build_dependency_graph()

        directly_affected = list(self._reverse_graph.get(project_name, set()))

        # Транзитивно затронутые — BFS от directly_affected
        transitively_affected: Set[str] = set()
        queue: deque[str] = deque(directly_affected)
        visited: Set[str] = {project_name} | set(directly_affected)

        while queue:
            current = queue.popleft()
            for dependent in self._reverse_graph.get(current, set()):
                if dependent not in visited:
                    visited.add(dependent)
                    transitively_affected.add(dependent)
                    queue.append(dependent)

        # Определяем уровень риска
        total_affected = len(directly_affected) + len(transitively_affected)
        total_projects = self.registry.count if self.registry else 0

        if total_projects <= 1:
            risk_level = "low"
        elif total_affected == 0:
            risk_level = "low"
        elif total_affected <= total_projects * 0.25:
            risk_level = "medium"
        elif total_affected <= total_projects * 0.5:
            risk_level = "high"
        else:
            risk_level = "critical"

        return {
            "project": project_name,
            "directly_affected": sorted(directly_affected),
            "transitively_affected": sorted(transitively_affected),
            "risk_level": risk_level,
        }

    def _scan_imports(self, project_path: Path) -> Dict[str, List[str]]:
        """Сканирует импорты проекта, определяя ссылки на другие проекты.

        Args:
            project_path: Путь к проекту

        Returns:
            Dict: {имя_зависимого_проекта: [список_импортов]}
        """
        project_names = {name for name, _ in self.registry.list_projects()} if self.registry else set()
        imports_by_project: Dict[str, List[str]] = defaultdict(list)

        # Собираем все файлы проекта
        source_files = self._collect_source_files(project_path)

        for file_path in source_files:
            try:
                file_imports = self._extract_imports_from_file(file_path, project_path)
                referenced_projects = self._detect_project_references(
                    file_imports, project_names
                )
                for ref_project in referenced_projects:
                    imports_by_project[ref_project].extend(file_imports)
            except Exception as e:
                logger.debug(f"Ошибка анализа импортов в {file_path}: {e}")

        return dict(imports_by_project)

    def _extract_imports_from_file(
        self, file_path: Path, project_path: Path
    ) -> List[str]:
        """Извлекает импорты из одного файла.

        Поддерживает Python, JavaScript/TypeScript, Java, Go, Rust.

        Args:
            file_path: Путь к файлу
            project_path: Путь к корню проекта

        Returns:
            Список строк импортов
        """
        suffix = file_path.suffix.lower()

        if suffix in _PYTHON_EXTENSIONS:
            return self._extract_python_imports(file_path)
        elif suffix in _JAVASCRIPT_EXTENSIONS:
            return self._extract_js_imports(file_path)
        elif suffix in _JAVA_EXTENSIONS:
            return self._extract_java_imports(file_path)
        elif suffix in _GO_EXTENSIONS:
            return self._extract_go_imports(file_path)
        elif suffix in _RUST_EXTENSIONS:
            return self._extract_rust_imports(file_path)

        return []

    def _extract_python_imports(self, file_path: Path) -> List[str]:
        """Извлекает Python импорты через AST."""
        imports = []
        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(file_path))

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    names = [alias.name for alias in node.names]
                    if names:
                        imports.extend([f"{module}.{name}" for name in names])
                    else:
                        imports.append(module)
        except (SyntaxError, UnicodeDecodeError) as e:
            logger.debug(f"Не удалось распарсить Python файл {file_path}: {e}")

        return imports

    def _extract_js_imports(self, file_path: Path) -> List[str]:
        """Извлекает JavaScript/TypeScript импорты через regex."""
        import re

        imports = []
        # Паттерны для import/require
        patterns = [
            r"""import\s+(?:[\w*{}\s,]+)\s+from\s+['"]([^'"]+)['"]""",
            r"""import\s+['"]([^'"]+)['"]""",
            r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""",
            r"""from\s+['"]([^'"]+)['"]""",
        ]

        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
            for pattern in patterns:
                matches = re.findall(pattern, source)
                imports.extend(matches)
        except UnicodeDecodeError as e:
            logger.debug(f"Не удалось прочитать JS файл {file_path}: {e}")

        return imports

    def _extract_java_imports(self, file_path: Path) -> List[str]:
        """Извлекает Java/Kotlin импорты через regex."""
        import re

        imports = []
        pattern = r"^\s*import\s+(?:static\s+)?([\w.]+)\s*;"

        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
            for line in source.splitlines():
                match = re.match(pattern, line)
                if match:
                    imports.append(match.group(1))
        except UnicodeDecodeError as e:
            logger.debug(f"Не удалось прочитать Java файл {file_path}: {e}")

        return imports

    def _extract_go_imports(self, file_path: Path) -> List[str]:
        """Извлекает Go импорты через regex."""
        import re

        imports = []
        pattern = r"""^\s*import\s+(?:\(\s*)?["']([^"']+)["']"""

        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
            for line in source.splitlines():
                match = re.match(pattern, line)
                if match:
                    imports.append(match.group(1))
        except UnicodeDecodeError as e:
            logger.debug(f"Не удалось прочитать Go файл {file_path}: {e}")

        return imports

    def _extract_rust_imports(self, file_path: Path) -> List[str]:
        """Извлекает Rust импорты через regex."""
        import re

        imports = []
        pattern = r"^\s*use\s+([\w:]+)"

        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
            for line in source.splitlines():
                match = re.match(pattern, line)
                if match:
                    imports.append(match.group(1))
        except UnicodeDecodeError as e:
            logger.debug(f"Не удалось прочитать Rust файл {file_path}: {e}")

        return imports

    def _detect_project_references(
        self, imports: List[str], project_names: Set[str]
    ) -> Set[str]:
        """Определяет какие импорты ссылаются на другие проекты.

        Args:
            imports: Список строк импортов
            project_names: Множество имён проектов

        Returns:
            Множество имён проектов на которые есть ссылки
        """
        referenced: Set[str] = set()

        for imp in imports:
            # Нормализуем импорт: убираем расширения, заменяем / на .
            normalized = imp.replace("/", ".").replace("\\", ".")

            # Проверяем точное совпадение или префикс
            for project_name in project_names:
                if normalized == project_name:
                    referenced.add(project_name)
                elif normalized.startswith(project_name + "."):
                    referenced.add(project_name)
                elif normalized.startswith(project_name + "/"):
                    referenced.add(project_name)

        return referenced

    def _find_cycles_dfs(
        self,
        graph: Dict[str, Set[str]],
        start: str,
        visited: Set[str],
        path: List[str],
        cycles: List[List[str]],
    ) -> None:
        """DFS для поиска циклических зависимостей.

        Args:
            graph: Граф зависимостей
            start: Текущая вершина
            visited: Посещённые вершины
            path: Текущий путь
            cycles: Найденные циклы (мутируемый список)
        """
        visited.add(start)
        path.append(start)

        for neighbor in graph.get(start, set()):
            if neighbor in path:
                # Нашли цикл — извлекаем его из пути
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:] + [neighbor]
                cycles.append(cycle)
            elif neighbor not in visited:
                self._find_cycles_dfs(graph, neighbor, visited, path, cycles)

        path.pop()

    def _collect_project_symbols(
        self, projects: List[Tuple[str, Path]]
    ) -> None:
        """Собирает символы (классы, функции) из всех проектов.

        Args:
            projects: Список (name, path) проектов
        """
        for name, path in projects:
            symbols: Set[str] = set()
            source_files = self._collect_source_files(path)

            for file_path in source_files:
                try:
                    file_symbols = self._extract_symbols_from_file(file_path)
                    symbols.update(file_symbols)
                except Exception as e:
                    logger.debug(f"Ошибка извлечения символов из {file_path}: {e}")

            self._project_symbols[name] = symbols
            for symbol in symbols:
                self._symbol_projects[symbol].add(name)

    def _extract_symbols_from_file(self, file_path: Path) -> Set[str]:
        """Извлекает имена классов и функций из файла.

        Args:
            file_path: Путь к файлу

        Returns:
            Множество имён символов
        """
        suffix = file_path.suffix.lower()

        if suffix in _PYTHON_EXTENSIONS:
            return self._extract_python_symbols(file_path)
        elif suffix in _JAVASCRIPT_EXTENSIONS:
            return self._extract_js_symbols(file_path)
        elif suffix in _JAVA_EXTENSIONS:
            return self._extract_java_symbols(file_path)

        return set()

    def _extract_python_symbols(self, file_path: Path) -> Set[str]:
        """Извлекает Python символы через AST."""
        symbols = set()
        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(file_path))

            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    symbols.add(node.name)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.add(node.name)
        except (SyntaxError, UnicodeDecodeError):
            pass

        return symbols

    def _extract_js_symbols(self, file_path: Path) -> Set[str]:
        """Извлекает JavaScript/TypeScript символы через regex."""
        import re

        symbols = set()
        patterns = [
            r"(?:^|\s)class\s+(\w+)",
            r"(?:^|\s)function\s+(\w+)",
            r"(?:^|\s)(?:const|let|var)\s+(\w+)\s*=\s*(?:\(|function)",
            r"(?:^|\s)interface\s+(\w+)",
            r"(?:^|\s)type\s+(\w+)\s*=",
        ]

        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
            for pattern in patterns:
                matches = re.findall(pattern, source, re.MULTILINE)
                symbols.update(matches)
        except UnicodeDecodeError:
            pass

        return symbols

    def _extract_java_symbols(self, file_path: Path) -> Set[str]:
        """Извлекает Java/Kotlin символы через regex."""
        import re

        symbols = set()
        patterns = [
            r"(?:^|\s)class\s+(\w+)",
            r"(?:^|\s)interface\s+(\w+)",
            r"(?:^|\s)enum\s+(\w+)",
        ]

        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
            for pattern in patterns:
                matches = re.findall(pattern, source, re.MULTILINE)
                symbols.update(matches)
        except UnicodeDecodeError:
            pass

        return symbols

    def _collect_source_files(self, project_path: Path) -> List[Path]:
        """Собирает исходные файлы проекта, исключая типичные директории.

        Args:
            project_path: Путь к проекту

        Returns:
            Список путей к исходным файлам
        """
        exclude_dirs = {
            "node_modules",
            ".git",
            "__pycache__",
            "venv",
            ".venv",
            "dist",
            "build",
            ".tox",
            ".eggs",
            "target",
            "vendor",
            ".next",
            "out",
        }
        max_depth = 10  # Защита от symlink-циклов

        source_files: List[Path] = []

        try:
            import os
            root = str(project_path)
            for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
                # Убираем excluded директории из обхода
                dirnames[:] = [
                    d for d in dirnames
                    if d not in exclude_dirs and not d.startswith(".")
                ]
                # Защита от глубокой рекурсии
                rel_depth = dirpath[len(root):].count(os.sep)
                if rel_depth > max_depth:
                    dirnames.clear()
                    continue
                for fname in filenames:
                    ext = os.path.splitext(fname)[1].lower()
                    if ext not in _ALL_EXTENSIONS:
                        continue
                    source_files.append(Path(dirpath) / fname)
        except (PermissionError, OSError) as e:
            logger.warning(f"Нет доступа к файлам проекта {project_path}: {e}")

        return source_files

    def _detect_project_type(self, project_path: Path) -> str:
        """Определяет тип проекта по характерным файлам.

        Args:
            project_path: Путь к проекту

        Returns:
            Тип проекта: "python", "javascript", "typescript", "java", "go", "rust", "unknown"
        """
        if (project_path / "pyproject.toml").exists() or (project_path / "setup.py").exists():
            return "python"
        if (project_path / "requirements.txt").exists():
            return "python"
        if (project_path / "package.json").exists():
            if (project_path / "tsconfig.json").exists():
                return "typescript"
            return "javascript"
        if (project_path / "pom.xml").exists() or (project_path / "build.gradle").exists():
            return "java"
        if (project_path / "go.mod").exists():
            return "go"
        if (project_path / "Cargo.toml").exists():
            return "rust"

        return "unknown"

    def _check_symbol_conflict(
        self, symbol: str, projects: Set[str]
    ) -> bool:
        """Проверяет является ли символ потенциальным конфликтом.

        Конфликт если символ импортируется из нескольких проектов
        и при этом проекты связаны зависимостями.

        Args:
            symbol: Имя символа
            projects: Проекты в которых определён символ

        Returns:
            True если потенциальный конфликт
        """
        # Проверяем есть ли зависимости между проектами с общим символом
        for project in projects:
            dependents = self._reverse_graph.get(project, set())
            if dependents & (projects - {project}):
                return True
        return False

    def _deduplicate_cycles(self, cycles: List[List[str]]) -> List[List[str]]:
        """Дедуплицирует циклы, нормализуя начальную точку.

        Args:
            cycles: Список найденных циклов

        Returns:
            Дедуплицированный список циклов
        """
        seen: Set[Tuple[str, ...]] = set()
        unique: List[List[str]] = []

        for cycle in cycles:
            # Убираем последний элемент (дублирует первый)
            normalized = cycle[:-1]
            if not normalized:
                continue

            # Находим минимальный элемент для нормализации начала
            min_idx = normalized.index(min(normalized))
            rotated = tuple(normalized[min_idx:] + normalized[:min_idx])

            if rotated not in seen:
                seen.add(rotated)
                unique.append(list(rotated) + [rotated[0]])

        return unique

    def format_dependency_graph(self, graph: Dict) -> str:
        """Форматирует граф зависимостей в текстовое представление.

        Args:
            graph: Результат build_dependency_graph()

        Returns:
            Текстовое представление графа
        """
        lines = [
            "📊 Cross-Project Dependency Graph",
            "=" * 50,
            "",
        ]

        stats = graph.get("stats", {})
        lines.append(f"Проектов: {stats.get('total_projects', 0)}")
        lines.append(f"Рёбер: {stats.get('total_edges', 0)}")
        lines.append(f"Циклов: {stats.get('cycles_count', 0)}")
        lines.append(f"Общих символов: {stats.get('shared_symbols_count', 0)}")
        lines.append("")

        # Узлы
        nodes = graph.get("nodes", [])
        if nodes:
            lines.append("📂 Проекты:")
            for node in nodes:
                lines.append(f"  • {node['name']} ({node['type']}) — {node['path']}")
            lines.append("")

        # Рёбра
        edges = graph.get("edges", [])
        if edges:
            lines.append("🔗 Зависимости:")
            for edge in edges:
                imports_preview = ", ".join(edge["imports"][:3])
                if len(edge["imports"]) > 3:
                    imports_preview += f" (+{len(edge['imports']) - 3})"
                lines.append(
                    f"  {edge['source']} → {edge['target']} "
                    f"(weight={edge['weight']}) [{imports_preview}]"
                )
            lines.append("")

        return "\n".join(lines)

    def format_project_deps(self, deps: Dict) -> str:
        """Форматирует зависимости проекта в текстовое представление.

        Args:
            deps: Результат get_project_dependencies()

        Returns:
            Текстовое представление зависимостей
        """
        lines = [
            f"📦 Зависимости проекта: {deps['project']}",
            "=" * 50,
            "",
        ]

        depends_on = deps.get("depends_on", [])
        if depends_on:
            lines.append("⬇️  Зависит от:")
            for dep in depends_on:
                lines.append(f"  • {dep}")
            lines.append("")

        depended_by = deps.get("depended_by", [])
        if depended_by:
            lines.append("⬆️  Зависимые проекты:")
            for dep in depended_by:
                lines.append(f"  • {dep}")
            lines.append("")

        shared = deps.get("shared_symbols", [])
        if shared:
            lines.append("🔄 Общие символы:")
            for item in shared[:10]:
                projects_str = ", ".join(item["projects"])
                lines.append(f"  • {item['symbol']} — [{projects_str}]")
            if len(shared) > 10:
                lines.append(f"  ... и ещё {len(shared) - 10}")
            lines.append("")

        if not depends_on and not depended_by:
            lines.append("  (нет зависимостей от других проектов)")
            lines.append("")

        return "\n".join(lines)


def get_cross_project_deps(
    project_registry: Optional[ProjectRegistry] = None,
) -> CrossProjectDependencyGraph:
    """Фабричная функция для создания CrossProjectDependencyGraph.

    Args:
        project_registry: Реестр проектов (если None — создаётся новый)

    Returns:
        Экземпляр CrossProjectDependencyGraph
    """
    if project_registry is None:
        project_registry = ProjectRegistry()
    return CrossProjectDependencyGraph(project_registry)
