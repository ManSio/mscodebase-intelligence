use zed_extension_api::{self as zed, LanguageServerId, Worktree, Result};

struct MscodebaseExtension;

impl zed::Extension for MscodebaseExtension {
    fn new() -> Self {
        Self
    }

    fn language_server_command(
        &mut self,
        _language_server_id: &LanguageServerId,
        _worktree: &Worktree,
    ) -> Result<zed_extension_api::process::Command> {
        Ok(zed_extension_api::process::Command {
            command: std::env::var("MSC_PYTHON").unwrap_or_else(|_| "python".to_string()),
            args: vec!["-u".to_string(), "-m".to_string(), "src.main".to_string()],
            env: vec![("PROJECT_PATH".to_string(), ".".to_string())],
        })
    }
}

zed::register_extension!(MscodebaseExtension);
