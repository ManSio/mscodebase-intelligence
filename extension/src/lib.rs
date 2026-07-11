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
        // Получаем путь к директории расширения (где лежит extension.toml)
        let ext_dir = zed::extension_dir(EXTENSION_ID)?;

        // Путь к venv скриптам
        let venv_python = if cfg!(target_os = "windows") {
            ext_dir.join("venv").join("Scripts").join("python.exe")
        } else {
            ext_dir.join("venv").join("bin").join("python3")
        };

        // Если venv не создан — запускаем установку
        if !venv_python.exists() {
            zed::set_language_context(EXTENSION_ID, "Установка зависимостей...");

            // Создаём venv
            let python = zed::which("python3".to_string())
                .or_else(|_| zed::which("python".to_string()))
                .map_err(|e| format!("Python не найден: {}", e))?;

            zed::run(
                &python,
                &["-m", "venv", &venv_python.parent().unwrap().to_string_lossy()],
            )?;

            // Устанавливаем зависимости
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
