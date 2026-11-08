# 搜索流水线

> 翻译：2026-11-08，来源 docs/en/SEARCH_PIPELINE.md。英文版为准。

> 2026-11-08 重写。默认运行时是 **Phase 3 文本优先**：对解析后的 chunk 使用
> SQLite FTS5/BM25，外加 Tree-sitter/PropertyGraph。
> Dense、LanceDB 和 reranker 阶段存在，但都是可选的，文中均有标注。
> 数字见 [FACTS.md](../FACTS.md)。

## 1. 一次查询经历什么

```text
query
  │
  ├─ 1. Request guard        empty? >512 chars? → refuse with the reason
  │
  ├─ 2. Freshness (throttled) changed/new files → reindex in the background
  │
  ├─ 3. Candidate retrieval
  │       identifier-shaped?  → graph stage (exact location, ~ms)
  │       otherwise           → SQLite FTS5/BM25 over chunks.db
  │
  ├─ 4. Enrichment            symbol/path signals, layer filter, dedup
  │
  ├─ 5. Rerank (optional)     live embeddings over the top pool
  │
  ├─ 6. Docs routing          docs FTS score − code score > margin → docs
  │
  └─ 7. Format                file:line, symbol, score, warnings
```

## 2. Phase 3 路径（默认）

`Searcher._sqlite_hybrid_search_async`：

1. **候选** —— `SQLiteChunkStore.search(query, raw_limit)`，其中
   `raw_limit = min(max(limit × 4, 20), 50)`。存储层返回基于 chunk 文本的 FTS5
   BM25 结果（当 `MSCODEBASE_AUGMENT_CHUNKS=true` 时，FILE/SYMBOLS/DOC 会被
   前置到文本中）。
2. **过滤** —— 可选的 `layer`（core/mcp/utils/tests/...）作用于候选集。
3. **Rerank（可选）** —— 在 `MSCODEBASE_ONDEMAND_RERANK=true`（默认）时，
   前 `MSCODEBASE_ONDEMAND_RERANK_TOP_N` 个候选会用实时 embedding 重新打分；
   文本在 embedding 前被截断到 `..._MAX_CHARS`。没有 provider 时该阶段被跳过，
   而不是失败。
4. **成形** —— 结果携带 `file_path`、`line`、`symbol_name`、`text`、
   `score`、`source`（`sqlite_fts5`）。

这条路径从不访问 LanceDB，因此完全不需要向量表也能工作。

## 3. 标识符短路

形如标识符的查询（`_IDENTIFIER_QUERY_RE`）跳过检索，进入图阶段，由它解析定义
及其直接邻居。代码注释中的实测值：约 6.8 ms，而向量搜索需要数秒。非标识符问题
不会产生图命中，会落回常规路径。

## 4. 文档路由（E57）

`Searcher.prefers_docs(query)` 对 `docs/**` 额外执行一次 FTS 查询，并比较最佳
docs 分数与最佳 code 分数：

```
docs_max − code_max > MSCODEBASE_DOCS_MARGIN (default 4.0)  → docs channel
```

- 该步骤没有 LLM；它只是一次查询加一次减法。
- 显式指定 `intent="docs"` 或 `intent="code"` 会覆盖自动选择。
- `search_docs` 会对翻译去重（ru/en/zh）并优先查询语言，因此 `docs/ru/X.md` 与
  `docs/en/X.md` 计为同一文档。
- 冻结面板上的实测效果：同名文件 hit@1 从 0.688 提升到 0.792，margin 为 4.0 时
  代码误报为零。

## 5. `investigate` —— 一个问题，多个通道

`investigate(query, limit=8)` 是默认入口，也是模型不必再自行选择工具的原因。

**第 1 轮（并行，每个 12 s）：**

| 通道 | 运行内容 | 权重 |
|---|---|---:|
| `search` | SQLite FTS5/BM25 混合检索、文档路由 | 0.6 |
| `symbols` | 对每个标识符调用 `symbol_index.search_symbols` | 1.0 |
| `grep` | 对最具代码特征的两个标识符做正则匹配，AST 作用域，15 s | 0.3 |

**第 2 轮（并行，仅当第 1 轮产出了文件/标识符）：**

| 通道 | 询问内容 | 权重 |
|---|---|---:|
| `impact` | top 标识符的影响半径 | 1.2 |
| `graph` | top 标识符的直接调用者 | 1.0 |
| `tests` | 哪些测试覆盖 top 文件（测试文件本身跳过） | 0.1 |
| `memory` | 与问题共享 token 的 ADR/incident 节点 | 0.4 |

**合并：** 键为 `(file, line)`；通道取并集（`[search+graph]`），排名为
`score + weight`，行先按通道数量排序，再按排名排序。输出有上限（8 行，每行
180 字符）。

**失败：** 抛异常或超出预算的通道会列入 `degraded[]`
（`grep:timeout`、`impact:AttributeError`）；其余答案仍会返回。无命中的查询返回
“未找到”——绝不给出看似合理的猜测。

## 6. 预算与保护

| 层级 | 预算 | 超时时 |
|---|---|---|
| `search_code` | 15 s（重试 1 次） | 结构化超时错误 |
| `investigate` | 外层 30 s，每通道 12 s，grep 15 s | `degraded[]`，部分答案 |
| `grep_code` | 45 s | 结构化超时错误 |
| `get_symbol_info` / `impact_analysis` | 15–20 s | 结构化错误 |
| 查询长度 | 512 字符 | 拒绝并给出长度 |
| 扫描文件数（grep） | 4 000；每文件 1 MB | 跳过并计数 |
| 模式长度（grep） | 512 字符 | 拒绝 |

## 7. 流水线不做什么

- **不要求 embedding。** 默认路径用 FTS5 和图作答。
- **没有 LLM 路由。** 文档路由是分数比较，不是模型调用。
- **默认路径不对 BM25+dense+graph 做 RRF/MMR。** 那些只存在于 legacy dense 路径；
  把其混入每次查询并未测出更好的结果。
- **不宣称 95%。** 实测快照与生成它的 harness 见 [FACTS.md](../FACTS.md)。

## 8. 如何诊断坏结果

1. `tool_help()` → 是否处于 `core`，预期的工具是否可见？
2. `codebase(action="index", path="status")` → chunks > 0，files > 0？
3. 用 `search_code(..., mode="quality")` 和 `grep_code(..., scope="all")` 重跑
   同一查询 → 是检索漏了，还是排序重排了？
4. `investigate(...)` → 哪些通道找到了该文件（`[search]`、`[grep]`）？
5. 检查日志尾部：`%LOCALAPPDATA%/mscodebase/logs/mcp_global.log`。
