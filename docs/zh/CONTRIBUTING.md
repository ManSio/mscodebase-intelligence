# 贡献指南 — MSCodeBase Intelligence

> **版本：** 3.3.9 — DocSync 版

---

## 1. 环境设置

```powershell
git clone https://github.com/ManSio/mscodebase-intelligence.git
cd MSCodeBase
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
pip install -e "."
```

要求：Python 3.10+，Windows（主要）或 Linux（实验性）。

---

## 2. 架构（整洁架构 Clean Architecture）

```
src/
├── main.py              # 入口点（最小化）
├── mcp/
│   ├── server.py        # MCP 服务器注册（约 220 行）
│   ├── server_factory.py # 服务器工厂 + DI 设置
│   ├── server_tools.py  # 工具注册（共 42 个工具）
│   └── tools/           # 14 个文件，18 个核心 + 13 个 intel + 7 个内联 + 3 个开发 + 1 个可选
│       ├── base.py          # MCPTool ABC
│       ├── search_tools.py  # search_code, get_symbol_info, impact_analysis
│       ├── codebase_tool.py # codebase(action={rename,move,delete,...})
│       ├── write_tools.py   # write(action={rename,move,delete,replace,insert,impact})
│       ├── graph_tools.py   # graph_query, cross_repo_search, cross_project_deps
│       ├── indexing_tools.py# 索引管理
│       ├── git_tools.py     # git(action={log,history,branch})
│       ├── doc_tools.py     # generate_docs, bump_version, auto_update_docs, install_git_hooks
│       ├── dev_tools.py     # 开发工具
│       ├── system_tools.py  # 系统/健康工具
│       ├── analysis_tools.py# structural_search, scan_changes 等
│       ├── investigation_tools.py # bug_correlation, hotspots 等
│       ├── lifecycle_tools.py# 后台任务，验证
│       └── meta_tools.py    # 索引状态，健康报告
├── core/                # 纯业务逻辑（无 MCP 导入）
│   ├── di_container.py  # ServiceCollection（15+ 服务）
│   ├── error_handler.py # error_boundary + ToolError
│   ├── rate_limiter.py  # SlidingWindowRateLimiter + CircuitBreaker
│   ├── runtime_coordinator.py # ExecutionVerdict + can_execute()
│   ├── graph.py         # PropertyGraph（SQLite WAL）— 节点/边
│   ├── doc_sync_engine.py # 自动同步文档与代码（重命名钩子）
│   ├── search/
│   │   ├── engine.py    # 混合搜索（BM25 + Dense + FTS5 + RRF）
│   │   ├── fts5_mixin.py# FTS5 全文搜索
│   │   ├── graph_adapter.py # PropertyGraph → SymbolIndex
│   │   ├── cypher_engine.py # Cypher→SQL
│   │   └── scoring.py   # RRF + MMR 多样性
│   ├── indexing/
│   │   ├── indexer.py   # LanceDB 向量存储
│   │   ├── db_manager.py# LanceDB 生命周期（PID-lock）
│   │   ├── parser.py    # Tree-sitter AST（16 种语言）
│   │   ├── file_guard.py# .gitignore + 扩展过滤器
│   │   ├── symbol_index.py # 调用图（BFS, PageRank）
│   │   └── watchdog.py  # 文件变更监视器
│   └── intelligence/
│       ├── layer.py     # 13 个 intel_* 工具
│       ├── project_context.py # 项目状态快照
│       ├── health.py    # 系统健康检查
│       └── tools_reg.py # Intel 工具注册
├── providers/
│   ├── embedder/
│   │   └── remote_embedder.py # ONNX E5-small + LM Studio/Ollama
│   └── reranker/
│       ├── llama_runner.py   # llama-server.exe 生命周期
│       ├── multi_provider.py # 多提供者（provider）重排序
│       └── search_result_reranker.py # 结果重排序
└── utils/
    ├── i18n.py          # 国际化
    ├── paths.py         # SafePathManager
    └── zed_config.py    # Zed 设置管理
```

