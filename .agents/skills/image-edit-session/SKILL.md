---
name: image-edit-session
description: Helps developers understand and work with image edit sessions, including bind_image_output function for managing generated images in chat sessions with TTL-based expiration.
---

# Image Edit Session Skill

This skill helps developers understand and work with the image edit session system in gemma_agent, specifically the `bind_image_output` function and related session management.

## What This System Does

The image edit session system manages generated images within chat sessions:

- **bind_image_output()**: Links a generated image to a specific (user_id, chat_id) session
- **TTL-based expiration**: Sessions automatically expire after a configurable time (default 1 hour)
- **File storage**: Session data stored as JSON files in `data/runtime/image_edit_sessions/`
- **Isolation**: Each user/chat pair has separate session data

## Key Functions

### bind_image_output(user_id, chat_id, local_path)
```python
def bind_image_output(user_id: str, chat_id: str, local_path: str) -> None:
    if not _enabled():
        return
    path = (local_path or "").strip()
    if not path or not Path(path).is_file():
        return
    now = int(time.time())
    with _LOCK:
        doc = _read(user_id, chat_id)
        doc.update(
            {
                "output_path": path,
                "updated_at": now,
                "expires_at": now + _ttl_sec(),
            }
        )
        _write(user_id, chat_id, doc)
```

**What it does:**
- Stores the path to a generated image in the session
- Updates the session timestamp and expiration time
- Automatically extends session lifetime on each image binding

**When to use:**
- After generating an image with an image generation model
- When you need to associate the generated image with a specific chat session
- For subsequent operations like editing, analyzing, or sending the image

### Related Functions

**bind_image_input(user_id, chat_id, local_path)**
- Stores the input path (source image) in the session
- Used for editing workflows where you start with an existing image

**get_image_edit_session(user_id, chat_id)**
- Retrieves the complete session data
- Returns None if session expired or doesn't exist
- Automatically cleans up expired sessions

**file_context_for_session_edit(user_id, chat_id)**
- Returns file context for editing the current session image
- Used by the editing system to provide the right image for modification

## Session Storage

**File location:** `data/runtime/image_edit_sessions/{user_id}_{chat_id}.json`

**Structure:**
```json
{
    "output_path": "/path/to/generated/image.jpg",
    "updated_at": 1701234567,
    "expires_at": 1701238167
}
```

**TTL Configuration:**
- Default: 1 hour (3600 seconds)
- Range: 5 minutes - 24 hours
- Controlled by `IMAGE_EDIT_SESSION_TTL_SEC` environment variable

## How to Work with This System

### 1. Basic Usage
```python
# Bind a generated image to a session
bind_image_output("user123", "chat456", "/path/to/generated/image.jpg")

# Later retrieve the session
session = get_image_edit_session("user123", "chat456")
if session:
    print(f"Image path: {session['output_path']}")
```

### 2. Session Expiration
```python
# Sessions expire automatically based on TTL
# After expiration, get_image_edit_session returns None
```

### 3. Editing Workflow
```python
# For editing the current session image
context = file_context_for_session_edit("user123", "chat456")
if context:
    # Use context['local_path'] for editing operations
    pass
```

## Common Patterns

### Pattern 1: Generate → Bind → Edit
```python
# 1. Generate image using your model
image_path = generate_image_with_model(prompt)

# 2. Bind to session
bind_image_output(user_id, chat_id, image_path)

# 3. Provide for editing
context = file_context_for_session_edit(user_id, chat_id)
```

### Pattern 2: Input → Bind → Process
```python
# 1. User provides input image
input_path = get_user_input_image()

# 2. Bind input to session
bind_image_input(user_id, chat_id, input_path)

# 3. Process and generate output
output_path = process_image(input_path)
bind_image_output(user_id, chat_id, output_path)
```

## Configuration

Environment variables:

- `IMAGE_EDIT_SESSION_ENABLED`: Enable/disable the system (default: true)
- `IMAGE_EDIT_SESSION_TTL_SEC`: Session TTL in seconds (default: 3600)
- `GEMMA_PROJECT_ROOT`: Root directory (default: current directory)

## Error Handling

**Common issues and solutions:**

1. **Session not found**: Ensure `bind_image_output` was called first
2. **Expired session**: Sessions expire based on TTL, call `bind_image_output` again to refresh
3. **File not found**: Verify the path exists before calling `bind_image_output`

## Integration with Other Systems

This system integrates with:

- **Image generation models**: Store generated images in sessions
- **Editing workflows**: Provide file context for session images
- **Chat systems**: Associate images with specific chat sessions
- **User management**: Isolate sessions per user/chat pair

## Debugging with MCP Tools

When investigating image session issues:

1. `get_logs(project_root)` → check for session-related errors
2. `search_code(query="bind_image_output")` → find all usages
3. `deep_search(query="image session lifecycle")` → understand full flow
4. `grep "IMAGE_EDIT_SESSION"` → find configuration
5. `get_symbol_info(query="bind_image_output")` → analyze callers

## Testing

To test this system:

```python
# Test basic functionality
bind_image_output("test_user", "test_chat", "/tmp/test.jpg")
session = get_image_edit_session("test_user", "test_chat")
assert session is not None
assert "output_path" in session

# Test expiration
# Wait for TTL to expire
# Session should return None
```

This skill provides the foundation for working with image edit sessions in gemma_agent, enabling developers to build workflows that generate, store, and manipulate images within the context of specific chat sessions.
