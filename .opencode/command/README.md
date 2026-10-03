# Agent command entry points

Six commands, one per phase of the protocol. They are procedures, not prose: each
ends in something checkable, and each refuses the specific false conclusion that
phase usually produces.

| command | phase | the false conclusion it exists to prevent |
|---|---|---|
| `/research` | learn | treating a summary of a source as the source |
| `/experiment` | measure | reporting a number with no control that had to fail |
| `/audit` | verify claims | authoring the denominator and getting 100% by construction |
| `/redteam` | attack | shipping because the tests pass |
| `/postmortem` | learn from failure | a fix with no guard, which is a coincidence |
| `/done` | close honestly | a `✅` with no statement of where it was verified |

## Why they live in the repository

A command file that lives only in `~/.config` is lost with the machine, overwritten
by a reinstall, and invisible to the next person. These travel with the code they
govern, and the gates they invoke (`tools/verification/`) are versioned in the same
commit history. A command pointing at a guard that was never committed would be a
procedure that cannot be run by anyone else.

## Invoked paths

The gates are called by real path in `/experiment`, `/audit` and `/done`:

```bash
python tools/verification/run_all.py
python tools/verification/gates.py --gate population --input '{"population": N, "computed_rate": R}'
python tools/verification/g5_denominator.py
```

Those paths are relative to the repository root, which is where an agent working in
this project already is. A command that names a path which does not exist is worse
than no command.
