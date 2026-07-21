import warnings
warnings.warn(
    "src.core.health_report is deprecated, use src.core.intelligence.health",
    DeprecationWarning, stacklevel=2,
)
from src.core.intelligence.health import *  # noqa: F403, F405
