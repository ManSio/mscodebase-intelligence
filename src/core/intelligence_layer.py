# Backward compatibility shim
import warnings
warnings.warn(
    "src.core.intelligence_layer is deprecated, use src.core.intelligence.layer",
    DeprecationWarning, stacklevel=2,
)
from src.core.intelligence.layer import *  # noqa: F401, F403
