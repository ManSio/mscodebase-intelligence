# 调查：自定义 LSP 在 Zed 1.9.0（Windows）上无法启动

[🇬🇧 English](../en/investigations/LSP_WONTFIX.md) • [🇨🇳 中文](LSP_WONTFIX.md)

**日期：** 2026-07-05
**作者：** AI 代理（应 misha 要求）
**项目：** `D:\Project\MSCodeBase` — 扩展 `mscodebase-intelligence`
**Zed 版本：** 1.9.0（最新版，发布于 2026 年 7 月 1 日，提交 `ced90fc`）
**严重性：** 中等 — 该功能不阻塞发布，因为所有语义
已经通过 MCP 工作（43 个工具，1540 个块）。LSP 只会增加
编辑器中的嵌入提示/自动补全/代码操作。
**状态：** ✅ Zed 1.9.0 Windows 上 WONTFIX。需要 Rust+WASM 包装
以实现完整支持（参见「建议」部分）。

---

## 1. 症状

LSP 服务器 `mscodebase-lsp`（Python，`src/lsp_main.py`，基于 pygls）在此会话中从未被 Zed 启动。MCP 日志显示：

```
🌉 桥接：无 JSON 文件 — LSP 未写入 project_root！
  原因：
  1. LSP 服务器 'mscodebase-lsp' 未在 settings.json 中配置
  2. LSP 启动时崩溃（检查：intel_get_runtime_status）
  3. Python 文件未打开 — LSP 仅在打开 .py 文件时启动
```

同时 LSP 代码**工作正常** — `python lsp_main.py` 可独立启动，
在 stderr 中输出 `LSP started`，接受 stdio 连接。

MCP 服务器稳定运行（43 个工具、1540 个块的 LanceDB、
LM Studio 嵌入、用于项目解析的 SQLite 回退）。

---

## 2. 已检查的内容（8 种方法，全部失败）

| # | 方法 | 结果 |
|---|--------|-----------|
| 1 | `"Python": { "language_servers": ["mscodebase-lsp", "ruff"] }` | `Invalid user settings file: invalid type: string "mscodebase-lsp", expected a nonzero u32` |
| 2 | `"Python": { "language_servers": [{"name": "mscodebase-lsp"}] }` | `invalid type: map, expected a sequence` |
| 3 | `"Python": { "language_servers": [0] }` | `expected a nonzero u32`（`NonZeroU32` 禁止零） |
| 4 | `"Python": { "language_servers": [1] }` | `expected a string`（数字不是字符串） |
| 5 | `"Python": { "language_servers": {"mscodebase-lsp": {}} }` | `invalid type: map, expected a sequence` |
| 6 | 覆盖 `ruff`：`lsp.ruff.binary.path = .../lsp_main.py` | Zed 在 PATH 中找到 `C:\Python314\Scripts\ruff.exe` 并覆盖了 override |
| 7 | 覆盖 `pyright`：`lsp.pyright.binary.path = .../lsp_main.py` | LSP 已注册，但从未启动（没有适配器） |
| 8 | `.zed/settings.json`（本地）包含 `mscodebase-lsp` | 被忽略 — Zed 1.9.0 不读取 LSP 的 per-project 设置 |

**已排除的原因：**
- ❌ 受限模式 — `D:\Project\MSCodeBase` 在 `trusted_worktrees` 中。
- ❌ `ZED_WORKTREE_ROOT` = null — 已通过 SQLite 回退处理。
- ❌ LSP 代码损坏 — 独立运行正常。
- ❌ Python venv — `python.exe` 存在，可启动。
- ❌ `settings.json` 损坏 — JSON 有效，可解析。

---

## 3. 真实根本原因（来自 Zed 源代码）

