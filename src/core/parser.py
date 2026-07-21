import warnings
warnings.warn(
    "src.core.parser is deprecated, use src.core.indexing.parser",
    DeprecationWarning, stacklevel=2,
)
from src.core.indexing.parser import *  # noqa: F403, F405

