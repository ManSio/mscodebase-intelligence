---
title: "I Reverse-Engineered Zed's threads.db: Here's How Your AI Chats Are Stored"
published: true
description: "A deep dive into the internal format of Zed IDE's AI chat database — zstd compression, JSON v0.3.0, and what it means for privacy-conscious developers."
tags: zed, editor, sqlite, reverse-engineering
cover_image: 
---

> **TL;DR:** Zed IDE stores all AI chat conversations in `threads.db` — a SQLite database with zstd-compressed JSON entries. I decoded the format, and here's everything I found: 300+ threads, 700+ messages, and a structure that's surprisingly well-designed for an IDE chat log.

---

## Why I Did This

I'm building [MSCodeBase Intelligence](https://github.com/ManSio/mscodebase-intelligence) — an MCP server for codebase intelligence. To understand how Zed manages AI context, I needed to know where conversations are stored and how they're structured.

Zed doesn't document `threads.db`. It's not in their public API docs. But it exists, and it's growing every time you chat with an AI agent.

So I reverse-engineered it.

---

## The Discovery

The file lives at:
```
%LOCALAPPDATA%\Zed\threads\threads.db
```
(or `~/Library/Application Support/Zed/threads/threads.db` on macOS)

Size: ~39MB on my machine (300+ threads accumulated over weeks of use).

First instinct: `sqlite3 threads.db .tables`

```
sqlite> .tables
threads

sqlite> .schema threads
CREATE TABLE threads (
    id TEXT PRIMARY KEY,
    summary TEXT,
    updated_at TEXT,
    data_type TEXT,
    data BLOB,
    ...
);
```

The `data` column is a BLOB. Not plain text, not JSON — compressed binary.

---

## Decoding the Format

### Step 1: Decompression

```python
import sqlite3
import zstandard
import json

db = sqlite3.connect("threads.db")
rows = db.execute("SELECT id, data FROM threads LIMIT 5").fetchall()

for thread_id, compressed_data in rows:
    # Decompress with Zstandard
    decompressor = zstandard.ZstdDecompressor()
    raw_data = decompressor.decompress(compressed_data)
    print(f"Thread {thread_id}: {len(raw_data)} bytes decompressed")
```

Output:
```
Thread abc123: 11,247,832 bytes decompressed  # 11.2 MB!
Thread def456: 3,421,088 bytes decompressed
Thread ghi789: 892,441 bytes decompressed
```

The current dialog alone was 11.2 MB uncompressed. That's a lot of AI chat.

### Step 2: JSON Parsing

```python
data = json.loads(raw_data)
print(f"Format version: {data.get('version', 'unknown')}")
print(f"Messages: {len(data.get('messages', []))}")
```

Output:
```
Format version: 0.3.0
Messages: 702
```

### Step 3: Message Structure

```python
for msg in data['messages'][:3]:
    role = list(msg.keys())[0]  # "User" or "Assistant"
    content = msg[role]
    print(f"\n{role}:")
    print(f"  ID: {content.get('id', 'N/A')}")
    print(f"  Model: {content.get('model', {}).get('model', 'N/A')}")
    print(f"  Content blocks: {len(content.get('content', []))}")
    
    for block in content.get('content', [])[:2]:
        if 'Text' in block:
            print(f"  Text: {block['Text'][:100]}...")
```

Output:
```
User:
  ID: msg_abc123
  Model: go/deepseek-v4-flash
  Content blocks: 1
  Text: How do I implement a rate limiter in Python?

Assistant:
  ID: msg_def456
  Model: go/deepseek-v4-flash
  Content blocks: 3
  Text: Here's a simple token bucket rate limiter...
```

---

## The Complete Schema

After analyzing 300+ threads, here's the full structure:

### Top Level

```json
{
  "version": "0.3.0",
  "messages": [
    {
      "User": { /* message object */ },
      "Assistant": { /* message object */ }
    }
  ]
}
```

### Message Object

```json
{
  "id": "msg_unique_id",
  "content": [
    {
      "Text": "The actual message text"
    }
  ],
  "model": {
    "provider": "opencode",
    "model": "go/deepseek-v4-flash"
  },
  "timestamp": 1721234567890
}
```

### Content Blocks

Messages can contain multiple content blocks:
- `{"Text": "..."}` — text content
- `{"ToolUse": {...}}` — tool invocations
- `{"ToolResult": {...}}` — tool outputs

---

## What I Found Interesting

### 1. Model Information is Stored

Every message records which model generated it. In my case, it's `go/deepseek-v4-flash` — Zed's default AI model. This means you could technically analyze which model you're using and how often.

### 2. No Encryption, Just Compression

The data is zstd-compressed but **not encrypted**. Anyone with access to your filesystem can read your AI conversations. This is worth noting for privacy-conscious developers.

### 3. Size Management

The database doesn't seem to have automatic cleanup. My 300+ threads grew to 39MB. Over months, this could become significant.

### 4. Tool Calls are Preserved

Tool invocations (like code edits, file reads) are stored as separate content blocks. This means Zed keeps a complete record of what the AI did, not just what it said.

---

## Privacy Implications

If you're using Zed with AI features:

1. **Your conversations are stored locally** — good for privacy
2. **They're not encrypted** — anyone with file access can read them
3. **They grow without cleanup** — monitor disk usage
4. **They contain tool call history** — including code edits

For most developers, this is fine. But for security-sensitive environments, it's worth knowing.

---

## How to Export Your Conversations

Here's a script to export all threads to readable Markdown:

```python
import sqlite3
import zstandard
import json
from pathlib import Path

def export_threads(db_path: str, output_dir: str):
    """Export all Zed threads to Markdown files."""
    db = sqlite3.connect(db_path)
    rows = db.execute("SELECT id, summary, data FROM threads").fetchall()
    
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    for thread_id, summary, compressed_data in rows:
        try:
            decompressor = zstandard.ZstdDecompressor()
            raw_data = decompressor.decompress(compressed_data)
            data = json.loads(raw_data)
            
            # Generate filename from summary or ID
            safe_name = (summary or thread_id)[:50].replace("/", "_")
            filename = f"{safe_name}.md"
            
            with open(output_path / filename, "w", encoding="utf-8") as f:
                f.write(f"# {summary or thread_id}\n\n")
                f.write(f"**Model:** {data.get('messages', [{}])[0].get('User', {}).get('model', {}).get('model', 'N/A')}\n\n")
                f.write("---\n\n")
                
                for msg in data.get('messages', []):
                    for role, content in msg.items():
                        f.write(f"## {role}\n\n")
                        for block in content.get('content', []):
                            if 'Text' in block:
                                f.write(f"{block['Text']}\n\n")
            
            print(f"Exported: {filename}")
        except Exception as e:
            print(f"Error exporting {thread_id}: {e}")

# Usage
export_threads(
    "%LOCALAPPDATA%\\Zed\\threads\\threads.db",
    "./zed_export"
)
```

---

## What This Means for Zed's Future

The existence of `threads.db` suggests Zed is building toward:

1. **Persistent AI context** — conversations survive restarts
2. **Cross-session learning** — the AI could reference past conversations
3. **Local-first AI** — everything runs on your machine, no cloud required

This aligns with Zed's philosophy of being a fast, local-first editor.

---

## Discussion

Has anyone else looked at `threads.db`? I'm curious what other IDEs store and how they manage conversation history.

What would you want to see in Zed's AI chat API? Export? Summarization? Cross-thread search?

---

*Found this useful? I'm building [MSCodeBase Intelligence](https://github.com/ManSio/mscodebase-intelligence) — an MCP server for codebase intelligence with incident memory and root cause prediction.*
