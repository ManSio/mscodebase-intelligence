I read this properly rather than skimming, and the part I want to lead with is the part that held up under testing.

**What I verified.** On the committed bytes your suite is 474 passed / 0 failed, offline, no keys — exactly what the README claims. I then mutation-tested the guards that carry your main promise (README:193, "every new guard was shown failing once"). Seven mutants, one at a time, full suite after each: disabling the prose guard (4 fails), removing the 0.8 gate (5), emptying `PLATFORM_SET` (1), dropping the unread-config guard (1), removing the Missing suppression (13), renaming the build-output exclusion (17). Six died. A no-op control stayed green, so the harness wasn't manufacturing redness. That claim is real, and it is the hardest thing in this repo to get right.

**One real defect — `lib/verifiers/coverage.js:24`.**

    if (readme.includes(name.toLowerCase())) continue;

A substring test over the whole README. A package whose name appears inside an unrelated word counts as documented, and its Missing finding disappears silently. Not synthetic — from a real repo, `sindresorhus/yocto-queue @72a8fa9`:

- `ava` is a declared devDependency
- the README contains `mozilla.org/en-us/docs/web/javascript/reference/iteratio…`
- `ava`script contains `ava` → suppressed, never reported

Same shape on ordinary prose: package `can` is suppressed by the word "canvas", `yoga` by `yoga-layout`.

I measured the incidence before deciding it was worth sending: over 6 real repos it hit **1 of 22** suppressions. Rare, not systemic — but silent, and it's the mirror of the failure you defend against all README. You spend the doc protecting against accusing a correct README; this is a real drift the report simply never mentions.

A token boundary closes the substring half. This variant is 12/12 on my cases:

    (?<![A-Za-z0-9_@/-])<name>(?![A-Za-z0-9_/.-])

It still matches `` `ava` ``, `ava@5.0.0`, `React 19`; it stops matching `ava` inside `javascript`, `lodash` inside `lodash-es`, `can` inside `canvas`. Worth being straight about what it does **not** fix: package `got` vs the English word "got" is genuinely ambiguous, and no regex settles that — that one needs the alias map or an ignore list.

**Two small notes, both optional.**

- No `.gitattributes`, so on a Windows clone (`core.autocrlf=true`) the extension-sync test is red before you run anything: committed file is LF, working copy CRLF, so the byte comparison fires. The guard is correct — the checkout makes it fail. `* text=auto eol=lf` settles it.
- The `JS_FILE` filter in `importedPackages()` is unreachable — `isSourcePath()` in `github.js:14,45` already restricts `sources` to JS/TS. That was my one surviving mutant. Harmless, just unexercised.

Happy to send the mutation catalog with expected kill counts, and the token-boundary regression tests. Both are small and entirely yours to take or leave.