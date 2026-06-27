"""
Content cache for efficient change detection and file tracking.
Replaces Merkle Tree with a simple, performant SHA-256 content cache.
"""

import hashlib
import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class ContentCache:
    """Simple SHA-256 content cache for efficient change detection."""

    def __init__(self, project_path: Path, cache_db_path: Optional[Path] = None):
        self.project_path = project_path
        self.cache_db_path = (
            cache_db_path or project_path / ".codebase_index" / "cache.db"
        )
        self._init_database()

    def _init_database(self):
        """Initialize SQLite database for content cache."""
        os.makedirs(self.cache_db_path.parent, exist_ok=True)

        with sqlite3.connect(self.cache_db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS file_cache (
                    file_path TEXT PRIMARY KEY,
                    file_hash TEXT NOT NULL,
                    last_modified INTEGER NOT NULL,
                    content_size INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_file_hash ON file_cache(file_hash)"
            )
            conn.commit()

    def _normalize_path(self, file_path: Path) -> str:
        """Normalize path for consistent comparison across platforms."""
        try:
            rel_path = file_path.relative_to(self.project_path)
            return rel_path.as_posix().lower()
        except ValueError:
            # File is not part of the project
            return file_path.as_posix().lower()

    def _get_file_hash(self, file_path: Path) -> str:
        """Calculate SHA-256 hash of file content."""
        try:
            hasher = hashlib.sha256()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except (FileNotFoundError, OSError) as e:
            logger.warning(f"⚠️ Could not hash file {file_path}: {e}")
            return hashlib.sha256(b"").hexdigest()

    def _get_file_mtime(self, file_path: Path) -> int:
        """Get file modification time as integer timestamp."""
        try:
            return int(os.path.getmtime(file_path))
        except OSError:
            return 0

    def build_cache(self, gitignore_patterns: Set[str] = None) -> str:
        """Build content cache for the project.

        Args:
            gitignore_patterns: Set of .gitignore patterns to exclude files

        Returns:
            Root hash of the cache (combined hash of all file hashes)
        """
        logger.info(f"🔄 Building content cache for: {self.project_path}")

        # Get all files to process
        files_to_process = self._get_all_files(gitignore_patterns)

        # Update cache and get root hash
        root_hash = self._update_cache(files_to_process)

        logger.info(f"✅ Content cache built. Root hash: {root_hash[:16]}...")
        return root_hash

    def _get_all_files(self, gitignore_patterns: Set[str] = None) -> List[Path]:
        """Get all files to process, applying gitignore patterns."""
        files = []

        # Skip ignored directories
        ignore_dirs = {
            ".git",
            "node_modules",
            "venv",
            ".venv",
            "__pycache__",
            "dist",
            "build",
            "target",
            ".tox",
            ".mypy_cache",
            ".ruff_cache",
            ".pytest_cache",
            "htmlcov",
            ".coverage",
            ".codebase_index",
            ".codebase_models",
            ".zed",
            ".idea",
            ".vscode",
            "out",
        }

        for root, dirs, files_list in os.walk(self.project_path):
            # Modify dirs in-place to skip ignored directories
            dirs[:] = [
                d for d in dirs if d not in ignore_dirs and not d.startswith(".")
            ]

            root_path = Path(root)
            for file in files_list:
                file_path = root_path / file

                # Skip ignored files
                if gitignore_patterns and self._should_ignore_file(
                    file_path, gitignore_patterns
                ):
                    continue

                # Only process supported extensions
                if file_path.suffix.lower() in {
                    ".py",
                    ".js",
                    ".ts",
                    ".jsx",
                    ".tsx",
                    ".rs",
                    ".go",
                    " .c",
                    " .cpp",
                    " .h",
                    " .hpp",
                    " .java",
                    " .cs",
                    " .php",
                    " .rb",
                    " .swift",
                    " .kt",
                    " .scala",
                    " .r",
                    " .m",
                    " .mm",
                    " .css",
                    " .scss",
                    " .sass",
                    " .less",
                    " .html",
                    " .xml",
                    " .json",
                    " .yaml",
                    " .yml",
                    " .toml",
                    " .md",
                    " .sql",
                    " .sh",
                    " .bash",
                }:
                    files.append(file_path)

        return files

    def _should_ignore_file(
        self, file_path: Path, gitignore_patterns: Set[str]
    ) -> bool:
        """Check if file should be ignored based on .gitignore patterns."""
        try:
            rel_path = file_path.relative_to(self.project_path)
            rel_path_str = rel_path.as_posix().lower()

            for pattern in gitignore_patterns:
                if self._match_gitignore_pattern(rel_path_str, pattern):
                    return True

        except ValueError:
            pass

        return False

    def _match_gitignore_pattern(self, path: str, pattern: str) -> bool:
        """Match path against .gitignore pattern."""
        import fnmatch

        try:
            return fnmatch.fnmatch(path, pattern)
        except Exception:
            return False

    def _update_cache(self, files: List[Path]) -> str:
        """Update cache with new file information and return root hash."""
        hasher = hashlib.sha256()

        with sqlite3.connect(self.cache_db_path) as conn:
            for file_path in files:
                normalized_path = self._normalize_path(file_path)
                file_hash = self._get_file_hash(file_path)
                file_mtime = self._get_file_mtime(file_path)
                content_size = file_path.stat().st_size if file_path.exists() else 0

                # Update cache entry
                conn.execute(
                    """
                    INSERT OR REPLACE INTO file_cache
                    (file_path, file_hash, last_modified, content_size, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (
                        normalized_path,
                        file_hash,
                        file_mtime,
                        content_size,
                        int(time.time()),
                    ),
                )

                # Update root hash
                hasher.update(file_hash.encode())

            conn.commit()

        return hasher.hexdigest()

    def find_changed_files(self, previous_root_hash: str) -> List[Path]:
        """Find files that have changed since last build.

        Args:
            previous_root_hash: Root hash from previous build

        Returns:
            List of changed file paths
        """
        current_root_hash = self._get_current_root_hash()

        if current_root_hash == previous_root_hash:
            return []

        # Get all files that have different hashes
        changed_files = self._get_changed_file_paths(current_root_hash)

        logger.info(
            f"🔍 Changes detected. Previous: {previous_root_hash[:16]}..., Current: {current_root_hash[:16]}..."
        )

        return changed_files

    def _get_current_root_hash(self) -> str:
        """Calculate current root hash from cache."""
        hasher = hashlib.sha256()

        with sqlite3.connect(self.cache_db_path) as conn:
            cursor = conn.execute("SELECT file_hash FROM file_cache")
            for row in cursor.fetchall():
                file_hash = row[0]
                hasher.update(file_hash.encode())

        return hasher.hexdigest()

    def _get_changed_file_paths(self, current_root_hash: str) -> List[Path]:
        """Get paths of files that have changed."""
        changed_files = []

        with sqlite3.connect(self.cache_db_path) as conn:
            cursor = conn.execute("SELECT file_path FROM file_cache")
            for row in cursor.fetchall():
                normalized_path = row[0]
                # Convert back to Path relative to project
                file_path = self.project_path / normalized_path
                changed_files.append(file_path)

        return changed_files

    def get_file_hash(self, file_path: Path) -> Optional[str]:
        """Get hash of specific file from cache."""
        normalized_path = self._normalize_path(file_path)

        with sqlite3.connect(self.cache_db_path) as conn:
            cursor = conn.execute(
                "SELECT file_hash FROM file_cache WHERE file_path = ?",
                (normalized_path,),
            )
            row = cursor.fetchone()
            return row[0] if row else None

    def is_file_in_cache(self, file_path: Path) -> bool:
        """Check if file is in the cache."""
        normalized_path = self._normalize_path(file_path)

        with sqlite3.connect(self.cache_db_path) as conn:
            cursor = conn.execute(
                "SELECT 1 FROM file_cache WHERE file_path = ?", (normalized_path,)
            )
            return cursor.fetchone() is not None

    def get_cache_stats(self) -> Dict:
        """Get cache statistics."""
        with sqlite3.connect(self.cache_db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM file_cache")
            file_count = cursor.fetchone()[0]

            cursor = conn.execute("SELECT COUNT(DISTINCT file_hash) FROM file_cache")
            unique_hash_count = cursor.fetchone()[0]

            cursor = conn.execute("SELECT MAX(updated_at) FROM file_cache")
            last_updated = cursor.fetchone()[0] or 0

        return {
            "file_count": file_count,
            "unique_hash_count": unique_hash_count,
            "last_updated": last_updated,
            "cache_path": str(self.cache_db_path),
        }
