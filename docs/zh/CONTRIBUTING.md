<img src="../../logo/logo.svg" width="64" height="64" align="left" style="margin-right: 16px;">

[🇬🇧 English](../en/CONTRIBUTING.md) • [🇷🇺 Русский](../ru/CONTRIBUTING.md) • [🇨🇳 中文](CONTRIBUTING.md)

# 贡献指南 — MSCodeBase Intelligence

贡献者指南。项目版本：**3.2.0**（Polyglot Graph Engine）

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

要求：Python 3.10+，LM Studio（可选，用于嵌入）

> 💡 v3.2.0 使用 **llama.cpp** 作为主要嵌入提供者（通过 `install.py` 自动安装）。LM Studio 作为备用。

---

## 2. 架构（整洁架构 Clean Architecture）

```
src/
├── main.py              # 入口点（最小化）
├── lsp_main.py          # LSP 处理器（通过 ServiceCollection 的 DI）
├── mcp/
│   ├── server.py        # ~220 行 — 仅工具注册
│   ├── write_tools.py   # 6 个写入工具
│   └── tools/           # 11 个文件，57 个工具（40 个基于类 + 14 个 intel + 3 个诊断）
│       ├── base.py          # MCPTool ABC
│       ├── search_tools.py  # search_code（+ 已弃用的 smart_search 等）
│       ├── graph_tools.py   # query_graph + Cypher 查询引擎
│       ├── indexing_tools.py# 索引管理
│       ├── git_tools.py     # git 集成
│       ├── system_tools.py  # 9 个系统/健康工具
│       ├── analysis_tools.py# impact_analysis, structural_search 等
│       └── write_tools.py   # rename/move/delete/replace/insert
├── core/                # 业务逻辑（无 MCP 依赖）
│   ├── di_container.py  # ServiceCollection（15+ 个服务）
│   ├── error_handler.py # error_boundary + ToolError
│   ├── rate_limiter.py  # DebounceBatch + CircuitBreaker
│   ├── indexer.py       # LanceDB 向量存储
│   ├── searcher.py      # 混合搜索（BM25 + 稠密 + RRF）
│   ├── parser.py        # Tree-sitter AST + ASSIGNED_FROM 提取
│   ├── graph.py         # PropertyGraph（SQLite WAL）— 节点/边
│   ├── graph_adapter.py # 包装 PropertyGraph 的 SymbolIndexAdapter
│   ├── cypher_engine.py # MATCH→SQL 引擎
│   ├── route_extractor.py# HTTP 路由检测（Flask/FastAPI/Django/Express）
│   ├── multi_signal_scorer.py# 4 信号搜索评分
│   ├── dataflow_experiment.py# ASSIGNED_FROM 基准测试
│   ├── intelligence_layer.py  # 14 个 intel_* 工具
│   ├── llama_runner.py   # llama-server.exe 生命周期
│   ├── remote_embedder.py# LM Studio / llama.cpp / Ollama / ONNX
│   ├── file_guard.py     # .gitignore + 扩展过滤器
│   └── ...
└── utils/
    ├── paths.py         # SafePathManager
    └── zed_config.py    # ZedSettings
```

**关键原则：**
1. 所有工具都是独立的类，使用构造函数注入（通过 `MCPTool`）
2. 每个工具都使用 `@error_boundary` 装饰（JSON + 超时）
3. 依赖创建的唯一位置 — `create_service_collection()`
4. LSP 和 MCP 使用同一个 DI 容器（无重复）

**重要：** 开发 MCP 工具时，主文件是 `src/mcp/server.py`（`create_mcp_server()` 函数）。`src/hybrid_server.py` 是入口点，同时启动 LSP 和 MCP。

---

## 3. 代码风格

- **格式化工具**：Black（行长度 88）
- **导入顺序**：isort
- **类型提示**：公共 API 必需
- **日志记录**：`logging.getLogger(__name__)` — production 代码中永远不要使用 `print()`
- **异步**：使用 `async/await` 进行 I/O 操作；重型磁盘操作通过 `asyncio.to_thread()`

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

