# Backward compatibility shim — re-exports everything from src.config.settings
# Файл оставлен для обратной совместимости. Новый код импортирует из src.config.settings
from src.config.settings import *  # noqa: F401, F403
