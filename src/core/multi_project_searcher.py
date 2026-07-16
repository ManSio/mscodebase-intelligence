"""
MSCodebase Intelligence — Cross-repo поиск по нескольким проектам.

Поддерживает @-mention синтаксис: "query @project1 @project2"
Ищет по нескольким проектам одновременно и объединяет результаты через RRF.
"""

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import lancedb

from src.core.indexing.file_guard import FileGuard
from src.core.indexer import Indexer, _generate_unique_db_path

logger = logging.getLogger(__name__)
from src.utils.i18n import _

# Паттерн для извлечения @-mentions
_AT_MENTION_RE = re.compile(r"@([\w\-\.]+)")


def parse_cross_repo_query(query: str) -> Tuple[str, List[str]]:
    """Разбирает запрос с @-mentions на запрос и список проектов.

    Примеры:
        "auth @backend @frontend" → ("auth", ["backend", "frontend"])
        "database migration" → ("database migration", [])
        "@shared utils" → ("utils", ["shared"])

    Args:
        query: Запрос с возможными @-mentions

    Returns:
        Tuple из (чистый_запрос, список_проектов)
    """
    mentions = _AT_MENTION_RE.findall(query)
    # Убираем @-mentions из запроса
    clean_query = _AT_MENTION_RE.sub("", query).strip()
    # Нормализуем пробелы
    clean_query = re.sub(r"\s+", " ", clean_query)
    return clean_query, mentions


class ProjectRegistry:
    """Реестр проиндексированных проектов.

    Хранит информацию о проектах, которые были проиндексированы
    и доступны для cross-repo поиска.
    """

    def __init__(self):
        self._projects: Dict[str, Path] = {}  # name → path

    def register(self, project_path: Path) -> None:
        """Регистрирует проект в реестре."""
        name = project_path.name
        self._projects[name] = project_path
        logger.debug(f"📋 Проект зарегистрирован: {name} → {project_path}")

    def unregister(self, project_name: str) -> None:
        """Удаляет проект из реестра."""
        self._projects.pop(project_name, None)

    def get(self, project_name: str) -> Optional[Path]:
        """Возвращает путь к проекту по имени."""
        return self._projects.get(project_name)

    def find_by_prefix(self, prefix: str) -> List[Tuple[str, Path]]:
        """Находит проекты по префиксу имени (для частичных @-mentions).

        Args:
            prefix: Префикс имени проекта

        Returns:
            Список (name, path) для подходящих проектов
        """
        prefix_lower = prefix.lower()
        return [
            (name, path)
            for name, path in self._projects.items()
            if name.lower().startswith(prefix_lower)
        ]

    def list_projects(self) -> List[Tuple[str, Path]]:
        """Возвращает все зарегистрированные проекты."""
        return list(self._projects.items())

    @property
    def count(self) -> int:
        return len(self._projects)


