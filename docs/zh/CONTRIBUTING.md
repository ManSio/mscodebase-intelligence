<img src="../../logo/logo.svg" width="64" height="64" align="left" style="margin-right: 16px;">

# 贡献指南 — MSCodeBase Intelligence

[🇬🇧 English](../en/CONTRIBUTING.md) • [🇷🇺 Русский](../ru/CONTRIBUTING.md) • [🇨🇳 中文](CONTRIBUTING.md)

贡献者指南。项目版本：**2.4.x**（带 DI 的整洁架构）。

---

## 1. 设置

```powershell
git clone https://github.com/ManSio/mscodebase-intelligence.git
cd MSCodeBase
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
pip install -e "."
```

要求：Python 3.10+、LM Studio（可选，用于嵌入生成）。

---

## 2. 架构（整洁架构）

```
src/
├── main.py              # 入口点（最小化）
├── lsp_main.py          # LSP 处理器（通过 ServiceCollection 的 DI）
├── mcp/
│   ├── server.py        # 约 220 行 — 仅工具注册
│   └── tools/           # 10 个文件，43 个工具（33 个基于类 + 10 个 intel）
│       ├── base.py          # MCPTool ABC
│       ├── search_tools.py  # 3 个搜索工具
│       ├── indexing_tools.py# 3 个索引工具
│       ├── git_tools.py     # 3 个 git 工具
│       ├── system_tools.py  # 9 个系统工具
│       ├── analysis_tools.py# 5 个分析工具
│       └── ...
├── core/                # 业务逻辑（无 MCP 依赖）
│   ├── di_container.py  # ServiceCollection（15 个服务）
│   ├── error_handler.py # error_boundary + ToolError
│   ├── rate_limiter.py  # DebounceBatch + CircuitBreaker
│   ├── indexer.py
│   ├── searcher.py
│   └── ...
└── utils/
    ├── paths.py         # SafePathManager
    └── zed_config.py    # ZedSettings
```

**关键原则：**
1. 所有工具都是独立的类，使用构造函数注入（通过 `MCPTool`）
2. 每个工具都用 `@error_boundary` 装饰（JSON + 超时）
3. 唯一创建依赖的地方是 `create_service_collection()`
4. LSP 和 MCP 使用同一个 DI 容器（无重复）

**重要：** 开发 MCP 工具时，主文件是 `src/mcp/server.py`（函数 `create_mcp_server()`）。`src/hybrid_server.py` 是启动 LSP 和 MCP 的入口点。

---

## 3. 代码风格

- **格式化工具**：Black（行长度 88）
- **导入顺序**：isort
- **类型提示**：公共 API 必需
- **日志**：`logging.getLogger(__name__)` — production 代码中绝不使用 `print()`
- **异步**：对 I/O 操作使用 `async/await`；繁重磁盘操作使用 `asyncio.to_thread()`

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

项目在 `tests/` 目录下有 **391+ 项测试**。通过带有标记的 `pytest` 运行。

```powershell
# 完整测试集
pytest tests/ -v

# 仅快速测试（不含慢速和集成测试）
pytest tests/ -v -m "not slow and not integration and not benchmark"

# 按标记
pytest tests/ -v -m slow
pytest tests/ -v -m integration
pytest tests/ -v -m benchmark

# 按模块
pytest tests/test_searcher.py -v
pytest tests/test_parser.py -v
pytest tests/test_cross_repo_search.py -v

# 带覆盖率
pytest tests/ --cov=src --cov-report=term-missing

# 特定测试
pytest tests/test_searcher.py::TestSearcher::test_basic_search -v
```

**标记**（在 `pyproject.toml` 中定义）：
- `slow` — 慢速测试
- `integration` — 集成测试（需要 LM Studio）
- `benchmark` — 性能基准测试
- `asyncio` — 异步测试

所有测试在创建 PR 前必须通过。

### 测试结构

