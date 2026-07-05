"""Дамп внутренностей РАБОТАЮЩЕГО MCP через переменную __loader__ trick.

Скрипт подключается к уже запущенному MCP-серверу через сигнал — но
проще: убьёт его и стартует новый, который сразу пишет diagnostic.
"""
import os
import sys
import time

# Env как Zed (без MSCODEBASE_ALLOW_SELF_INDEX — посмотрим что вернёт)
os.environ["PROJECT_PATH"] = r"D:\Project\MSCodeBase"
os.environ["ZED_WORKTREE_ROOT"] = r"D:\Project\MSCodeBase"
os.environ["PYTHONPATH"] = r"C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence"
sys.path.insert(0, os.environ["PYTHONPATH"])

print(f"[t={time.time():.3f} PID={os.getpid()}] === START (NO MSCODEBASE_ALLOW_SELF_INDEX) ===")
print(f"  MSCODEBASE_ALLOW_SELF_INDEX = {os.environ.get('MSCODEBASE_ALLOW_SELF_INDEX')!r}")
print(f"  PROJECT_PATH                = {os.environ.get('PROJECT_PATH')!r}")
print(f"  ZED_WORKTREE_ROOT           = {os.environ.get('ZED_WORKTREE_ROOT')!r}")

from src.mcp.server import resolve_project_root, reset_project_root_cache, _ext_root
reset_project_root_cache()
pr = resolve_project_root()
print(f"  project_root = {pr}")
print(f"  _ext_root    = {_ext_root}")
print(f"  equal?       = {pr.resolve() == _ext_root.resolve()}")

from src.mcp.tools.base import _is_self_index_path
print(f"  _is_self_index_path({pr}) = {_is_self_index_path(pr)}")

from src.core.lsp_project_bridge import is_zed_install_dir
print(f"  is_zed_install_dir({pr}) = {is_zed_install_dir(pr)}")
print(f"  is_zed_install_dir({_ext_root}) = {is_zed_install_dir(_ext_root)}")

# Запустим create_mcp_server — он делает _is_self_index_path в регистрации
print("\n--- create_mcp_server ---")
try:
    from src.mcp.server import create_mcp_server
    server = create_mcp_server()
    print(f"  server created: {type(server).__name__}")
except Exception as e:
    import traceback
    print(f"  ERROR: {e}")
    traceback.print_exc()

print("=== END ===")
