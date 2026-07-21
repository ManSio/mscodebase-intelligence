import warnings
warnings.warn(
    "src.core.cross_project_deps is deprecated, use src.core.search.cross_project_deps",
    DeprecationWarning, stacklevel=2,
)
from src.core.search.cross_project_deps import *  # noqa: F403, F405

