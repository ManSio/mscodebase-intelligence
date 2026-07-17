# Security Policy — MSCodeBase Intelligence

[🇬🇧 English](SECURITY.md) • [🇷🇺 Русский](../ru/SECURITY.md) • [🇨🇳 中文](../zh/SECURITY.md)

## Responsible Disclosure

If you discover a security vulnerability in MSCodeBase Intelligence, please report it responsibly.

### How to Report

1. **GitHub Security Advisory**: [Create an advisory](https://github.com/ManSio/mscodebase-intelligence/security/advisories/new)
2. **In the subject line**, include: `[SECURITY]` + a brief description of the issue

### What to Provide

- Vulnerability description (type, component, exploitation conditions)
- Steps to reproduce
- Impact assessment (confidentiality, integrity, availability)
- Proof of concept (if applicable)
- Fix suggestions (optional)

### Response Timeline

| Severity | First Response | Fix |
|----------|---------------|-----|
| Critical | 7 days | 30 days |
| High | 14 days | 90 days |
| Medium | 14 days | 90 days |
| Low | 30 days | 180 days |

---

## Supported Versions

| Version | Support |
|---------|---------|
| 3.2.x | ✅ Current (hybrid LSP+MCP) |
| 2.x | ⚠️ Critical patches only |
| < 2.0 | ❌ No |

---

## Security Architecture

### Hybrid Architecture (LSP + MCP)

Starting with version 2.0.0, MSCodeBase Intelligence uses a hybrid architecture combining Language Server Protocol (LSP) and Model Context Protocol (MCP):

- **LSP server**: handles code parsing via Tree-sitter and provides symbols to the editor
- **MCP server**: provides semantic search, embeddings, and AI agent interaction
- **Interaction**: both components work locally, data exchange via stdio/SSE

### What Leaves the Machine

**By default — nothing.** All components operate exclusively locally:

| Component | Data | Sent To |
|-----------|------|---------|
| LanceDB | Vector index, code chunks | Locally (`.codebase_indices/`) |
| Tree-sitter | AST parsing | Locally, in process memory |
| SafePathManager | Path validation | Locally, no network |
| MCP tools | Search/analysis requests | Locally, stdio/SSE |

**The only exception**: if LM Studio or Ollama integration is configured for generating embeddings — requests are sent **only** to a local endpoint (`localhost:1234` for LM Studio, `localhost:11434` for Ollama). Cloud APIs are not used.

### Input Protection

- **All MCP tool validation**: each tool checks types, length, and format of input parameters
- **Path traversal protection**: `SafePathManager` blocks access outside project directories (`../`, absolute paths outside the project)
- **SQL injection**: LanceDB uses parameterized queries, user input is never interpolated into queries
- **Input size limits**: restrictions on query length and indexed file size

### Data Protection

- **Local storage**: the entire index is stored in `.codebase_indices/` inside the project
- **Path hashing**: project paths are hashed to isolate indices
- **Filtering**: files from `.gitignore` and binary files are excluded from indexing
- **Encryption**: data is not encrypted on disk (file system is assumed to be protected by the OS)

### Access Control

- **File system**: access is limited to project directories
- **Privileges**: no elevated rights required (no `sudo`/admin needed)
- **Network access**: not required for operation (except local LM Studio/Ollama)

---

## Hybrid Architecture Security (2.0.0+)

### Risks and Mitigations

| Risk | Description | Mitigation |
|------|-------------|------------|
| LSP server accessible over network | If running in SSE mode, external access is possible | Default: stdio; SSE only on `localhost` |
| MCP tools accept arbitrary input | A malicious agent could pass invalid data | Per-tool validation |
| Code leakage via embeddings | Code is sent to LM Studio for indexing | Only local LM Studio; cloud services not supported |
| Race condition during indexing | Concurrent writes to LanceDB | Chunk versioning, atomic updates |

### Deployment Recommendations

1. **Use stdio mode** for LSP and MCP if remote access is not required
2. **LM Studio/Ollama**: ensure the server listens only on `127.0.0.1`, not `0.0.0.0`
3. **Firewall**: block outgoing connections from the MSCodeBase process (if not using cloud services)
4. **Updates**: monitor dependency updates via Dependabot

---

## Dependencies

### Vulnerability Scanning

- **GitHub Dependabot**: automatic dependency scanning
- **Dependabot Alerts**: notifications about critical CVEs in dependencies

### Critical Dependencies

| Dependency | Purpose | Security Notes |
|------------|---------|---------------|
| LanceDB | Vector DB | Local storage, no network access |
| Tree-sitter | Code parsing | Sandboxed, no arbitrary code execution |
| LM Studio SDK | Embeddings | Local endpoint only |
| Ollama SDK | Alternative embeddings | Local endpoint only |

---

## Acknowledgements

We thank the security researchers who help make MSCodeBase Intelligence more reliable.

---

*Last updated: 2026-06-28*
