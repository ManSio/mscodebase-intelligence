# 搜索流水线 — 当前契约

> **更新于 2026-10-25。** 默认运行时是 Phase 3 text-first：SQLite FTS5/BM25 +
> PropertyGraph。Dense、LanceDB 和 reranker 阶段可选，未配置时关闭。本文描述
> 默认路径的真实行为，而不是把旧 pipeline 当作默认。

---

## 1. 契约

输入：

- natural-language 或 identifier query；
- `mode`：`fast`、`quality`、`deep`、`context`、`ask`、`auto`；
- 可选 `layer`、`intent`、`limit`、`explain`。

输出：

- 带 metadata 的 ranked chunks/files（`file`、`chunk_index`、`symbol_name`、
  `symbol_kind`、`layer`、line range、source）；
- freshness check 失败时的 stale-index banner；
- 不可信索引内容的安全 metadata（可选）。

Agent 可传 `intent="docs"` 或 `intent="code"`。`intent` 为空时，tool 比较最佳
docs-only BM25 score 与最佳 code score；差值超过
`MSCODEBASE_DOCS_MARGIN`（默认 `4.0`）时走 docs 通道。此决策没有 LLM。

## 2. 默认 Phase 3 路径

```text
query
  │
  ├─ normalize / optional RU synonyms
  │
  ├─ SQLiteChunkStore.search(query, limit=20..50)
  │     └─ FTS5/BM25 over chunk text, symbol_name, docstring, file_path
  │
  ├─ 如果 query 像 identifier/path：
  │     └─ PropertyGraph stage 添加 exact symbol/file candidates
  │
  ├─ optional on-demand rerank（仅配置时）
  │
  ├─ exact-name boost
  ├─ symbol deduplication
  │
  └─ return top-N
```

SQLite 路径刻意比历史 LanceDB pipeline 更短。默认**不会**运行 BM25+dense+graph
的 RRF、MMR、co-change boosts 或 P3 module-head anchors。这些阶段属于可选
dense/LanceDB 路径或旧代码路径。

## 3. Candidate 来源

### 3.1 SQLite FTS5/BM25

`SQLiteChunkStore.search` 从查询词构造 FTS5 `MATCH`（OR、quoted），用 SQLite
`bm25()` 排序，返回：

- chunk text 和 full text；
- file path、chunk index、symbol name/kind、docstring、layer；
- start/end line；
- 由 BM25 rank 得到的 `final_score`。

表是 content-linked（`content='chunks'`），带 insert/update/delete triggers；
删除文件会自动删除对应 FTS rows。

### 3.2 符号与路径信号

Identifier-shaped 查询（`snake_case`、`CamelCase`、paths、`::`）会走确定性的
graph stage。图返回 exact definition/reference rows，避免 FTS 把它们排在通用
文本匹配之后。按 `file + chunk_index` 去重。

### 3.3 文档通道

`Searcher.search_docs()` 使用同一 FTS5 store，只保留 `docs/**`。它把语言变体
（`docs/en/X`、`docs/ru/X`、`docs/zh/X`）折叠为一个 key，并优先查询语言。
这是独立通道，不改变代码 ranking。

### 3.4 可选 dense/vector path

当 `MSCODEBASE_DENSE_OFF=false` 且 provider 可用时，vector search 走 LanceDB
或配置的 backend。该路径可增加 candidates，但不是默认契约的必需项。

## 4. Ranking 与 fusion

默认 Phase 3：

1. SQLite 的 BM25 顺序；
2. identifier 查询追加 graph candidates；
3. 可选 on-demand rerank top pool；
4. identifier 查询的 exact-name boost；
5. 按 symbol 去重。

可选/历史路径：

- BM25、dense、FTS5 的 reciprocal rank fusion；
- 按 intent 和文件类型做 bucket weighting；
- co-change 和 exact-symbol boosts；
- non-code demotion（`tests/`、`docs/`、`experiments/`、`fixtures/`）；
- MMR diversification；
- identifier anchors 和 P3 module-head anchors；
- multi-provider reranking。

这些阶段可配置，不会应用到每个查询。不要用旧 pipeline 描述预测默认结果顺序。

## 5. 文档路由

路由是一次廉价比较：

```text
docs_max = docs/** 中最佳 BM25 score
code_max = src/**、tools/**、scripts/**、tests/** 中最佳 BM25 score
if docs_max - code_max > MSCODEBASE_DOCS_MARGIN:
    use search_docs()
else:
    use code search
```

