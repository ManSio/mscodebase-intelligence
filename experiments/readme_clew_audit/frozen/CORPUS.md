# FROZEN INPUT — E-Missing-Substring (readme-clew-2 coverage audit)

Frozen BEFORE any result was computed. Changing this list after seeing results is
forbidden (Freeze-before-look, §17). Changing an entry must create a NEW entry,
never edit this one.

## Corpus (N=6 real JS repos, shallow clones, pinned)

| repo | sha256-commit |
|---|---|
| chalk/chalk | 47fc05abd46171b235e24174cd2dba83d25bf037 |
| sindresorhus/execa | 63ddae6aeb6934da06fdb3754647791e58cd87c3 |
| sindresorhus/got | e1d87d2ced01d5b7d855a7dc8b091bf7b014a1e4 |
| sindresorhus/ora | b204360b0df925289759858c93d3d3ca824914c3 |
| sindresorhus/slugify | 3b17b2e84b97624a683aafaa38184bf2746fab22 |
| sindresorhus/yocto-queue | 72a8fa96a9d389765cdf2bb9c6daba8302fc375d |

Attempted and NOT AVAILABLE (do not silently substitute):
`ws/ws`, `sindresorhus/nanoid`, `sindresorhus/mime-types` — repository not found.

## Target under test

`lib/verifiers/coverage.js:24`

    if (readme.includes(name.toLowerCase())) continue;

Substring test against the whole lowercased README, no token boundary.

## What is measured

For every imported package that the tool SUPPRESSED (did not report as Missing),
does the name occur in the README as a standalone token, or only as a substring
of some other word?

- standalone token  -> genuine mention, suppression is correct
- substring only    -> FALSE NEGATIVE: real Missing drift silently disappears

This needs no subjective labelling: the question is mechanical.

## Snapshot construction (mirrors the tool's own limits)

- `pkg`   = parsed `package.json`
- `files` = `git ls-files`
- `sources` = first 20 source files (`.js .mjs .cjs .ts .tsx .jsx`), sorted —
  the README documents "at most 20 source files are read per scan"
- README = `README.md`, lowercased by the tool itself

## Controls (must be present in every run)

- positive control: a package genuinely absent from the README MUST be flagged
- negative control: a package genuinely named in the README MUST NOT be flagged
- synthetic substring cases already frozen in `harness/EXP_coverage_substring.mjs`
  (4/9 correct; 3 false negatives + 2 false positives, controls green)