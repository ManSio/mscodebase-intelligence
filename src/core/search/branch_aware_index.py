"""
Branch-Aware Index — управление индексами для разных git-веток.

Каждая ветка имеет свой изолированный индекс LanceDB.
При смене ветки автоматически переключается база данных.
"""

import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

__all__ = [
    "BranchAwareIndex",
]
logger = logging.getLogger("branch_aware_index")


class BranchAwareIndex:
    """Управляет индексами для разных git-веток."""

    def __init__(self, project_path: Path):
        self.project_path = project_path.resolve()
        self._current_branch: Optional[str] = None
        self._branch_cache: Dict[str, Path] = {}  # branch -> db_path
        self._db_connections: Dict[str, Any] = {}  # branch -> lancedb connection (кэш)

    def get_current_branch(self) -> str:
        """Определяет текущую git-ветку."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=str(self.project_path),
            )
            if result.returncode == 0:
                branch = result.stdout.strip()
                self._current_branch = branch
                return branch
        except Exception as e:
            logger.debug(f"Git branch detection failed: {e}")

        return "main"  # Fallback

    def get_branch_db_path(self, branch: Optional[str] = None) -> Path:
        """Возвращает путь к БД для конкретной ветки."""
        if branch is None:
            branch = self.get_current_branch()

        if branch in self._branch_cache:
            return self._branch_cache[branch]

        # Создаём уникальный путь для ветки
        normalized = branch.replace("/", "_").replace("\\", "_")
        db_dir = self.project_path / ".codebase_indices" / "branches" / normalized
        db_dir.mkdir(parents=True, exist_ok=True)

        db_path = db_dir / "codebase_chunks.db"
        self._branch_cache[branch] = db_path

        return db_path

    def switch_branch(self, new_branch: str) -> bool:
        """Переключает индекс на другую ветку."""
        # Используем закэшированное значение если есть
        current = (
            self._current_branch if self._current_branch else self.get_current_branch()
        )

        if current == new_branch:
            logger.info(f"Already on branch: {new_branch}")
            return False

        logger.info(f"Switching index: {current} → {new_branch}")
        self._current_branch = new_branch

        # Очищаем кэш для новой ветки (будет пересоздана при необходимости)
        if new_branch in self._branch_cache:
            del self._branch_cache[new_branch]

        return True

    def get_branch_info(self) -> Dict:
        """Информация о текущей ветке и индексе (sync, с кэшированием)."""
        branch = self.get_current_branch()
        db_path = self.get_branch_db_path(branch)
        exists = db_path.exists()
        chunks = 0
        if exists:
            try:
                import lancedb

                if branch not in self._db_connections:
                    self._db_connections[branch] = lancedb.connect(str(db_path))
                db = self._db_connections[branch]
                try:
                    table = db.open_table("codebase_chunks")
                    chunks = table.count_rows()
                except Exception as _e:
                    logger.warning("exception", exc_info=True)
                    pass
            except Exception as _e:
                logger.warning("exception", exc_info=True)
                pass
        return {
            "branch": branch,
            "db_path": str(db_path),
            "index_exists": exists,
            "total_chunks": chunks,
        }

    async def get_branch_info_async(self) -> Dict:
        """Async версия — через connect_async (не блокирует event loop)."""
        branch = self.get_current_branch()
        db_path = self.get_branch_db_path(branch)
        exists = db_path.exists()
        chunks = 0
        if exists:
            try:
                import asyncio

                import lancedb

                async def _fetch():
                    db = await lancedb.connect_async(str(db_path))
                    table = await db.open_table("codebase_chunks")
                    count = await table.count_rows()
                    return count

                chunks = await asyncio.wait_for(_fetch(), timeout=10)
            except asyncio.TimeoutError:
                logger.warning(f"Branch info async timeout for {branch}")
            except Exception as e:
                logger.debug(f"Branch info async error: {e}")
        return {
            "branch": branch,
            "db_path": str(db_path),
            "index_exists": exists,
            "total_chunks": chunks,
        }

    def list_branch_indices(self) -> Dict[str, int]:
        """Список всех индексов для веток."""
        branches_dir = self.project_path / ".codebase_indices" / "branches"

        if not branches_dir.exists():
            return {}

        indices = {}
        for branch_dir in branches_dir.iterdir():
            if branch_dir.is_dir():
                db_path = branch_dir / "codebase_chunks.db"
                if db_path.exists():
                    branch_name = branch_dir.name
                    try:
                        import lancedb

                        if branch_name not in self._db_connections:
                            self._db_connections[branch_name] = lancedb.connect(
                                str(db_path)
                            )
                        db = self._db_connections[branch_name]
                        try:
                            table = db.open_table("codebase_chunks")
                            indices[branch_name] = table.count_rows()
                        except Exception:
                            indices[branch_name] = 0
                    except Exception:
                        indices[branch_name] = 0

        return indices

    def cleanup_old_branches(self, keep_branches: list) -> int:
        """Удаляет индексы для устаревших веток.

        Args:
            keep_branches: Список веток которые нужно сохранить

        Returns:
            Количество удалённых индексов
        """
        import shutil

        branches_dir = self.project_path / ".codebase_indices" / "branches"
        if not branches_dir.exists():
            return 0

        removed = 0
        normalized_keep = {
            b.replace("/", "_").replace("\\", "_") for b in keep_branches
        }

        for branch_dir in branches_dir.iterdir():
            if branch_dir.is_dir() and branch_dir.name not in normalized_keep:
                try:
                    shutil.rmtree(branch_dir)
                    removed += 1
                    logger.info(f"Removed old branch index: {branch_dir.name}")
                except Exception as e:
                    logger.warning(f"Failed to remove {branch_dir}: {e}")

        return removed
