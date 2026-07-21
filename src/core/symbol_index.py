import warnings
warnings.warn(
    "src.core.symbol_index is deprecated, use src.core.indexing.symbol_index",
    DeprecationWarning, stacklevel=2,
)
from src.core.indexing.symbol_index import *  # noqa: F403, F405