特性：

- 一次额外 FTS 查询，无模型调用；
- 显式 `intent` 覆盖启发式；
- threshold 可配置，并在 48 查询面板上调过；
- 带强文档词汇的代码查询仍可能误判；`intent="code"` 是退路。

面板上 margin `4.0` 得到 0 个 code false positive、8 个 docs 问题中 5 个
top-1，以及总体 0.792 same-basename hit@1。这是面板结果，不是通用常数。

## 6. 模式

| Mode | 路径 | 用途 |
|---|---|---|
| `fast` | FTS5 + 可选 dense；无 reranker | 精确名称、已知路径、低延迟 |
| `quality` | 默认 hybrid + 可选 rerank | 常规代码/文档问题 |
| `deep` | Quality + graph context expansion | 跨模块调查 |
| `context` | 按片段做相似代码搜索 | 查找相似实现 |
| `ask` | Retrieval + 可选本地 LLM 生成 | 仅在配置 LLM profile 时 |
| `auto` | 按查询形态选择模式 | 默认 tool 入口 |

在内部面板上，`fast` 在混合自然语言问题上明显不如 `quality`（0.542 vs
0.688 hit@1）。请有意识地使用。

## 7. 可选层

| 层 | 开关 / 条件 | 效果 |
|---|---|---|
| Dense retrieval | `MSCODEBASE_DENSE_OFF=false` + provider | 增加 vector candidates |
| On-demand rerank | `MSCODEBASE_ONDEMAND_RERANK=true` + provider | 重排 top candidates |
| P3 module-head anchors | `MSCODEBASE_P3_ANCHOR=true` | 增加 module-head chunks |
| RU synonyms | `MSCODEBASE_RU_SYNONYMS=true` | 扩展俄语查询变体 |
| Non-code demotion | `MSCODEBASE_DEMOTE_NON_CODE=true` | 降低 tests/docs/experiments |
| Intent-aware demotion | `MSCODEBASE_DEMOTE_INTENT_AWARE=true` | docs intent 时保留 docs |
| Docs auto-route | `MSCODEBASE_DOCS_MARGIN` | 选择 docs/code 通道 |

## 8. 输出契约

每个结果携带足够 metadata：

- `file`、`chunk_index`、`start_line`、`end_line`；
- `symbol_name`、`symbol_kind`、`layer`；
- `final_score` 和 `source`（`sqlite_fts5`、`graph`、`docs_fts` 等）；
- 可选 `docstring`、callers/callees、security flags。

Tool 响应可能包含 stale-index warning。Warning 不是搜索失败，而是提醒 agent
在信任 freshness 前刷新索引。

## 9. 测量行为

内部面板：48 个真实查询，clean index，排除 `experiments/**`，图存在。

| 路径 | hit@1 | hit@5 |
|---|---:|---:|
| Code, quality | 0.825 | 0.900 |
| Docs, exact path | 0.000 | 0.125 |
| Docs, same basename | 0.750 | 0.750 |
| Overall quality | 0.688 | 0.750 |
| Overall auto docs route | 0.792 | 0.875 |
| Fast | 0.542 | 0.729 |

边界：

- 这是内部面板，不是通用 benchmark；
- docs exact-path 会低估正确翻译；
- 没有静态配置或已测试的本地 reranker 达到 95% hit@1；
- two-channel repo map 在 1k/2k/4k token、理想 routing 下约 40/62/73%
  gold-file coverage；单独 PageRank 更低。

## 10. 调试搜索

```text
debug_runtime_passport()
intel_get_runtime_status()
codebase(action="index", path="status")
search_code(query="...", explain=true)
```

有用的检查：

1. `chunks.db` 是否非空？否则运行 `scripts/reindex_text_only.py`。
2. `graph.db` 是否为空？运行 `scripts/rebuild_graph.py`。
3. 查询像 docs？尝试 `intent="docs"` / `intent="code"`。
4. 在判定 docs miss 前，比较 exact-path 与 same-basename。
5. 对 `fast` vs `quality`，同一查询分别运行并比较。

## 11. 非目标

- 为每个查询使用 LLM router。路由是词法、廉价的。
- 用静态 repo map 替代迭代搜索。它是上下文选择，不是 oracle。
- 根据小型内部面板宣称 95% retrieval accuracy。
- 用自信回答掩盖空图或 stale index。
