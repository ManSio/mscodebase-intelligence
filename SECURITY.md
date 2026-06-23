# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in MSCodebase Intelligence, please report it responsibly. We follow the [Responsible Disclosure](https://docs.github.com/en/github/site-policy/security-policies#responsible-disclosure-of-vulnerabilities) policy.

### How to Report

1. **Email**: security@mscodebase.com
2. **GitHub Security Advisory**: [Create an advisory](https://github.com/ManSio/mscodebase-intelligence/security/advisories/new)
3. **PGP Key**: `0x1234567890ABCDEF` (for encrypted reports)

### What We Need

When reporting a vulnerability, please include:

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

- Sensitive data encryption at rest
- Secure handling of API keys and tokens
- Regular security audits and dependency updates

### Access Control

- Principle of least privilege applied
- Role-based access control where applicable
- Authentication and authorization mechanisms

## Dependencies

### Security Scanning

We use the following tools for security scanning:

- **GitHub Dependabot**: Automated dependency vulnerability scanning
- **CodeQL**: Static application security testing (SAST)
- **Semgrep**: Pattern-based security scanning

### Third-Party Services

| Service | Purpose | Security Notes |
|---------|---------|----------------|
| LM Studio | Embeddings API | Requires local deployment |
| ChromaDB | Vector database | Encrypted storage |
| Tree-sitter | Code parsing | Sandboxed execution |

## Security Contact

For security-related questions or concerns:

- **Email**: security@mscodebase.com
- **PGP**: security@mscodebase.com (key fingerprint: `0x1234567890ABCDEF`)

## Acknowledgments

We thank all security researchers who have contributed to making MSCodebase Intelligence more secure.

## Reporting Vulnerabilities in Dependencies

If you believe a dependency has a security vulnerability, please report it to the respective dependency maintainers. We also monitor vulnerability databases and will update dependencies as needed.

---

*Last updated: 2026-06-24*