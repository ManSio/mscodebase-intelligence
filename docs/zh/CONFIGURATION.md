# 配置

> 翻译：2026-11-08，来源 docs/en/CONFIGURATION.md。英文版为准。

> 2026-11-08 依据 `src/config/settings.py`、`.env.example` 以及一次实时的
> `get_config()` 输出重写。所示默认值即代码在**未设置任何变量**时返回的值。
> 随仓库变化而变化的数字（索引大小、耗时）位于 [FACTS.md](../FACTS.md)，不在本页。

## 1. 配置来源

1. 配置对象构建时从环境变量读取取值（`src/config/settings.py`、`get_config()`），
   因此修改后需要**重启进程**。
2. 项目根目录下的 `.env` 由 `python-dotenv` 加载；它是存放本地取值的预期位置。
   `.env.example` 记录了受支持的配置面。
3. 优先级：进程环境 > `.env` > 内置默认值。
4. 本清单中没有任何项是从 YAML/JSON 配置文件读取的 —— 不存在第二种配置格式。

下面的分组与 dataclass 一一对应：`server`、`search`、`embedding`、`index`、
`performance`、`security`、`memory`。

## 2. 服务器、profile 与存储

| 变量 | 默认值 | 作用 |
|---|---|---|
| `MSCODEBASE_MCP_PROFILE` | `core` | 工具面：`core` = 17 个工具，`full` = 全部 69 个 |
| `MSCODEBASE_MCP_TOOLS` | — | 显式的逗号分隔 allowlist；覆盖 profile |
| `MSCODEBASE_EXECUTE_SCRIPT_ENABLED` | `false` | 注册 `execute_script`（宿主上的 RCE，默认关闭） |
| `MSCODEBASE_DATA_DIR` | `%LOCALAPPDATA%/mscodebase`（Windows）或 `~/.cache/mscodebase` | graph、memory、jobs、telemetry、commit memory 的根目录 |
| `MSCODEBASE_PROJECT_PATH` / `MSCODEBASE_PROJECT_ROOT` | 未设置 | 当宿主不提供 workspace root 时固定项目 |
| `MSCODEBASE_CHUNKS_DB` | `<project>/.mscodebase/chunks.db` | 覆盖 SQLite chunk 存储位置 |
| `MSCODEBASE_LOG_DIR` | `<data_root>/logs` | 服务器日志目录 |
| `MSCODEBASE_LOCALE` | 系统 / `en` | UI 文案语言（`en`、`ru`） |
| `MCP_HOST` / `MCP_PORT` | `127.0.0.1` / `8765` | Streamable-HTTP 监听（stdio 忽略此项） |
| `LSP_HOST` / `MSCODEBASE_LSP_START_TIMEOUT` | `127.0.0.1` / — | basedpyright LSP 客户端 |

每项目目录为 `<data_root>/projects/<md5(project_path)[:8]>/`
（`src/core/artifact_paths.py`）：`graph.db`、`intelligence/`、`commit_memory/`、
`telemetry/`。项目内部只存在 `chunks.db` 和 `.mscodebase/`，两者都已 gitignore。

## 3. 检索（真正重要的默认值）

