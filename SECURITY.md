# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 3.3.x   | ✅ Active development |
| 3.2.x   | ⚠️ Security patches only |
| < 3.2   | ❌ Not supported |

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

## Sandbox Model (`execute_script`)

`execute_script` runs Python code on the host machine. It has **three defense layers**,
none of which is a security boundary:

| Layer | What it does | Known weakness |
|-------|-------------|----------------|
| 1. String pattern scan | Blocks obvious patterns (`open(`, `os.system`, etc.) | Substring match — we switched to regex word-boundary (`(?<![a-zA-Z0-9_])`) to prevent false positives like `urlopen` matching `open(` |
| 2. AST validation | Blocks dangerous imports, `eval/exec`, dunder access | Cannot catch all obfuscation (e.g. `__getattribute__` bypass was found and patched) |
| 3. Runtime preamble | Restricts `__import__` to an allowlist at runtime | Minimal stdlib — no `os`, `subprocess`, `shutil`, `pathlib` |

**Critical: this is NOT a sandbox for untrusted code.** It is defense-in-depth for
AI agent tools. A determined attacker can bypass all three layers. Never rely on it
as the sole security control for code execution.

When reporting security issues: bypassing the sandbox to run `os.system()` or `subprocess`
is **expected behavior** and not a vulnerability — the sandbox slows attacks, it does not
prevent them.

Thank you for helping keep this project secure.
