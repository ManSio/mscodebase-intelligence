# Pull request

## What changed

<!-- One or two sentences. For a documentation change: state which code fact it reflects. -->

## Documentation = code (mandatory when any .md changes)

Every changed documentation line must point at the code that makes it true. A
change that only "fixes a number" without a source reference is rejected before
commit.

| Changed doc line (file) | Code fact it describes (file:symbol) | How it was verified |
|---|---|---|
| `docs/en/...` | `install.py::_print_config` | ran `python install.py --print-config --client generic` |

- [ ] No sentence in this PR describes behaviour the code does not have.
- [ ] `python scripts/check_docs_vs_installer.py` is green (flags and client
      names in docs exist in `install.py` / `adapters/clients/snippets.py`).
- [ ] `install / uninstall / clean / doctor` are described and match the behaviour.
- [ ] The "What works today" table keeps its **Entry point** column.

## Gates

- [ ] `python -m pytest tests/ -q`
- [ ] `ruff check src/ tests/` (or `scripts/ruff_gate.py`)
- [ ] New behaviour has a test that fails when the behaviour is removed
      (paste the red run below).
- [ ] Numbers in this PR are measured, with unit and denominator.

## Evidence

```text
<paste command output, not a summary>
```

## Risks / not verified

<!-- What is untested and why. "None" is a valid answer only when it is true. -->