| 变量 | 默认值 | 作用 |
|---|---|---|
| `MSCODEBASE_DENSE_OFF` | `true` | 完全跳过 dense/vector 检索；只用 FTS5 + 图 |
| `MSCODEBASE_SQLITE_CHUNKS` | `true` | 用 SQLite/FTS5 chunk 存储提供候选 |
| `MSCODEBASE_ONDEMAND_RERANK` | `false` | 有 provider 时用实时 embedding 重排 top 候选；单次调用覆盖：`investigate(rerank=true)` |
| `MSCODEBASE_ONDEMAND_RERANK_TOP_N` | `10` | 进入 rerank 池的候选数量 |
| `MSCODEBASE_ONDEMAND_RERANK_MAX_CHARS` | `1600` | embedding 前的文本截断长度 |
| `MSCODEBASE_DOCS_MARGIN` | `4.0` | `docs_score − code_score > margin` 时文档通道胜出 |
| `MSCODEBASE_AUGMENT_CHUNKS` | `true` | 在 chunk 文本前加上 `FILE:` / `SYMBOLS:` / `DOC:` |
| `MSCODEBASE_CODE_BM25`（+`_K1`、`_B`、`_STOPWORDS`） | `false` / `1.2` / `0.45` / `true` | 感知标识符的 BM25 打分 |
| `MSCODEBASE_RU_SYNONYMS` | `false` | 俄语 → 英语代码术语扩展 |
| `MSCODEBASE_DEMOTE_NON_CODE` / `_DEMOTE_INTENT_AWARE` | `false` | 对代码问题降低 docs/tests 排名 |
| `MSCODEBASE_P3_ANCHOR` | `false` | 模块头部池锚点 |
| `MSCODEBASE_TESTS_SIGNAL` | `false` | 在符号结果后附加覆盖测试 |
| `MSCODEBASE_LATE_ENRICHMENT` | `false` | 把图富化推迟到排序之后 |
| `MSCODEBASE_EVIDENCE_GATE` | `true` | 校验 `investigate` 的每一行（definition/ast/fresh/graph）并打印确定性结论；`0` 恢复门控前行为 |
| `MSCODEBASE_ASK_REWRITE` | `smart` | `on` —— 任何没有代码形态标识符的西里尔文问题都要求给出标识符；`smart` —— 仅当问题还包含类专有名词的拉丁词（XERJ N03）；`off` —— 返回邻居并带结论。实测：`experiments/xerj_2026_11/evidence_gate/REPORT_REWRITE.md` |
| `MSCODEBASE_FUSION` | `weights` | `investigate` 的合并公式：`weights` —— 通道得分 + 手工权重（默认发布）；`rrf` —— 对命中该行的通道求倒数秩之和；`norm` —— 两项都归一化到 [0, 1]。未知或空值回退到 `weights`。这是实验开关，不是调参旋钮：`experiments/xerj_2026_11/fusion/` |
| `MSCODEBASE_FILE_DEDUP` | *（关）* | `investigate` 的作答顺序：`file` —— 每个文件先出一行，剩余行补到末尾；关 —— 发布顺序。未知或空值即为关。E72 实测：`sqlalchemy`（11/40）与 B1 dev（19/71）的 hit@5 均未变化，而“X 在哪里被使用”丢失了同一文件的行（20 个探针中保留 5 个）—— 这是实验开关，不是默认行为：`experiments/file_dedup_2026_11/` |
| `MSCODEBASE_SCRIPTS_DEMOTE` | `true` | 对代码问题降低 `scripts/`、`examples/`、`benches/`、`fuzz/` 行的排名，与 tests、docs 相同。实测：XERJ P05 回到 top-1，`any` 无损失（`experiments/xerj_2026_11/probe_scripts_demote.py`） |

无论这些开关如何设置，`EXPERIMENTS/**` 都会被 `FileGuard` 排除在索引之外：
冻结面板绝不应作为搜索命中出现。

## 4. 索引与性能

| 变量 | 默认值 | 作用 |
|---|---|---|
| `BASE_INDEX_DIR` | `.codebase_indices` | 旧版索引目录名 |
| `LANCEDB_VERSION` | `v2` | 向量存储布局（仅在启用 dense 时使用） |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `512` / `100` | 回退的行级分块 |
| `INDEX_BATCH_SIZE` | `100` | 每批索引的文件数 |
| `MSCODEBASE_PARSE_TIMEOUT_SEC` | — | 单文件解析预算 |
| `MSCODEBASE_LINK_TIMEOUT_SEC` | — | 图连边阶段预算 |
| `MSCODEBASE_REINDEX_STALL_SEC` | — | 长时间重建的停滞看门狗 |
| `MSCODEBASE_IVF_MAX_ABANDONS` | — | N 次 optimize/create 失败后自动关闭 IVF |
| `MAX_FILE_SIZE_MB`（security，无前缀 —— 由 `SecurityConfig` 读取，`src/config/settings.py:425`） | `10` | 超过此大小的文件会被跳过 |

## 5. Provider（全部可选）

文本优先搜索不需要其中任何一个；它们用于 rerank、legacy dense 路径和 LSP。