| 文件 | 测试数 | 类型 | 覆盖内容 |
|------|--------|-----|--------------|
| `test_agentic_search.py` | 20 | unit, async | 代理搜索：路由、查询精化 |
| `test_reranker.py` | 27 | unit, async | 重排序器：排名、权重、边界情况 |
| `test_symbol_index_call_graph.py` | 22 | unit | 调用图：构建、遍历、循环依赖 |
| `test_cross_repo_search.py` | 21 | unit | 跨仓库搜索：结果合并 |
| `test_deep_search.py` | 15 | unit | 深度搜索：迭代、精化、停止条件 |
| `test_index_progress.py` | 11 | unit | 索引进度：状态、状态转换 |
| `test_indexer_project_path.py` | 6 | unit | 索引器路径：规范化、验证 |
| `test_parser.py` | 4 | unit | 解析器：AST 提取、语法错误 |
| `test_integration.py` | 3 | integration | 与真实 LanceDB 集成 |
| `benchmark_agentic_search.py` | 6 | benchmark | 代理搜索性能 |

### 测试类别

- **单元测试（129 项）** — 不需要外部服务，时间 < 5 秒
- **集成测试（3 项）** — 需要 LanceDB，标记为 `@pytest.mark.integration`
- **基准测试（6 项）** — 延迟/吞吐量测量，不在常规运行中
- **异步测试** — `test_agentic_search.py` 和 `test_reranker.py` 使用 `pytest-asyncio`

### CI 流水线

```bash
# 最小化（每次提交）
pytest tests/ -m "not integration and not benchmark" --tb=short -q

# 完整（夜间运行）
pytest tests/ --tb=long -v
```

CI 要求：Python 3.10+、`pytest`、`pytest-asyncio`、`pytest-cov`。

---

## 5. 添加新的 MCP 工具

所有 33 个 MCP 工具在 `src/mcp/server.py` 的 `create_mcp_server()` 函数中定义。

### 主要工具：

| 类别 | 工具 |
|-----------|-------------|
| **搜索** | `search_code(query, mode)`、`structural_search`、`cross_repo_search`、`cross_project_deps` |
| **索引** | `get_index_status`、`get_index_progress`、`get_index_timeline`、`index_project_dir`、`notify_change`、`index_health` |
| **符号** | `get_symbol_info`、`impact_analysis`、`get_repo_map`、`get_repo_rank` |
| **系统** | `get_health_report`、`watcher_status`、`get_logs`、`generate_chunk_summaries` |
| **分析** | `get_hotspots`、`get_bug_correlation`、`get_related_files`、`graph_query` |
| **Git** | `get_commit_history`、`get_file_history`、`get_branch_info` |
| **后台** | `submit_background_task`、`get_task_status` |

> 🔄 `smart_search`、`deep_search`、`context_search` — 已弃用，请使用 `search_code(query, mode=...)`

### 添加新工具的步骤：

1. **在 `src/mcp/server.py` 的 `create_mcp_server()` 中实现函数：**

```python
@mcp.tool()
def my_new_tool(param: str, kwargs: Optional[Dict[str, Any]] = None) -> str:
    """AI 代理的工具描述。

    使用此工具当：
    - 使用场景 1
    - 使用场景 2

    Args:
        param: 参数描述

    Returns:
        返回值描述
    """
    _debug_log("my_new_tool", param)
    try:
        # 实现
        return f"✅ 结果：{param}"
    except Exception as e:
        logger.error(f"my_new_tool 错误：{e}", exc_info=True)
        return f"❌ 错误：{e}"
```

2. **添加 `_debug_log()`** — 这是在 `mcp_debug.log` 中的标记记录，用于调试服务器活动情况。

3. **处理错误** — 永远不要向外抛出异常。返回带 `❌` 的字符串。

4. **在 `tests/test_<module>.py` 中添加测试：**

```python
def test_my_new_tool():
    from src.mcp.server import create_mcp_server
    mcp = create_mcp_server()
    # 测试逻辑
```

5. **更新文档：**
   - `README.md` — "工具"部分 → 更新类别和描述
   - `ARCHITECTURE.md` — 添加工具描述
   - `CHANGELOG.md` — 添加记录

6. **检查格式化：**

```powershell
black src/mcp/server.py
isort src/mcp/server.py
pytest tests/ -v
```

---

