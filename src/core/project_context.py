import warnings
warnings.warn(
    "src.core.project_context is deprecated, use src.core.intelligence.project_context",
    DeprecationWarning, stacklevel=2,
)
from src.core.intelligence.project_context import *  # noqa: F403, F405

