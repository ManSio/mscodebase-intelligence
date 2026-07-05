# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 2.4.x   | ✅ Active development |
| < 2.4   | ❌ Not supported |

## Reporting a Vulnerability

We take security seriously. If you discover a security vulnerability in
MSCodeBase Intelligence, please report it privately.

**Do not** disclose the vulnerability publicly via GitHub Issues.

Instead, please:

1. **Open a draft security advisory** at:
   https://github.com/ManSio/mscodebase-intelligence/security/advisories

2. **Or email** the maintainers via the GitHub security contact.

You should receive a response within 48 hours. If the issue is confirmed,
we will release a patch as soon as possible.

## What to Include

- Type of vulnerability
- Steps to reproduce
- Affected versions
- Any potential mitigations you've identified

## Scope

MSCodeBase Intelligence runs fully locally. The following are **not**
considered security vulnerabilities:
- LM Studio API exposed on localhost (by design)
- SQLite database in project directory (local file)
- Venv/pip dependencies (user-managed)

Thank you for helping keep this project secure.