## 6. 添加新的核心模块

核心位于 `src/core/`。现有模块：

| 模块 | 用途 |
|---|---|
| `indexer.py` | 文件索引到 LanceDB |
| `searcher.py` | 语义搜索 + 代理搜索 |
| `parser.py` | 代码解析（Tree-sitter） |
| `reranker.py` | 多提供商重排序 |
| `symbol_index.py` | 符号索引 + 调用图 |
| `structural_search.py` | AST 模式 |
| `multi_project_searcher.py` | 跨仓库搜索 |
| `file_guard.py` | 文件过滤（.gitignore） |
| `gitignore_parser.py` | .gitignore 解析 |
| `log_manager.py` | 文件日志 |
| `remote_embedder.py` | LM Studio/Ollama/ONNX 客户端 |

### 添加新模块的步骤：

1. **在 `src/core/my_module.py` 中创建文件：**

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

2. **在 `src/mcp/server.py` 中导入并连接：**

```python
from src.core.my_module import MyModule

# 在 create_mcp_server() 内部：
my_module = MyModule(...)
```

3. **在 `tests/test_my_module.py` 中添加测试：**

```python
import pytest
from src.core.my_module import MyModule

class TestMyModule:
    def test_basic(self):
        module = MyModule()
        result = module.do_something()
        assert result is not None
```

4. **更新 `ARCHITECTURE.md`** — 在组件图中添加模块。

---

## 7. 提交消息

格式：Conventional Commits：`type(scope): description`

**类型：**
- `feat` — 新功能
- `fix` — 缺陷修复
- `docs` — 文档
- `test` — 添加/修复测试
- `refactor` — 不改变行为的重构
- `perf` — 性能改进
- `chore` — 维护（依赖、配置）

**范围：** `searcher`、`indexer`、`parser`、`reranker`、`mcp`、`lsp`、`core`、`tests`、`docs`

**示例：**
```
feat(searcher): add BM25 hybrid search implementation
fix(indexer): handle empty embeddings from LM Studio
docs: update README with architecture diagram
test(cross-repo): add @-mention parsing tests
refactor(mcp): extract debug logging to shared utility
perf(symbol_index): cache call graph results
```

---

## 8. PR 流程

### 创建 PR 前的检查清单：

- [ ] 分支从 `development` 创建（不是 `main`）
- [ ] `pytest tests/ -v` — 所有测试通过
- [ ] `black --check src/` — 格式符合规范
- [ ] `isort --check-only src/` — 导入已排序
- [ ] 所有公共函数都有类型提示
- [ ] production 代码中没有 `print()`（仅 `logging`）
- [ ] 新工具/模块有测试覆盖
- [ ] `CHANGELOG.md` 已更新
- [ ] `README.md` 已更新（如果公共 API 变更）
- [ ] `ARCHITECTURE.md` 已更新（如果架构变更）

### PR 描述应包含：

1. **更改了什么** — 具体文件和函数
2. **为什么** — 解决了什么问题
3. **如何测试** — 添加/运行了哪些测试
4. **破坏性变更** — 如果有，明确指出

### 流程：

1. 在 GitHub 上创建 PR
2. 等待审核
3. 修复提出的问题
4. 合并到 `development`（不直接合并到 `main`）

---

## 9. 版本管理

语义化版本控制：MAJOR.MINOR.PATCH

- **MAJOR** — 不兼容的 API 变更
- **MINOR** — 新工具/功能（向后兼容）
- **PATCH** — 缺陷修复

`pyproject.toml` 中的当前版本：`1.2.0`

---

## 10. 贡献者的故障排除

| 问题 | 解决方案 |
|---|---|
| `ModuleNotFoundError: No module named 'src'` | 确保从项目根目录运行 |
| 从 `src/mcp/` 而非库导入 `mcp` | 检查 `sys.path` — `src/` 应在导入 mcp 后添加 |
| 测试因嵌入错误失败 | 回退模式下正常；要完全测试请启动 LM Studio |
| 启动时 `WinError 5` | 使用 `src/hybrid_server.py`（单进程替代两个） |

---

*最后更新：2026-07-05*
