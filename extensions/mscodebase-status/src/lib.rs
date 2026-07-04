use std::collections::HashMap;
use zed_extension_api::{
    self as zed, Command, LanguageServerId, ProjectPath, Result, serde_json, Settings,
};

/// Структура расширения MSCodeBase Status.
/// Управляет статус-баром, командами и JSON-RPC связью с Python-сервером.
struct MscodebaseExtension {
    /// ID LSP-сервера (он же наш stdio-канал к Python)
    language_server: Option<LanguageServerId>,
    /// Ссылка на статус-бар элемент
    status_bar: Option<zed::StatusBarItem>,
    /// Кэш последнего полученного статуса
    last_status: StatusCache,
}

/// Кэш статусов для быстрого отображения
#[derive(Default)]
struct StatusCache {
    indexing_progress: u8,     // 0-100
    indexing_file: String,     // текущий файл
    circuit_breaker: String,   // OPEN / CLOSED / HALF_OPEN
    embedder: String,          // LM Studio / Ollama / ONNX
    total_chunks: u64,
}

impl MscodebaseExtension {
    fn new() -> Self {
        Self {
            language_server: None,
            status_bar: None,
            last_status: StatusCache::default(),
        }
    }

    /// Обновляет текст в статус-баре
    fn update_status_bar(&mut self, text: &str) {
        if let Some(ref mut bar) = self.status_bar {
            bar.set_text(text);
        }
    }

    /// Отправляет JSON-RPC запрос к Python-серверу
    fn send_request(&self, method: &str, params: &str) -> Result<String> {
        if let Some(server_id) = &self.language_server {
            zed::Editor::language_server_request(server_id, method, params)
        } else {
            Err("Language server not initialized".to_string())
        }
    }

    /// Обрабатывает push-уведомления от NotificationBroker (Python → Zed)
    fn handle_notification(&mut self, method: &str, params: &str) -> Result<()> {
        let json: serde_json::Value = serde_json::from_str(params)
            .map_err(|e| format!("Invalid JSON: {}", e))?;

        match method {
            "mscodebase/indexing_status" => {
                let status = json["status"].as_str().unwrap_or("idle");
                let progress = json["progress"].as_u64().unwrap_or(0);
                let chunks = json["total_chunks"].as_u64().unwrap_or(0);
                let file = json["current_file"].as_str().unwrap_or("");

                self.last_status.indexing_progress = progress as u8;
                self.last_status.total_chunks = chunks;
                self.last_status.indexing_file = file.to_string();

                if status == "indexing" {
                    self.update_status_bar(&format!("⏳ Indexing: {}%", progress));
                } else {
                    self.update_status_bar(&format!(
                        "📊 {} chunks | 🟢 {}",
                        chunks,
                        self.last_status.embedder
                    ));
                }
            }
            "mscodebase/system_health" => {
                let cb = json["circuit_breaker"].as_str().unwrap_or("CLOSED");
                let fallback = json["fallback_active"].as_bool().unwrap_or(false);
                let embedder = json["embedder"].as_str().unwrap_or("?");

                self.last_status.circuit_breaker = cb.to_string();
                self.last_status.embedder = embedder.to_string();

                if cb == "OPEN" {
                    self.update_status_bar("⚠️ LM Studio Offline");
                } else if fallback {
                    self.update_status_bar("🟡 Fallback: Lexical Search");
                } else if self.last_status.total_chunks > 0 {
                    self.update_status_bar(&format!("📊 {} chunks | 🟢 {}",
                        self.last_status.total_chunks, embedder));
                }
            }
            "mscodebase/diagnostics_update" => {
                if let Some(diags) = json["diagnostics"].as_array() {
                    for diag in diags {
                        let msg = diag["message"].as_str().unwrap_or("Unknown error");
                        zed::Editor::show_diagnostic(&zed::Diagnostic {
                            severity: zed::DiagnosticSeverity::Warning,
                            message: msg.to_string(),
                            source: Some("MSCodeBase".to_string()),
                            path: diag["file_path"].as_str().unwrap_or(""),
                            range: zed::Range {
                                start: zed::Point {
                                    row: diag["range"]["start"]["line"].as_u64().unwrap_or(0) as u32,
                                    column: 0,
                                },
                                end: zed::Point {
                                    row: diag["range"]["end"]["line"].as_u64().unwrap_or(0) as u32,
                                    column: 0,
                                },
                            },
                        });
                    }
                }
            }
            _ => {}
        }
        Ok(())
    }
}

