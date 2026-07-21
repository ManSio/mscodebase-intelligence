# Backward compatibility shim — re-exports everything from src.config.settings
# Файл оставлен для обратной совместимости. Новый код импортирует из src.config.settings
import warnings
warnings.warn(
    "src.core.config is deprecated, use src.config.settings",
    DeprecationWarning, stacklevel=2,
)
from src.config.settings import *  # noqa: F401, F403