**关键原则：**
1. 所有工具都是独立的类，使用构造函数注入（通过 `MCPTool`）
2. 每个工具都使用 `@error_boundary` 装饰（JSON + 超时）
3. 单一 DI 容器 — `create_service_collection()` 在 `di_container.py` 中
4. 核心层有零个 MCP 导入

---

## 3. 代码风格

- **格式化工具**：Black（行长度 88）
- **导入顺序**：isort
- **类型提示**：所有公共 API 必需
- **日志记录**：`logging.getLogger(__name__)` — production 代码中永远不要使用 `print()`
- **异步**：使用 `async/await` 进行 I/O 操作；重型磁盘操作 → `asyncio.to_thread()`

```powershell
# 检查格式化
black --check src/
isort --check-only src/

# 自动格式化
black src/
isort src/
```

---

## 4. 运行测试

项目在 `tests/` 目录中有 **565+ 个测试**。

```powershell
# 完整测试集
pytest tests/ -v

# 仅快速测试（不含 slow/integration/benchmark）
pytest tests/ -v -m "not slow and not integration and not benchmark"

# 按标记
pytest tests/ -v -m slow
pytest tests/ -v -m integration
pytest tests/ -v -m benchmark

# 按模块
pytest tests/test_engine.py -v
pytest tests/test_parser.py -v

# 带覆盖率
pytest tests/ --cov=src --cov-report=term-missing
```

**标记**（在 `pyproject.toml` 中定义）：
- `slow` — 慢速测试
- `integration` — 集成测试（需要 LanceDB）
- `benchmark` — 性能基准测试
- `asyncio` — 异步测试

### 测试分类

| 类别 | 数量 | 描述 |
|----------|-------|-------------|
| 单元测试 | 550+ | 无外部服务，每个 <5 秒 |
| 集成测试 | 3 | 需要 LanceDB，标记 `@pytest.mark.integration` |
| 基准测试 | 6 | 延迟/吞吐量测量 |

### CI 流水线

```bash
# 最小化（每次提交）
pytest tests/ -m "not integration and not benchmark" --tb=short -q

# 完整（夜间运行）
pytest tests/ --tb=long -v
```

---

## 5. 添加新的 MCP 工具

工具在 `src/mcp/server_tools.py` 中通过 `register_all_tools()` 注册。
每个工具是 `src/mcp/tools/*.py` 中的一个类，继承自 `MCPTool`。

### 工具类别（共 42 个）：

| 类别 | 数量 | 主要工具 |
|----------|-------|-----------|
| **搜索** | 3 | `search_code`, `get_symbol_info`, `impact_analysis` |
| **Codebase** | 1 | `codebase(action=rename/move/delete/...)` |
| **写入** | 1 | `write(action=rename/move/delete/replace/insert)` |
| **分析** | 5 | `structural_search`, `get_repo_map`, `scan_changes` 等 |
| **图** | 3 | `graph_query`, `cross_repo_search`, `cross_project_deps` |
| **Git** | 1 | `git(action=log/history/branch)` |
| **索引** | 1 | `get_index_status`, `notify_change`, `watcher_status` |
| **文档** | 1 | `generate_docs`, `bump_version`, `auto_update_docs`, `install_git_hooks` |
| **调查** | 3 | `get_bug_correlation`, `get_hotspots`, `find_similar_bugs` |
| **生命周期** | 3 | `submit_background_task`, `get_task_status`, `verify_action` |
| **系统** | 1 | `read_live_file`, `get_health_report`, `get_logs` |
| **元** | 1 | 索引状态，健康报告 |
| **Intelligence** | 13 | `intel_get_runtime_status`, `intel_trigger_reindex` 等 |
| **开发** | 3 | `generate_docs`, `bump_version`, `install_git_hooks` |
| **诊断内联** | 7 | `debug_runtime_passport`, `get_runtime_counters` 等 |
| **可选** | 1 | `execute_script(code)`（E2B 沙箱） |

### 添加新工具的步骤：

1. **在 `src/mcp/tools/<category>.py` 中创建类**：