| 变量 | 默认值 | 作用 |
|---|---|---|
| `LLAMA_CPP_ENABLED` | 除非为 `false`，否则开启 | 用于 embedding/rerank 的本地 llama.cpp 服务器 |
| `LLAMA_CPP_PORT` / `RERANKER_PORT` | `8080` / `8081` | llama.cpp 与 BGE-M3 端点 |
| `LM_STUDIO_HOST` / `LM_STUDIO_PORT` | `127.0.0.1` / `1234` | LM Studio provider |
| `OLLAMA_HOST` / `OLLAMA_PORT` | `127.0.0.1` / `11434` | Ollama provider |
| `EMBEDDING_MODEL` / `MODEL_NAME` / `EMBEDDING_DIMENSION` | `qwen3-embedding` / `multilingual-e5-small-int8` / `384` | provider 模型选择 |
| `MSCODEBASE_ONNX_PROVIDER` | — | 强制指定 ONNX 执行 provider |
| `MSCODEBASE_REMOTE_TOKEN` / `_REMOTE_RATE_LIMIT_RPS` | — | 远程 provider 认证与速率限制 |
| `MSCODEBASE_LANGUAGE_PACK` | `false` | 启用 tree-sitter-language-pack（首次使用时下载 parser） |

## 6. 安全与信任

| 变量 | 默认值 | 作用 |
|---|---|---|
| `MSCODEBASE_TRUSTED_ROOTS` | 项目根目录 | 工具可读写的路径 |
| `MSCODEBASE_RESTRICTED_READ` | 关闭 | 把读取限制在受信任根目录内 |
| `MSCODEBASE_SANDBOX_MODE` | 关闭 | 额外的写限制 |
| `MSCODEBASE_ALLOW_SELF_INDEX` | 关闭 | 允许索引服务器自身的 checkout（仅 CI） |
| `MSCODEBASE_ACK_SECRET` | 派生 | `ack_impact` 令牌的 HMAC 密钥 |

安全细节与威胁模型：[SECURITY.md](SECURITY.md)。

## 7. Hooks 与门禁

| 变量 | 默认值 | 作用 |
|---|---|---|
| `MSCODEBASE_STALE_GATE` | `block` | OpenCode 插件中文档漂移门禁的 `block` / `off` |
| `MSCODEBASE_ISOLATION_GATE` | `advisory` | 图隔离的 `advisory` / `block` / `off` |
| `MSCODEBASE_GATE_LOG` | `%TEMP%/opencode/mscodebase_gate.log` | 插件日志路径 |
| `MSCODEBASE_PY` | `<repo>/venv/Scripts/python.exe` | 插件调用的解释器 |
| `MSCODEBASE_AUTODOC_LEDGERS` | 关闭 | 允许 AutoDocUpdater 改写 agent 所属的台账 |
| `MSCB_PRECOMMIT_FAST` / `MSCB_PRECOMMIT_GATE_TIMEOUT` | — / `900` | pre-commit 快捷方式与预算 |

每个门禁具体检查什么，见 [HOOKS_AND_GATES.md](HOOKS_AND_GATES.md)。

## 8. 如何验证一项改动

```bash
python -c "from src.config.settings import get_config; c=get_config(); print(c.search.dense_off, c.search.docs_margin)"
```

配置在每个进程中只构建一次：修改 `.env` 后重启 MCP 宿主，随后
`get_health_report()` 应显示新值（至少不应再显示旧的 provider 状态）。

## 9. 代码引用（2026-11-12 审计）

| 分组 | 读取位置 |
|---|---|
| server/profile/storage（`MSCODEBASE_MCP_PROFILE`、`MSCODEBASE_DATA_DIR` 等） | `src/config/settings.py`、`src/mcp/server_tools.py::CORE_PROFILE`、`src/core/artifact_paths.py::get_data_root` |
| 检索默认值（`MSCODEBASE_DOCS_MARGIN`、`_ONDEMAND_RERANK_*`、`_CODE_BM25_*`） | `src/config/settings.py::SearchConfig`（第 189–268 行） |
| `MAX_FILE_SIZE_MB`（无前缀） | `src/config/settings.py::SecurityConfig`（第 425 行） |
| 插件门禁（`MSCODEBASE_STALE_GATE`、`_ISOLATION_GATE`、`_GATE_LOG`、`MSCODEBASE_PY`） | `.opencode/plugin/mscodebase_gate.ts`（第 25–27 行） |
| pre-commit 预算（`MSCB_PRECOMMIT_FAST`、`MSCB_PRECOMMIT_GATE_TIMEOUT`） | `.githooks/pre-commit`（第 33、153 行） |

当上表中的名称在代码里消失时，`python scripts/check_docs_vs_config.py` 会失败。
