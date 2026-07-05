"""Изолированный тест guard'a для D:\\Project\\MSCodeBase.

Запускаем resolve_project_root и _is_self_index_path напрямую,
с теми же env-флагами, что и Zed передаёт MCP-серверу.
Печатаем PID, env vars, и все guard-результаты.
"""
import os
import sys

# Имитация Zed env
os.environ["MSCODEBASE_ALLOW_SELF_INDEX"] = "1"
os.environ["PROJECT_PATH"] = r"D:\Project\MSCodeBase"
os.environ["ZED_WORKTREE_ROOT"] = r"D:\Project\MSCodeBase"
os.environ["PYTHONPATH"] = r"C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence"
sys.path.insert(0, os.environ["PYTHONPATH"])

import time
print(f"[t={time.time():.3f} PID={os.getpid()}] === START DEBUG ===")
print(f"  MSCODEBASE_ALLOW_SELF_INDEX = {os.environ.get('MSCODEBASE_ALLOW_SELF_INDEX')!r}")
print(f"  PROJECT_PATH                = {os.environ.get('PROJECT_PATH')!r}")
print(f"  ZED_WORKTREE_ROOT           = {os.environ.get('ZED_WORKTREE_ROOT')!r}")
print(f"  CWD                         = {os.getcwd()!r}")

# 1) Resolve project_root
print("\n--- (1) resolve_project_root ---")
from src.mcp.server import resolve_project_root, reset_project_root_cache, _ext_root
reset_project_root_cache()
pr = resolve_project_root()
print(f"  project_root = {pr}")
print(f"  _ext_root    = {_ext_root}")
print(f"  equal?       = {pr.resolve() == _ext_root.resolve()}")

# 2) _is_self_index_path
print("\n--- (2) _is_self_index_path ---")
from src.mcp.tools.base import _is_self_index_path
print(f"  _is_self_index_path({pr}) = {_is_self_index_path(pr)}")

# 3) is_zed_install_dir
print("\n--- (3) is_zed_install_dir ---")
from src.core.lsp_project_bridge import is_zed_install_dir
print(f"  is_zed_install_dir({pr}) = {is_zed_install_dir(pr)}")
print(f"  is_zed_install_dir({_ext_root}) = {is_zed_install_dir(_ext_root)}")
print(f"  is_zed_install_dir(D:\\AI\\Zed) = {is_zed_install_dir(r'D:\\AI\\Zed')}")

# 4) Создаём MCP server
print("\n--- (4) create_mcp_server ---")
try:
    from src.mcp.server import create_mcp_server
    server = create_mcp_server()
    print(f"  server created: {type(server).__name__}")
    print(f"  registered tools: {len(getattr(server, '_tool_manager', {})._tools) if hasattr(server, '_tool_manager') else 'N/A'}")
except Exception as e:
    import traceback
    print(f"  ERROR: {e}")
    traceback.print_exc()

print("\n=== END DEBUG ===")
