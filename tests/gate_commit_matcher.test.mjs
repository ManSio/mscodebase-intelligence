// isGitCommit — commit matcher used by the gate hook.
//
// Regression: the previous matcher was /\bgit\s+commit\b/, which required the two
// tokens to be adjacent. M4 full-30 run 11 committed through `git -C <dir> commit`
// and was never gated, then was scored instead of discarded (30/30 transcripts).
//
// This file is the control for that guard: it MUST be able to fail. Each case below
// is a command that must be recognised (positive) or must NOT be recognised
// (negative). If someone weakens the tokenizer, these fail rather than silently
// letting commits through again.
import { describe, it, before } from "node:test";
import assert from "node:assert/strict";

process.env.MSCODEBASE_STALE_GATE = "off";
if (!process.env.MSCODEBASE_PY) process.env.MSCODEBASE_PY = "python";

let isGitCommit;
before(async () => {
  ({ isGitCommit } = await import("../tools/gate_helpers.ts"));
});

describe("isGitCommit", () => {
  const POSITIVE = [
    "git commit -m 'x'",
    "git commit",
    "git -C D:/Project/_m4runs/full11 commit -m 'chore: x'", // the actual bypass
    "git -C . commit --amend --no-edit",
    "git -c user.name=x commit -m y",
    "git --git-dir=D:/x/.git commit -m y",
    "git --git-dir D:/x/.git commit -m y",
    "cd pkg && git commit -m y",
    "git.exe commit -m y",
    "timeout 300 git commit -m y",
    "git -C a -c b=c commit -m y", // two value-taking options in a row
  ];

  const NEGATIVE = [
    "",                                        // empty
    "git status",
    "git log --oneline -5",
    "git diff --cached",
    "git add -A",
    "git commit-tree abc",                      // commit-tree is not commit
    "echo 'git commit -m x'",                   // quoted text, not the git binary
    "git -C . status",                          // option present, commit absent
    "git commitmsg-hook",                       // prefix, not the subcommand
  ];

  for (const cmd of POSITIVE) {
    it(`gates: ${cmd}`, () => assert.equal(isGitCommit(cmd), true));
  }
  for (const cmd of NEGATIVE) {
    it(`does not gate: ${cmd}`, () => assert.equal(isGitCommit(cmd), false));
  }
});