"""
Integrity verification and change detection using Merkle Trees.
Provides atomic change detection for MSCodeBase to optimize file watching.
"""

import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class MerkleTree:
    """Merkle Tree implementation for efficient change detection."""

    def __init__(self, project_path: Path):
        self.project_path = project_path
        self.tree: Dict[Path, str] = {}  # file_path -> hash
        self.root_hash: Optional[str] = None

    def build_tree(self, gitignore_patterns: Set[str] = None) -> str:
        """Build Merkle Tree for the project.

        Args:
            gitignore_patterns: Set of .gitignore patterns to exclude files

        Returns:
            Root hash of the Merkle Tree
        """
        logger.info(f"🔄 Building Merkle Tree for: {self.project_path}")

        # Clear existing tree
        self.tree.clear()

        # Walk through project directory
        for root, dirs, files in os.walk(self.project_path):
            # Skip ignored directories
            dirs[:] = [d for d in dirs if not self._should_ignore_dir(d)]

            root_path = Path(root)

            for file in files:
                file_path = root_path / file

                # Skip ignored files
                if gitignore_patterns and self._should_ignore_file(
                    file_path, gitignore_patterns
                ):
                    continue

                # Calculate file hash
                file_hash = self._hash_file(file_path)
                self.tree[file_path] = file_hash

        # Calculate root hash
        self.root_hash = self._calculate_root_hash()
        logger.info(f"✅ Merkle Tree built. Root hash: {self.root_hash[:16]}...")

        return self.root_hash

    def _should_ignore_dir(self, dir_name: str) -> bool:
        """Check if directory should be ignored."""
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
        return dir_name in ignore_dirs

    def _should_ignore_file(
        self, file_path: Path, gitignore_patterns: Set[str]
    ) -> bool:
        """Check if file should be ignored based on .gitignore patterns."""
        try:
            rel_path = file_path.relative_to(self.project_path)
            rel_path_str = str(rel_path).replace(os.sep, "/")

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

    def _hash_file(self, file_path: Path) -> str:
        """Calculate SHA-256 hash of file content."""
        try:
            # Use a reasonable buffer size for large files
            hasher = hashlib.sha256()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except (FileNotFoundError, OSError) as e:
            logger.warning(f"⚠️ Could not hash file {file_path}: {e}")
            return hashlib.sha256(b"").hexdigest()  # Return hash of empty content

    def _calculate_root_hash(self) -> str:
        """Calculate root hash from leaf hashes."""
        if not self.tree:
            return hashlib.sha256(b"").hexdigest()

        # Sort paths for consistent hashing
        sorted_paths = sorted(self.tree.keys())

        # Create hash from sorted file hashes
        hasher = hashlib.sha256()
        for file_path in sorted_paths:
            file_hash = self.tree[file_path]
            hasher.update(file_hash.encode())

        return hasher.hexdigest()

    def find_changed_files(self, previous_root_hash: str) -> List[Path]:
        """Find files that have changed since last build.

        Args:
            previous_root_hash: Root hash from previous build

        Returns:
            List of changed file paths
        """
        current_root_hash = self.root_hash
        if current_root_hash == previous_root_hash:
            return []

        # For now, return all files as a simple approach
        # In a full implementation, we would use the Merkle Tree
        # to efficiently find only changed branches
        logger.info(
            f"🔍 Changes detected. Previous: {previous_root_hash[:16]}..., Current: {current_root_hash[:16]}..."
        )
        return list(self.tree.keys())

    def get_file_hash(self, file_path: Path) -> Optional[str]:
        """Get hash of specific file."""
        return self.tree.get(file_path)

    def is_empty(self) -> bool:
        """Check if tree is empty."""
        return len(self.tree) == 0


class IntegrityChecker:
    """Main integrity checker that coordinates Merkle Tree operations."""

    def __init__(self, project_path: Path):
        self.project_path = project_path
        self.merkle_tree = MerkleTree(project_path)
        self.last_root_hash: Optional[str] = None

    def check_integrity(self, gitignore_patterns: Set[str] = None) -> Dict:
        """Check project integrity and return changes.

        Args:
            gitignore_patterns: Set of .gitignore patterns

        Returns:
            Dict with integrity check results
        """
        current_root_hash = self.merkle_tree.build_tree(gitignore_patterns)

        result = {
            "root_hash": current_root_hash,
            "file_count": len(self.merkle_tree.tree),
            "has_changes": self.last_root_hash != current_root_hash,
            "changed_files": [],
        }

        if result["has_changes"]:
            result["changed_files"] = self.merkle_tree.find_changed_files(
                self.last_root_hash
            )

        self.last_root_hash = current_root_hash

        logger.info(
            f"📊 Integrity check: {result['file_count']} files, "
            f"{'changes detected' if result['has_changes'] else 'no changes'}"
        )

        return result

    def get_file_hash(self, file_path: Path) -> Optional[str]:
        """Get hash of specific file."""
        return self.merkle_tree.get_file_hash(file_path)

    def is_file_in_tree(self, file_path: Path) -> bool:
        """Check if file is in the Merkle Tree."""
        return file_path in self.merkle_tree.tree
