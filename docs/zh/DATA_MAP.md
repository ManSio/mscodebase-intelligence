# MSCodeBase 数据存放位置

> 编写于 2026-11-12，已对照 `install.py` v3.2、`src/core/artifact_paths.py`、
> `src/core/artifact_gc.py`、`src/core/log_manager.py`、
> `src/sources/git_url/__init__.py` 以及一次真实的 `install.py --doctor` 运行核实。
> 数字为实测，不是估算。

本页回答一个问题：*安装器与服务器在磁盘上创建了什么，每个路径归谁，如何清除？*

```bash
python install.py --doctor              # 装了什么、占多少空间
python install.py --clean --dry-run     # 只列路径与大小，不删除
python install.py --clean --yes         # 删除下面所有层
```

## 1. 四个层

| 层 | 默认路径 | 创建者 | 内容 |
|---|---|---|---|
| **安装根** | Windows `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence`；macOS `~/Library/Application Support/Zed/extensions/…`；Linux `~/.local/share/zed/extensions/…` | `install.py`：`step_copy`、`step_venv`、`step_pip`、`step_llama`、`step_gguf`、`step_models`、`step_uninst` | 已安装副本：代码、`venv/`、可选模型、卸载器 |
| **数据根** | `%LOCALAPPDATA%\mscodebase`（Win）· `$XDG_CACHE_HOME/mscodebase` 或 `~/.cache/mscodebase`（POSIX） | `src/core/artifact_paths.py::get_data_root` | 项目缓存、日志、共享模型、仓库克隆 |
| **项目产物** | `<project>/.mscodebase/chunks.db` | 服务器（`MSCODEBASE_SQLITE_CHUNKS`） | 该项目的 FTS5 文本索引 |
| **宿主配置** | Zed：`%APPDATA%\Zed\settings.json`（`context_servers`） | `install.py` 的 `step_zedcfg` → `adapters/zed/zed_config.py` | 一条让宿主启动服务器的条目 |

两个根都可重定位：`MSCODEBASE_INSTALL_ROOT` 与 `MSCODEBASE_DATA_DIR`
（后者仍接受历史别名 `BASE_INDEX_DIR`）。

## 2. 安装根内容

| 路径 | 归属 | 用途 | 大小 |
|---|---|---|---|
| `src/`、`scripts/`、`adapters/`、`locales/`、`docs/` | `step_copy`（`_sync_dir`） | 仓库的可执行副本（不含 `experiments/`） | 数 MB |
| `venv/` | `step_venv`、`step_pip` | 含锁定依赖的 Python 环境 | ~1 GB |
| `venv/Scripts/mscodebase-mcp.exe` | `pyproject.toml [project.scripts]` 的入口点 | 宿主启动的 stdio 命令 | — |
| `.codebase_models/onnx/…` | `step_models`（仅 `--with-models`） | ONNX 嵌入 + 重排模型 | ~657 MB |
| `llama_msvc/` | `step_llama` | GGUF 路径用的 llama-server | ~200 MB |
| `models/*.gguf` | `step_gguf`（仅 `--with-models`） | GGUF 嵌入 + 重排模型 | ~700 MB |
| `uninstall.bat` / `uninstall.sh` | `step_uninst`（`_build_uninstaller`） | 结束后台进程并删除本目录 | < 1 KB |
| `__mscodebase_ext__.marker` | `step_copy` | 告诉 `src/main.py` 当前运行的是已安装副本 | < 1 KB |

开发机实测（2026-11-12，已安装模型）：**3.0 GB / 28 429 个文件**，几乎全部是
`venv/` 与模型。

## 3. 数据根内容

