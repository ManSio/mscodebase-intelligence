import warnings
warnings.warn(
    "src.core.project_indexer_registry is deprecated, use src.core.indexing.project_indexer_registry",
    DeprecationWarning, stacklevel=2,
)
from src.core.indexing.project_indexer_registry import *  # noqa: F403, F405

