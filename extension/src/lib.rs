// ═══════════════════════════════════════════════════════════════
// DRAFT — не использовать в production.
//
// Анализ (2026-07-11) показал, что Rust/WASM Context Server Extension
// теряет больше чем даёт:
//   - LSP-фичи (реалтайм диагностика, автокомплит, go-to-def)
//     не переносятся в MCP — ограничение протокола
//   - "Один клик" иллюзорен — Python venv + GGUF модели
//     всё равно требуют install.py
//   - Rust-тулчейн добавляет non-Python компонент в Python-проект
//
// Текущий подход: Python + extension.toml + install.py.
// Пересмотреть, когда Zed добавит Sampling/Elicitation в MCP,
// ИЛИ если zed::Project из context_server_command() решит multi-window.
// ═══════════════════════════════════════════════════════════════

use zed_extension_api::{self as zed, ContextServerCommand, Result};

const EXTENSION_ID: &str = "mscodebase-intelligence";

struct MSCodeBaseExtension;

impl zed::Extension for MSCodeBaseExtension {
    fn new() -> Self {
        Self
    }

    fn context_server_command(
        &mut self,
        _context: &zed::Context,
        _server_id: &str,
    ) -> Result<ContextServerCommand> {
        let ext_dir = zed::extension_dir(EXTENSION_ID)?;

        let venv_python = if cfg!(target_os = "windows") {
            ext_dir.join("venv").join("Scripts").join("python.exe")
        } else {
            ext_dir.join("venv").join("bin").join("python3")
        };

        if !venv_python.exists() {
            zed::set_language_context(EXTENSION_ID, "Installing dependencies...");

            let python = zed::which("python3".to_string())
                .or_else(|_| zed::which("python".to_string()))
                .map_err(|e| format!("Python not found: {}", e))?;

            zed::run(
                &python,
                &["-m", "venv", &venv_python.parent().unwrap().to_string_lossy()],
            )?;

            let pip = if cfg!(target_os = "windows") {
                venv_python.parent().unwrap().join("pip.exe")
            } else {
                venv_python.parent().unwrap().join("pip3")
            };
            zed::run(&pip, &["install", "-r", "requirements.txt"])?;

            zed::set_language_context(EXTENSION_ID, "");
        }

        Ok(ContextServerCommand {
            command: venv_python.to_string_lossy().to_string(),
            args: vec!["-u".to_string(), "-m".to_string(), "src.main".to_string()],
            env: vec![
                ("PYTHONPATH".to_string(), ".".to_string()),
                ("PROJECT_PATH".to_string(), "$ZED_WORKTREE_ROOT".to_string()),
            ],
        })
    }
}

zed::register_extension!(MSCodeBaseExtension);