class MultiProjectSearcher:
    """Поиск по нескольким проектам с объединением результатов через RRF.

    Использует существующие LanceDB базы каждого проекта,
    не требует дополнительной индексации.
    """

    def __init__(self, embedder, project_registry: Optional[ProjectRegistry] = None):
        self.embedder = embedder
        self.registry = project_registry or ProjectRegistry()
        self._db_cache: Dict[str, lancedb.LanceDB] = {}  # path_str → db connection

    def _get_project_table(self, project_path: Path):
        """Получает таблицу LanceDB для проекта (с кэшированием)."""
        db_path = _generate_unique_db_path(project_path)
        path_key = str(db_path)

        if path_key not in self._db_cache:
            raw_path = str(db_path.resolve())
            if raw_path.startswith("\\?\\"):
                raw_path = raw_path[4:]

            if not db_path.exists():
                return None

            try:
                db = lancedb.connect(raw_path)
                self._db_cache[path_key] = db
            except Exception as e:
                logger.warning(
                    f"Не удалось подключиться к БД проекта {project_path.name}: {e}"
                )
                return None

        db = self._db_cache[path_key]
        try:
            table = db.open_table("codebase_chunks")
            if len(table) == 0:
                return None
            return table
        except Exception:
            return None

    def _search_project(
        self, query_vector: List[float], project_path: Path, limit: int = 5
    ) -> List[dict]:
        """Выполняет векторный поиск в одном проекте."""
        table = self._get_project_table(project_path)
        if table is None:
            return []

        try:
            df = (
                table.search(query_vector, vector_column_name="vector")
                .limit(limit)
                .to_pandas()
            )
            results = []
            project_name = project_path.name
            for _, row in df.iterrows():
                results.append(
                    {
                        "text": row["text"],
                        "metadata": {
                            "file": row["file_path"],
                            "chunk_index": row["chunk_index"],
                            "project": project_name,
                        },
                        "score": float(row.get("_distance", 0.0)),
                    }
                )
            return results
        except Exception as e:
            logger.warning(f"Ошибка поиска в проекте {project_path.name}: {e}")
            return []

    def _merge_results_rrf(
        self,
        project_results: Dict[str, List[dict]],
        limit: int = 8,
        rrf_k: int = 60,
    ) -> List[dict]:
        """Объединяет результаты из нескольких проектов через RRF.

        Args:
            project_results: {project_name: [results]}
            limit: Максимальное число итоговых результатов
            rrf_k: Константа RRF
        """
        scores: Dict[str, float] = {}
        results_map: Dict[str, dict] = {}

        for project_name, results in project_results.items():
            for rank, result in enumerate(results, 1):
                key = (
                    f"{project_name}:"
                    f"{result['metadata']['file']}:"
                    f"{result['metadata']['chunk_index']}"
                )
                rrf_score = 1.0 / (rrf_k + rank)
                scores[key] = scores.get(key, 0.0) + rrf_score
                if key not in results_map:
                    results_map[key] = {
                        **result,
                        "rrf_score": rrf_score,
                        "source_projects": [project_name],
                    }
                else:
                    results_map[key]["rrf_score"] += rrf_score
                    results_map[key]["source_projects"].append(project_name)

        sorted_keys = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)[
            :limit
        ]

        return [results_map[k] for k in sorted_keys]

    def cross_repo_search(
        self,
        query: str,
        project_names: Optional[List[str]] = None,
        limit: int = 8,
    ) -> Tuple[List[dict], Dict[str, any]]:
        """Поиск по нескольким проектам.

        Args:
            query: Поисковый запрос
            project_names: Список имён проектов (если None — ищем по всем)
            limit: Максимальное число результатов

        Returns:
            Tuple из (results, metadata)
        """
        # Определяем проекты для поиска
        if project_names:
            projects_to_search = []
            for name in project_names:
                path = self.registry.get(name)
                if path:
                    projects_to_search.append((name, path))
                else:
                    # Пробуем найти по префиксу
                    matches = self.registry.find_by_prefix(name)
                    if matches:
                        projects_to_search.extend(matches)
                    else:
                        logger.warning(f"Проект '{name}' не найден в реестре")
        else:
            projects_to_search = self.registry.list_projects()

        if not projects_to_search:
            return [], {"error": "no_projects", "projects_searched": 0}

        # Эмбеддим запрос
        try:
            query_vector = self.embedder.embed(query)
            if not query_vector:
                return [], {"error": "embedder_unavailable", "projects_searched": 0}
        except Exception as e:
            return [], {"error": f"embed_error: {e}", "projects_searched": 0}

        # Ищем в каждом проекте
        project_results: Dict[str, List[dict]] = {}
        per_project_limit = max(limit, 5)

        for name, path in projects_to_search:
            results = self._search_project(query_vector, path, limit=per_project_limit)
            if results:
                project_results[name] = results
                logger.debug(f"  Проект {name}: {len(results)} результатов")

        if not project_results:
            return [], {
                "projects_searched": len(projects_to_search),
                "projects_with_results": 0,
            }

        # Объединяем через RRF
        merged = self._merge_results_rrf(project_results, limit=limit)

        metadata = {
            "projects_searched": len(projects_to_search),
            "projects_with_results": len(project_results),
            "projects_names": [name for name, _ in projects_to_search],
            "total_before_merge": sum(len(r) for r in project_results.values()),
            "total_after_merge": len(merged),
        }

        return merged, metadata

    def search(self, query: str, limit: int = 8) -> str:
        """Cross-repo поиск для MCP-инструмента.

        Поддерживает @-mention синтаксис: "query @project1 @project2"

        Args:
            query: Запрос с возможными @-mentions
            limit: Максимальное число результатов
        """
        # Разбираем @-mentions
        clean_query, project_names = parse_cross_repo_query(query)

        if not clean_query:
            return _("❌ Empty search query.")

        if self.registry.count == 0:
            return (
                "❌ Нет зарегистрированных проектов для cross-repo поиска. "
                "Используйте index_project_dir для индексации проектов."
            )

        results, metadata = self.cross_repo_search(
            clean_query,
            project_names=project_names if project_names else None,
            limit=limit,
        )

        if "error" in metadata:
            error = metadata["error"]
            if error == "no_projects":
                return _(
                    "❌ Specified projects not found: {project_names}",
                    project_names=", ".join(project_names),
                )
            elif error == "embedder_unavailable":
                return _("❌ Embedder unavailable. Cannot vectorize query.")
            else:
                return f"❌ Ошибка: {error}"

        if not results:
            return (
                f"🔍 По запросу '{clean_query}' ничего не найдено. "
                f"Проектов проверено: {metadata.get('projects_searched', 0)}."
            )

        # Формируем вывод
        output_lines = [
            f"🌐 Cross-repo Search: {len(results)} результатов из "
            f"{metadata['projects_with_results']} проектов\n"
        ]

        # Показываем какие проекты участвовали
        if metadata.get("projects_names"):
            output_lines.append(
                f"📂 Проекты: {', '.join(metadata['projects_names'])}\n"
            )

        for i, res in enumerate(results, 1):
            project = res["metadata"].get("project", "?")
            file_path = res["metadata"]["file"]
            chunk_idx = res["metadata"]["chunk_index"]
            score = res.get("rrf_score", 0.0)

            output_lines.append(
                f"{i}. 📄 [{project}] {file_path} [Чанк #{chunk_idx}] "
                f"(rrf={score:.4f})\n"
                f"```\n{res['text'][:500]}\n```\n"
                f"{'-' * 60}\n"
            )

        return "".join(output_lines)
