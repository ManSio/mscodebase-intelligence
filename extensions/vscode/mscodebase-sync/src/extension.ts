import * as vscode from "vscode";
import WebSocket from "ws";

/**
 * MSCodeBase Live Sync — расширение VS Code.
 *
 * Ловит изменения документов (onDidChangeTextDocument) и отправляет их в
 * демон MSCodeBase через WebSocket. Демон держит несохранённый текст в
 * RAM-оверлее (LiveBuffer) → индекс/поиск всегда свежие, без записи на диск.
 *
 * Ключевые отличия от наивного дизайна (Red Team):
 *  - НЕ шлём полный текст на каждую клавишу: debounce (по умолч. 350мс).
 *  - Порядок сообщений: монотонный `document.version` (last-writer-wins на
 *    сервере) — внеочередные WS-кадры не затирают свежее.
 *  - Reconnect с экспоненциальным backoff + jitter (а не фикс. 5с).
 *  - project_id = workspace-folder fsPath, определяется автоматически
 *    (extensionContext), без ручного ввода пути.
 */

let ws: WebSocket | null = null;
let reconnectTimer: NodeJS.Timeout | null = null;
let reconnectAttempt = 0;
const pendingByUri = new Map<string, vscode.TextDocument>();
let debounceTimer: NodeJS.Timeout | null = null;

interface SyncMsg {
  type: string;
  [key: string]: unknown;
}

function getConfig<T>(key: string): T {
  return vscode.workspace.getConfiguration("mscodebase").get<T>(key)!;
}

function currentProjectRoot(): string | null {
  const folder = vscode.workspace.workspaceFolders?.[0];
  return folder ? folder.uri.fsPath : null;
}

function shouldSync(doc: vscode.TextDocument): boolean {
  if (doc.uri.scheme !== "file") {
    return false;
  }
  // Игнорируем системные/большие папки, чтобы не спамить демон.
  const fsPath = doc.uri.fsPath;
  if (fsPath.includes("node_modules") || fsPath.includes(".git/")) {
    return false;
  }
  return true;
}

function send(msg: SyncMsg): void {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    return;
  }
  try {
    ws.send(JSON.stringify(msg));
  } catch (err) {
    console.error("[MSCodeBase] send error:", err);
  }
}

function scheduleFlush(): void {
  const debounceMs: number = getConfig<number>("debounceMs") || 350;
  if (debounceTimer) {
    clearTimeout(debounceTimer);
  }
  debounceTimer = setTimeout(flushPending, debounceMs);
}

function flushPending(): void {
  debounceTimer = null;
  const root = currentProjectRoot();
  if (!root) {
    return;
  }
  for (const [uri, doc] of pendingByUri) {
    send({
      type: "change",
      root,
      abs_path: doc.uri.fsPath,
      content: doc.getText(),
      version: doc.version,
    });
  }
  pendingByUri.clear();
}

function connectWebSocket(): void {
  const serverUrl = getConfig<string>("serverUrl");
  const authToken = getConfig<string>("authToken") || "";
  if (!serverUrl) {
    vscode.window.showErrorMessage("MSCodeBase: serverUrl не настроен");
    return;
  }

  const headers: Record<string, string> = {};
  if (authToken) {
    headers["Authorization"] = `Bearer ${authToken}`;
  }

  ws = new WebSocket(serverUrl, { headers });

  ws.on("open", () => {
    reconnectAttempt = 0;
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    vscode.window.setStatusBarMessage("MSCodeBase: синхронизация активна", 3000);

    const root = currentProjectRoot();
    if (root) {
      // hello: авто-регистрация проекта + ре-синк несохранённых (dirty) буферов.
      const dirty: Record<string, unknown>[] = [];
      for (const editor of vscode.window.visibleTextEditors) {
        const d = editor.document;
        if (shouldSync(d) && d.isDirty) {
          dirty.push({
            abs_path: d.uri.fsPath,
            content: d.getText(),
            version: d.version,
          });
        }
      }
      send({ type: "hello", root, repo_id: root, dirty });
    }
  });

  ws.on("message", (data: WebSocket.RawData) => {
    try {
      const msg = JSON.parse(data.toString());
      if (msg.type === "error") {
        console.warn("[MSCodeBase] server error:", msg.message);
      }
    } catch {
      // ignore non-json
    }
  });

  ws.on("close", () => {
    console.log("[MSCodeBase] WS закрыт, переподключение...");
    scheduleReconnect();
  });

  ws.on("error", (err) => {
    console.error("[MSCodeBase] WS ошибка:", err);
    // Закрытие вызовет on('close') → reconnect.
  });
}

function scheduleReconnect(): void {
  if (reconnectTimer) {
    return;
  }
  reconnectAttempt += 1;
  // Экспоненциальный backoff + jitter: base 1s, cap 30s.
  const base = Math.min(30000, 1000 * 2 ** Math.min(reconnectAttempt, 5));
  const jitter = Math.random() * 500;
  const delay = base + jitter;
  reconnectTimer = setTimeout(connectWebSocket, delay);
}

export function activate(context: vscode.ExtensionContext): void {
  const config = vscode.workspace.getConfiguration("mscodebase");
  if (!config.get<string>("serverUrl")) {
    vscode.window.showErrorMessage("MSCodeBase: serverUrl не настроен");
    return;
  }

  connectWebSocket();

  const onChange = vscode.workspace.onDidChangeTextDocument((event) => {
    const doc = event.document;
    if (!shouldSync(doc)) {
      return;
    }
    pendingByUri.set(doc.uri.fsPath, doc);
    scheduleFlush();
  });

  const onSave = vscode.workspace.onDidSaveTextDocument((doc) => {
    if (!shouldSync(doc)) {
      return;
    }
    pendingByUri.delete(doc.uri.fsPath);
    const root = currentProjectRoot();
    if (root) {
      send({ type: "save", root, abs_path: doc.uri.fsPath });
    }
  });

  const onClose = vscode.workspace.onDidCloseTextDocument((doc) => {
    if (!shouldSync(doc)) {
      return;
    }
    pendingByUri.delete(doc.uri.fsPath);
    const root = currentProjectRoot();
    if (root) {
      send({ type: "close", root, abs_path: doc.uri.fsPath });
    }
  });

  // Смена workspace-folder → новый hello (демон переключит проект).
  const onFolders = vscode.workspace.onDidChangeWorkspaceFolders(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      const root = currentProjectRoot();
      if (root) {
        send({ type: "hello", root, repo_id: root, dirty: [] });
      }
    }
  });

  context.subscriptions.push(onChange, onSave, onClose, onFolders);
}

export function deactivate(): void {
  if (debounceTimer) {
    clearTimeout(debounceTimer);
  }
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
  }
  if (ws) {
    ws.close();
    ws = null;
  }
}
