# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in MSCodebase Intelligence, please report it responsibly.

### How to Report

1. **GitHub Security Advisory**: [Create an advisory](https://github.com/ManSio/mscodebase-intelligence/security/advisories/new)

### What We Need

- Description of the vulnerability
- Steps to reproduce
- Impact assessment
- Proof of concept (if applicable)
- Suggested fixes

### Response Timeline

- **Critical vulnerabilities**: 7 days response, 30 days fix
- **High/Medium vulnerabilities**: 14 days response, 90 days fix
- **Low vulnerabilities**: 30 days response, 180 days fix

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 1.1.x   | ✅ Yes             |
| 1.0.x   | ✅ Yes             |
| <1.0    | ❌ No              |

## Security Best Practices

### Input Validation

- All user inputs are validated and sanitized
- Path traversal protection implemented
- SQL injection prevention through parameterized queries

### Data Protection

- All data stored locally (no external services except optional LM Studio)
- Path hashing for project isolation
- .gitignore pattern filtering

### Access Control

- File system access limited to project directories
- No elevated permissions required

## Dependencies

### Security Scanning

- **GitHub Dependabot**: Automated dependency vulnerability scanning

### Third-Party Services

| Service | Purpose | Security Notes |
|---------|---------|----------------|
| LM Studio | Embeddings API | Local deployment only |
| LanceDB | Vector database | Local storage, no cloud |
| Tree-sitter | Code parsing | Sandboxed execution |

## Acknowledgments

We thank all security researchers who have contributed to making MSCodebase Intelligence more secure.

---

*Last updated: 2026-06-27*