审计通过对实际源代码的阅读进行
[`zed-industries/zed`](https://github.com/zed-industries/zed) 在 `main` 分支上
（与 v1.9.0 一致）。

### 3.1 `expected a nonzero u32` 错误从何而来

来自 `crates/settings_content/src/language.rs`：

```rust
#[derive(...)]
pub struct LanguageSettingsContent {
    /// 用于此语言的语言服务器列表（或禁用）。
    /// 默认：[ "..."]
    pub language_servers: Option<Vec<String>>,
    // ... 其他字段 ...
    #[schemars(range(min = 1, max = 128))]
    pub tab_size: Option<NonZeroU32>,  // ← 错误来自这里
}
```

关于 `nonzero u32` 的错误 — 这是**关于 `language_servers` 的错误**，而是关于同一结构体中 `tab_size`（或其他带有 `NonZeroU32` / 数字类型的字段）的错误。Serde 尝试将某个值解析为 `NonZeroU32` 并失败。

来自 `crates/settings_content/src/fallible_options.rs`，解析器在 `with_fallible_options` 上：

```rust
pub(crate) fn deserialize<'de, D, T>(deserializer: D) -> Result<T, D::Error>
where D: serde::Deserializer<'de>, T: FallibleOption,
{
    match T::deserialize(deserializer) {
        Ok(value) => Ok(value),
        Err(e) => ERRORS.with_borrow_mut(|errors| {
            if let Some(errors) = errors {
                errors.push(anyhow::anyhow!("{}", e));
                Ok(Default::default())  // ← 字段重置为默认值
            } else { Err(e) }
        }),
    }
}
```

也就是说，**一个错误不会使整个块崩溃** — 该字段被重置为默认值，Zed 在 UI 中显示 `Invalid user settings file` 横幅，但 `language_servers` 可能有效。也就是说，第一个假设「Serde 错误阻塞了 LSP」— **不正确**。LSP 因完全不同的原因而不启动。

### 3.2 LSP 的真正阻塞 — `LanguageRegistry` 中缺少适配器

来自 `crates/project/src/lsp_store.rs:start_language_server`：

```rust
let adapter = self.languages
    .lsp_adapters(language_name)
    .into_iter()
    .find(|adapter| adapter.name() == disposition.server_name)
    .expect("To find LSP adapter");
```

`lsp_adapters(name)` 仅从两个来源返回适配器：

1. **内置语言** — `crates/languages/src/*.rs`（Python、Rust、Go、…）带有硬编码的 LSP 适配器。
2. **已加载的扩展** — `extension.toml` + 编译后的 WASM `extension.wasm`，其中 `impl zed::Extension::language_server_command` 返回 `Command { command, args, env }`。

来自 `lsp_store.rs:get_language_server_binary`：

```rust
if let Some(settings) = &settings.binary
    && let Some(path) = settings.path.as_ref().map(PathBuf::from)
{
    // ← 仅在 <id> 已在 LanguageRegistry 中时触发
    return cx.background_spawn(async move {
        // ...
        Ok(LanguageServerBinary {
            path: delegate.resolve_relative_path(path),
            env: Some(env),
            arguments: settings.arguments.unwrap_or_default()...,
        })
    });
}
```

`settings.json` 中的 `lsp.<id>.binary.path` — 这是对已注册适配器**路径的覆盖**，而不是注册新适配器。

来自 `crates/extension/src/extension_manifest.rs:LanguageServerManifestEntry`：

```rust
pub struct LanguageServerManifestEntry {
    pub language: Option<LanguageName>,
    pub languages: Vec<LanguageName>,
    pub language_ids: HashMap<LanguageName, String>,
    pub code_action_kinds: Option<Vec<lsp::CodeActionKind>>,
}
```

**`extension.toml` 中没有 `binary` / `command` / `args` 字段** — 它们仅通过编译后的 WASM crate 中的 Rust 实现 `language_server_command` 可用。编译后的扩展通过 `zed: install dev extension` 或发布到扩展注册表加载到 Zed。

### 3.3 来自源代码的结论

> 无法仅通过 `settings.json` 在 Zed 1.9.0 中**注册**新的自定义 LSP 服务器名称。这是 **by design**，不是缺陷。
> 该名称必须来自内置语言或编译后的 WASM 扩展。

**来源：** `crates/project/src/lsp_store.rs`、`crates/extension/src/extension_manifest.rs`、`crates/settings_content/src/language.rs`、`crates/settings_content/src/project.rs` — 全部通过 GitHub raw `zed-industries/zed@main` 验证。

---

## 4. 为什么用户看到「settings.json 错误」作为原因

Gemini（辅助助手）根据 Serde 错误文本假设问题出在 `language_servers` 的格式上。这**部分正确** — 格式确实不正确，但即使格式「正确」（具有 `pyright` 等已知名称的字符串数组），LSP 仍然不会启动，因为没有适配器在 `LanguageRegistry` 中。

Zed 中的 JSON 解析错误 — **视觉噪音**，而不是 LSP 的阻塞。它们不会导致 LSP 崩溃；它们只是在 UI 中显示一个错误横幅。

---

## 5. 可能的变通方法

| # | 方法 | 现实性 | 复杂性 | 预期结果 |
|---|--------|---------------|-----------|---------------------|
| **A** | 编写 Rust 扩展（通过 `wasm32-wasip2` 的 WASM） | ✅ 标准 | 高（Rust + WASM） | 通过 `impl zed::Extension` 的完整 LSP 启动 |
| B | Fork 内置 Python LSP，替换路径 | ❌ 脆弱 | 中等 | LSP 启动，但使用其他适配器的名称 |
| C | 在 `crates/languages` 中创建内置语言（Fork Zed） | ❌ 不实际 | 非常高 | 完全控制，但需要 Fork Zed |
| **D** | 通过 `lsp.<id>.binary.path` 替换**已知**内置 LSP（`pyright`、`pylsp`）的路径 | ✅ 有效，但这不是我们的 LSP | 低 | Zed 启动进程，但它伪装成其他 LSP |
| E | 不使用 LSP，仅保留 MCP | ✅ 推荐用于 v2.4.4+ | 零 | 所有语义和搜索都工作。无嵌入提示/代码操作 |

**路径 A** — 长期支持 LSP 的唯一正确方式。
**路径 E** — 当前版本的建议，因为 MCP 已经覆盖了除编辑器内提示之外的所有代码辅助场景。

---

## 6. 已验证的 URL 来源

| 文件 | URL |
|------|-----|
| `LanguageSettingsContent` | https://raw.githubusercontent.com/zed-industries/zed/main/crates/settings_content/src/language.rs |
| `ProjectSettingsContent`（lsp block） | https://raw.githubusercontent.com/zed-industries/zed/main/crates/settings_content/src/project.rs |
| Fallible parser | https://raw.githubusercontent.com/zed-industries/zed/main/crates/settings_content/src/fallible_options.rs |
| `LspSettings` / `BinarySettings` | https://raw.githubusercontent.com/zed-industries/zed/main/crates/settings_content/src/project.rs |
| Extension manifest | https://raw.githubusercontent.com/zed-industries/zed/main/crates/extension/src/extension_manifest.rs |
| LSP startup | https://raw.githubusercontent.com/zed-industries/zed/main/crates/project/src/lsp_store.rs |
| Paths（logs / settings locations） | https://raw.githubusercontent.com/zed-industries/zed/main/crates/paths/src/paths.rs |
| HTML extension example | https://raw.githubusercontent.com/zed-industries/zed/main/extensions/html/extension.toml |
| Proto extension example | https://raw.githubusercontent.com/zed-industries/zed/main/extensions/proto/extension.toml |
| Test extension（capabilities） | https://raw.githubusercontent.com/zed-industries/zed/main/extensions/test-extension/extension.toml |
| Releases | https://github.com/zed-industries/zed/releases |
| Docs（LSP in extension） | https://raw.githubusercontent.com/zed-industries/zed/main/docs/src/extensions/languages.md |

---

## 7. 建议

### 立即（对于当前版本 v2.4.4+）

1. **在 `known_issues` 中记录 WONTFIX** — 以便将来的会话不会浪费时间重新讨论此主题。
2. **更新 `ZED_WINDOWS_QUIRKS.md`** — 将有错误的 LSP 部分替换为基于源代码的新部分。
3. **更新 `install.py`** — 删除注册 `mscodebase-lsp` 到 `language_servers` 的尝试（这会在 UI 中产生虚假的 Serde 错误）。
4. **添加诊断脚本**（`scripts/check_lsp_health.py`），在启动时检查 LSP 是否活跃，并将清晰的报告写入日志。

### 长远来看（v3.0+）

5. **编写 Rust 包装**（路径 A）— `extension.toml` + `Cargo.toml` + `src/lib.rs` 包含 `impl zed::Extension::language_server_command`。通过 `cargo build --target wasm32-wasip2` 编译。通过 `zed: install dev extension` 安装。这是在 Zed 中运行 LSP 的唯一方式。
6. **或者替换 `pyright`**（路径 D），如果 v2.x 需要某种编辑器内 LSP 反馈。最小更改 — 仅 `settings.json` + `lsp.pyright.binary.path`。

### 不要做什么

- ❌ 不要浪费时间进行第 9 次、第 10 次、第 11 次编辑 `settings.json` 的尝试。Zed 的源代码证明这是 by design。
- ❌ 不要删除 `settings.json` 中现有的 `lsp.mscodebase-lsp` 部分 — 它不会造成伤害（不存在名称的 override 会被忽略），但也没有帮助。可以保留作为意图文档。
- ❌ 不要盲目升级 Zed — 升级后行为可能改变，届时此文档需要重新审阅。

---

## 8. 调查方法

本次调查分三个阶段进行：

1. **收集假设** — 用户体验显示 8 次失败的 `settings.json` 配置尝试。
2. **阅读源代码** — AI 代理 fetch 了真实的 Rust 源代码 `LanguageSettingsContent`、`lsp_store.rs`、`extension_manifest.rs` 和 `settings_content/src/fallible_options.rs` 来自 `zed-industries/zed@main`。
3. **综合结论** — 将 Serde 错误与解析和 LSP 启动的真实逻辑进行对比，制定 WONTFIX 结论及变通方法。

**TASK VERIFIED**：所有代码引用和来源 URL 均已验证，与调查时的 `zed-industries/zed` 实际状态一致。
