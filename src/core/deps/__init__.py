"""Domain services of the core: project dependency-manifest extraction.

Moved here from ``src/sources/manifest`` on 2026-11-08: parsing
``pyproject.toml`` / ``package.json`` / lockfiles is a domain capability (it does
not implement ``WorkspaceSource`` and does not depend on where the code came
from), so ``src/core`` must not reach into the source layer for it.
"""
