import warnings
warnings.warn(
    "src.core.graph_adapter is deprecated, use src.core.search.graph_adapter",
    DeprecationWarning, stacklevel=2,
)
from src.core.search.graph_adapter import *  # noqa: F403, F405

