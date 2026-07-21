import warnings
warnings.warn(
    "src.core.resource_monitor is deprecated, use src.core.indexing.resource_monitor",
    DeprecationWarning, stacklevel=2,
)
from src.core.indexing.resource_monitor import *  # noqa: F403, F405