在 `tests/` 目录中有 **494 个测试**。通过 `pytest` 运行，支持标记。

```powershell
# 完整测试集
pytest tests/ -v

# 仅快速测试（不含 slow 和 integration）
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
|------|--------|------|----------|
| `test_agentic_search.py` | 20 | unit, async | 智能搜索：路由，查询优化 |
| `test_reranker.py` | 27 | unit, async | 重排序器：排序，权重，边界情况 |
| `test_symbol_index_call_graph.py` | 22 | unit | 调用图：构建，遍历，循环依赖 |
| `test_cross_repo_search.py` | 21 | unit | 跨仓库搜索：结果合并 |
| `test_deep_search.py` | 15 | unit | 深度搜索：迭代，优化，停止条件 |
| `test_index_progress.py` | 11 | unit | 索引进度：状态，状态转换 |
| `test_indexer_project_path.py` | 6 | unit | 索引器路径：规范化，验证 |
| `test_parser.py` | 4 | unit | 解析器：AST 提取，语法错误 |
| `test_integration.py` | 3 | integration | 与真实 LanceDB 集成 |
| `benchmark_agentic_search.py` | 6 | benchmark | 智能搜索性能 |

### 测试分类

- **单元测试（129 个）** — 不需要外部服务，时间 < 5 秒
- **集成测试（3 个）** — 需要 LanceDB，标记为 `@pytest.mark.integration`
- **基准测试（6 个）** — 延迟/吞吐量测量，不在常规运行中
- **异步测试** — `test_agentic_search.py` 和 `test_reranker.py` 使用 `pytest-asyncio`

### CI 流水线

```bash
# 最小化（每次提交）
pytest tests/ -m "not integration and not benchmark" --tb=short -q