impl zed::Extension for MscodebaseExtension {
    fn new() -> Self {
        MscodebaseExtension::new()
    }

    /// Инициализация при старте расширения
    fn initialize(
        &mut self,
        _context: &mut zed::ExtensionContext,
    ) -> Result<()> {
        // Регистрируем команды палитры
        _context.register_command(
            "mscodebase: trigger-full-reindex",
            |this: &mut Self, _params: &str| -> Result<String> {
                let result = this.send_request("mscodebase/force_reindex", r#"{}"#)?;
                Ok(result)
            },
        );

        _context.register_command(
            "mscodebase: show-dashboard",
            |this: &mut Self, _params: &str| -> Result<String> {
                let dashboard = this.send_request("mscodebase/get_dashboard", r#"{}"#)?;
                // Открываем дашборд в виртуальном буфере
                zed::Editor::open_buffer(&zed::BufferOptions {
                    uri: "mscodebase://dashboard.md",
                    content: &dashboard,
                    read_only: true,
                })?;
                Ok("Dashboard opened".to_string())
            },
        );

        _context.register_command(
            "mscodebase: clear-project-memory",
            |this: &mut Self, _params: &str| -> Result<String> {
                this.send_request("mscodebase/clear_memory", r#"{}"#)
            },
        );

        // Создаём элемент статус-бара
        let mut bar = zed::StatusBarItem::new("📊 ...");
        bar.set_tooltip("MSCodeBase Intelligence — click for dashboard");
        self.status_bar = Some(bar);

        Ok(())
    }

    /// Запуск LSP-сервера (наш Python MCP-сервер)
    fn language_server_command(
        &mut self,
        language_server_id: &LanguageServerId,
        _workspace: &zed::Workspace,
    ) -> Result<Command> {
        self.language_server = Some(language_server_id.clone());

        // Путь к Python-серверу берётся из настроек или из окружения
        let settings = Settings::get("mscodebase-status", "python_path")
            .unwrap_or_else(|| "python".to_string());

        // Определяем корень проекта через env или CWD
        let project_root = std::env::var("PROJECT_PATH")
            .or_else(|_| std::env::var("ZED_WORKTREE_ROOT"))
            .unwrap_or_else(|_| ".".to_string());

        Ok(Command {
            command: settings,
            args: vec![
                "-u".to_string(),
                "-m".to_string(),
                "src.main".to_string(),
            ],
            env: vec![
                ("PROJECT_PATH".to_string(), project_root),
                ("PYTHONPATH".to_string(), std::env::current_dir()
                    .map(|p| p.to_string_lossy().to_string())
                    .unwrap_or_default()),
            ],
            // Проброс stderr Python-процесса в логи Zed для отладки крэшей
            stderr: Some(zed::StderrBehavior::Log),
        })
    }

    /// Обработка кастомных JSON-RPC уведомлений от сервера
    fn handle_notification(
        &mut self,
        _language_server_id: &LanguageServerId,
        method: &str,
        params: &str,
    ) -> Result<()> {
        self.handle_notification(method, params)
    }

    /// Обработка запросов (от сервера к расширению)
    fn handle_request(
        &mut self,
        _language_server_id: &LanguageServerId,
        method: &str,
        _params: &str,
    ) -> Result<String> {
        match method {
            "heartbeat_ping" => Ok("{}".to_string()),
            _ => Ok("{}".to_string()),
        }
    }

    /// Событие при сохранении документа — уведомляем сервер
    fn on_save(&mut self, _workspace: &zed::Workspace, _project_path: &ProjectPath) {
        if let Some(server_id) = &self.language_server {
            // Уведомляем сервер о сохранении для синхронизации
            let _ = zed::Editor::language_server_notification(
                server_id,
                "mscodebase/buffer_sync",
                r#"{"path": "sync", "content": ""}"#,
            );
        }
    }
}

zed::register_extension!(MscodebaseExtension);