| 路径 | 归属 | 用途 | 策略 |
|---|---|---|---|
| `projects/<hash8>/graph.db` | `artifact_paths.get_graph_db_path` | PropertyGraph：文件、符号、调用、导入 | 随项目目录一起删除 |
| `projects/<hash8>/lancedb_v2/` | `get_index_dir`、`get_db_path` | 向量索引（仅 dense 开启时） | 同上 |
| `projects/<hash8>/intelligence/` | `get_intelligence_dir` | 项目记忆：ADR、事件、技术债 | 同上 |
| `projects/<hash8>/metrics/` | `get_metrics_dir` | 索引任务历史（ETA 模型） | 同上 |
| `projects/<hash8>/commit_memory/` | `get_commit_memory_dir` | 提交语义缓存 | 同上 |
| `projects/<hash8>/branches/` | `get_branches_dir` | 按分支的索引状态 | 同上 |
| `projects/<hash8>/telemetry/` | `get_telemetry_dir` | 每日 JSON 快照 | 超过 **90 天**清理 |
| `projects/<hash8>/summaries_cache/` | `get_summaries_cache_dir` | 分块 LLM 摘要 | 同项目目录 |
| `projects/<hash8>/progress.json` | `get_progress_file` | 索引进度契约 | 覆盖写入 |
| `projects/<hash8>/action_receipts.jsonl` | `src/core/action_receipt.py` | 写操作回执 | verified 60 天 / inconclusive 7 天（`purge`） |
| `logs/mscodebase-intelligence.log` | `log_manager.get_main_log_path` | 服务器日志 | 2 MB × 3 文件轮转，**7 天**后删除 |
| `logs/crash.json` | `get_crash_log_path` | 最近一次资源监控崩溃 | 覆盖写入 |
| `models/.codebase_models/onnx/…` | `get_onnx_models_base` | 已下载模型的共享副本 | 仅 `--clean` |
| `repos/<hash8>/` | `get_repos_cache_dir` | 远程仓库克隆 | LRU(5) + 24 小时 TTL（`src/sources/git_url`） |
| `projects/<hash8>/`（整个目录） | — | — | 不活跃超过 **30 天**的目录与空目录由 `artifact_gc.prune_stale_artifacts()` 清理 |

开发机实测（2026-11-12）：**302.9 MB / 2 934 个文件**。
在同时含有 `chunks.db`（78 MB）与本地模型副本（960 MB）的真实项目目录中，
`--doctor` 对所有层报告 **4.3 GB / 31 385 个文件**。

## 4. 项目产物

| 路径 | 归属 | 用途 |
|---|---|---|
| `<project>/.mscodebase/chunks.db` | `MSCODEBASE_SQLITE_CHUNKS` 存储 | 默认搜索路径使用的文本索引（FTS5/BM25）；`--doctor` 报告其分块数 |
| `<project>/.codebase_indices/`、`.codebase/`、`.mscodebase/telemetry/` | 历史遗留 | 首次打开项目时迁入数据根（`artifact_paths.migrate_legacy_artifacts`） |
| `<project>/.codebase_models/` | `scripts/download_model.py`（暂存） | 模型安装到安装根之前的临时副本 |

`experiments/**` 按设计不参与索引，因此不会让索引增长。

## 5. 策略

- **模型为 opt-in。** `install.py` 默认 text-first：不带 `--with-models` 时不会发起
  任何模型下载，也不会创建模型目录。`--skip-models`/`--no-models` 仍被接受。
- **日志**按大小轮转（2 MB，3 个文件），7 天后删除
  （`log_manager._MAX_LOG_BYTES`、`_MAX_LOG_FILES`、`_LOG_RETENTION_DAYS`）。
- **遥测**保留 90 天；**不活跃项目目录**保留 30 天（`artifact_gc.DEFAULT_*`）；
  空项目目录立即删除。
- **仓库克隆**为 LRU(5) + 24 小时 TTL，并有 500 MB 克隆后上限
  （`git_url.DEFAULT_MAX_CLONE_BYTES`）。
- **共享模型缓存**（`data_root/models`）无 TTL：只能由 `install.py --clean` 删除。
- **卸载** = `install.py --clean --yes`，清除四层中的三层半，宿主配置条目除外
  （请自行从 `settings.json` / `opencode.json` / `.mcp.json` 删除 `mscodebase`
  条目，或用 `--no-zed` 安装，根本不创建它）。

## 6. 如何阅读 doctor 输出

```
+ install_root              3.0 GB  28429 file(s)  C:\Users\<user>\AppData\Local\Zed\extensions\mscodebase-intelligence
+ data_root               302.9 MB   2934 file(s)  C:\Users\<user>\AppData\Local\mscodebase
+ project_chunks           78.0 MB      4 file(s)  D:\work\repo\.mscodebase
   ...

index           7278 chunk(s)  (D:\work\repo\.mscodebase\chunks.db)
total           4.3 GB over 31385 file(s)
```

`+` 表示存在，`-` 表示不存在。`index missing` 表示当前目录的文本索引尚未建立
（首次 `codebase(action="index")` 会创建），而不是搜索损坏。`--json` 输出同样数据。
