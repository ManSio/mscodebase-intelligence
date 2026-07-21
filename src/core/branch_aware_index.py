import warnings
warnings.warn(
    "src.core.branch_aware_index is deprecated, use src.core.search.branch_aware_index",
    DeprecationWarning, stacklevel=2,
)
from src.core.search.branch_aware_index import *  # noqa: F403, F405