```python
from src.core.di_container import ServiceCollection
from src.mcp.tools.base import MCPTool
from src.core.error_handler import error_boundary


class MyNewTool(MCPTool):
    """供 AI 代理使用的描述。

    使用此工具的情况：
    - 使用场景 1
    - 使用场景 2

    Args:
        param: 参数描述
    """

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="my_new_tool")

    @error_boundary("my_new_tool", timeout_ms=15000)
    async def execute(self, param: str, **kwargs) -> dict:
        # 实现
        return {"status": "ok", "result": param}
```

2. **在 `src/mcp/server_tools.py` 中注册**：

```python
from src.mcp.tools.my_module import MyNewTool

def register_all_tools(mcp, services):
    tool_classes = [
        ...
        MyNewTool,
    ]
    for cls in tool_classes:
        tool = cls(services)
        mcp.tool()(tool.execute)
```

3. **在 `tests/test_<module>.py` 中添加测试**。

4. **更新文档**：
   - `README.md` — 工具部分
   - `ARCHITECTURE.md` — 如果架构发生变化
   - `CHANGELOG.md` — 添加记录

5. **运行验证**：

```powershell
python -m pytest tests/ -q --tb=short
auto_update_docs(action="verify")
```

---

## 6. 添加新的核心模块

核心模块位于 `src/core/`。不允许 MCP 导入。

### 步骤：

1. **在适当的 `src/core/` 子目录中创建文件**：

```python
"""用于 ... 的模块"""
import logging
from typing import Any

logger = logging.getLogger(__name__)


class MyModule:
    def __init__(self, ...):
        ...

    def do_something(self) -> Any:
        """方法的作用。"""
        ...
```

2. **在 DI 中注册** — `src/core/di_container.py`：

```python
services.add_singleton(MyModule, MyModule(...))
```

3. **在 `tests/test_my_module.py` 中添加测试**。

4. **更新 ARCHITECTURE.md**。

5. **运行 DocSync 验证文档匹配**：

```python
from src.core.doc_sync_engine import DocSyncEngine
engine = DocSyncEngine(project_root)
report = engine.sync_all()
```

---

## 7. 提交信息

Conventional Commits 格式：`type(scope): description`

**类型：** `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `chore`

**范围：** `search`, `indexer`, `parser`, `mcp`, `core`, `tests`, `docs`, `doc_sync`

**示例：**
```
feat(search): add FTS5 full-text search to hybrid pipeline
fix(indexer): handle LanceDB Not found during reindex
docs: update ARCHITECTURE.md with DocSync engine
refactor(doc_sync): clean up suggestion logic
```

---

## 8. PR 流程

### 检查清单：

- [ ] 分支从 `development`（不是 `main`）创建
- [ ] `pytest tests/ -v` — 所有测试通过
- [ ] `black --check src/` — 符合格式化要求
- [ ] 所有公共函数有类型提示
- [ ] production 代码中没有 `print()`（仅使用 `logging`）
- [ ] 新工具/模块有测试覆盖
- [ ] `CHANGELOG.md` 已更新
- [ ] `README.md` 已更新（如果公共 API 发生变化）
- [ ] `ARCHITECTURE.md` 已更新（如果架构发生变化）
- [ ] DocSync 检查：`auto_update_docs(action="verify")`

### PR 描述应包含：

1. **变更内容** — 具体的文件和函数
2. **原因** — 解决什么问题
3. **测试方式** — 添加/运行了哪些测试
4. **Breaking changes** — 如果有，需明确说明

---

## 9. 版本管理

SemVer：MAJOR.MINOR.PATCH

- **MAJOR** — 不兼容的 API 更改
- **MINOR** — 新工具/功能（向后兼容）
- **PATCH** — 错误修复

当前版本在 `pyproject.toml` 中：`3.3.9`

---

## 10. 故障排除

| 问题 | 解决方案 |
|---------|----------|
| `ModuleNotFoundError: No module named 'src'` | 从项目根目录运行 |
| 测试因嵌入错误失败 | 这在回退模式下是正常的；使用 LM Studio 进行完整测试 |
| 首次调用 MCP 服务器超时 | 重排序器（reranker）冷启动 — 第二次调用即可正常工作 |
| DocSync 报告误报 | 运行 `auto_update_docs(action="verify")` 获取当前状态 |

---

*最后更新：2026-07-21 | DocSync 版*