# 完整（夜间运行）
pytest tests/ --tb=long -v
```

CI 要求：Python 3.10+，`pytest`，`pytest-asyncio`，`pytest-cov`。

---

## 5. 添加新的 MCP 工具

所有 34 个 MCP 工具在 `src/mcp/server.py` 的 `create_mcp_server()` 函数中定义。

### 主要工具：

| 类别 | 工具 |
|------|------|
| **搜索** | `search_code(query, mode)`, `structural_search`, `cross_repo_search`, `cross_project_deps` |
| **索引** | `get_index_status`, `get_index_progress`, `get_index_timeline`, `index_project_dir`, `notify_change`, `index_health` |
| **符号** | `get_symbol_info`, `impact_analysis`, `get_repo_map`, `get_repo_rank` |
| **系统** | `get_health_report`, `watcher_status`, `get_logs`, `generate_chunk_summaries` |
| **分析** | `get_hotspots`, `get_bug_correlation`, `get_related_files`, `graph_query` |
| **Git** | `get_commit_history`, `get_file_history`, `get_branch_info` |
| **后台** | `submit_background_task`, `get_task_status` |

> 🔄 `smart_search`, `deep_search`, `context_search` — 已弃用，请使用 `search_code(query, mode=...)`

### 添加新工具的步骤：

1. **实现函数** 在 `src/mcp/server.py` 的 `create_mcp_server()` 中：

```python
@mcp.tool()
def my_new_tool(param: str, kwargs: Optional[Dict[str, Any]] = None) -> str:
    """工具描述供 AI 代理使用。

    使用此工具的情况：
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
        return f"✅ 结果: {param}"
    except Exception as e:
        logger.error(f"my_new_tool 错误: {e}", exc_info=True)
        return f"❌ 错误: {e}"
```

2. **添加 `_debug_log()`** — 这是写入 `mcp_debug.log` 的标记记录，用于调试服务器活性。

3. **处理错误** — 永远不要将异常抛出外部。返回带 `❌` 的字符串。

4. **添加测试** 到 `tests/test_<module>.py`：

```python
def test_my_new_tool():
    from src.mcp.server import create_mcp_server
    mcp = create_mcp_server()
    # 测试逻辑
```

5. **更新文档**：
   - `README.md` — "工具"部分 → 更新类别和描述
   - `ARCHITECTURE.md` — 添加工具描述
   - `CHANGELOG.md` — 添加记录

6. **检查格式化**：

```powershell
black src/mcp/server.py
isort src/mcp/server.py
pytest tests/ -v
```

---

## 6. 添加新的核心模块

核心代码位于 `src/core/`。现有模块：

| 模块 | 用途 |
|------|------|
| `indexer.py` | 文件索引到 LanceDB |
| `searcher.py` | 语义搜索 + 智能搜索 |
| `parser.py` | 代码解析（Tree-sitter） |
| `reranker.py` | 多提供商重排序 |
| `symbol_index.py` | 符号索引 + 调用图 |
| `structural_search.py` | AST 模式匹配 |
| `multi_project_searcher.py` | 跨仓库搜索 |
| `file_guard.py` | 文件过滤（.gitignore） |
| `gitignore_parser.py` | 解析 .gitignore |
| `log_manager.py` | 文件日志记录 |
| `remote_embedder.py` | LM Studio/Ollama/ONNX 客户端 |

### 添加新模块的步骤：

1. **创建文件** 在 `src/core/my_module.py`：

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

2. **导入并连接** 在 `src/mcp/server.py` 中：

```python
from src.core.my_module import MyModule

# 在 create_mcp_server() 内部：
my_module = MyModule(...)
```

3. **添加测试** 到 `tests/test_my_module.py`：

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

## 7. 提交信息

格式：Conventional Commits：`type(scope): description`

**类型：**
- `feat` — 新功能
- `fix` — 错误修复
- `docs` — 文档
- `test` — 添加/修改测试
- `refactor` — 重构（不改变行为）
- `perf` — 性能优化
- `chore` — 维护（依赖，配置）

**范围：** `searcher`, `indexer`, `parser`, `reranker`, `mcp`, `lsp`, `core`, `tests`, `docs`

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

- [ ] 分支从 `development`（不是 `main`）创建
- [ ] `pytest tests/ -v` — 所有测试通过
- [ ] `black --check src/` — 符合格式化要求
- [ ] `isort --check-only src/` — 导入已排序
- [ ] 所有公共函数有类型提示
- [ ] production 代码中没有 `print()`（仅使用 `logging`）
- [ ] 新工具/模块有测试覆盖
- [ ] `CHANGELOG.md` 已更新
- [ ] `README.md` 已更新（如果公共 API 发生变化）
- [ ] `ARCHITECTURE.md` 已更新（如果架构发生变化）

### PR 描述应包含：

1. **变更内容** — 具体的文件和函数
2. **原因** — 解决什么问题
3. **测试方式** — 添加/运行了哪些测试
4. **Breaking changes** — 如果有，需明确说明

### 流程：

1. 在 GitHub 创建 PR
2. 等待 review
3. 修复意见
4. 合并到 `development`（不直接合并到 `main`）

---

## 9. 版本管理

SemVer：MAJOR.MINOR.PATCH

- **MAJOR** — 不兼容的 API 更改
- **MINOR** — 新工具/功能（向后兼容）
- **PATCH** — 错误修复

当前版本在 `pyproject.toml` 中：`1.2.0`

---

## 10. 贡献者故障排除

| 问题 | 解决方案 |
|------|----------|
| `ModuleNotFoundError: No module named 'src'` | 确保从项目根目录运行 |
| `mcp` 从 `src/mcp/` 导入而不是库 | 检查 `sys.path` — `src/` 应在 mcp 导入之后添加 |
| 测试因嵌入错误失败 | 这在回退模式下是正常的；要进行完整测试，请启动 LM Studio |
| 启动时出现 `WinError 5` | 使用 `src/hybrid_server.py`（单进程而非双进程） |

---

*最后更新：2026-07-05*
