I ran the two package-facing verifiers offline against a few public repositories. One thing seemed worth an issue, because it hides a finding rather than raising one.

### Names are matched with `includes`, so a substring counts as a mention

`lib/verifiers/coverage.js:24`

```js
if (readme.includes(name.toLowerCase())) continue;
```

A name that appears inside an unrelated word is treated as documented. A real case, not synthetic — `sindresorhus/yocto-queue @72a8fa9`: `ava` is a declared devDependency and the README points at `mozilla.org/en-us/docs/web/javascript/reference/iteration…`, where "j**ava**script" carries the name. The `missing` finding is suppressed, with no trace.

### The same shape can invert in `inCodeContext`

`lib/verifiers/dependencies.js:54`

```js
return INSTALL.test(text) && names.some((n) => text.includes(n));
```

Here the prose guard decides whether a line counts as a code claim, and a substring can push a prose word across that line — reaching `contradicted`, the outcome the comment above it says must not happen. Calling `verifyDependency` directly:

| name | line | bucket |
|---|---|---|
| `can` | ``Run `npm i canvas-parser` to start.`` | **contradicted** |
| `can` | `The canvas API draws things.` | unverifiable |
| `lodash` | ``Run `npm i lodash-es` instead.`` | **contradicted** |
| `leftpad` | ``Run `npm i leftpad` to start.`` | contradicted (true positive) |

It needs a name that isn't really on the line to reach the guard, so it is a latent path rather than something I have seen fire on a live scan.

### A token check fixes both

`\b<name>\b` is not enough — it still matches `lodash` inside `lodash-es`, `yoga` inside `yoga-layout`, and `types` inside `@types`. What worked:

```js
// a package name is its own token: npm's own name characters are letters, digits, "_" and "-",
// and the name must not sit after "@" or "/" (a scope or a path)
function mentionsWord(text, name) {
  if (!name) return false;
  const esc = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(`(?<![A-Za-z0-9_@/-])${esc}(?![A-Za-z0-9_-])`, 'i').test(text);
}
```

On 27 unambiguous cases: the current `includes` gets 14, `\b` gets 20, this gets 27. It keeps `ava@6.0.0`, `` `ava` ``, `npm i --save-dev ava`, `We use ava.` and `lodash/fp`; it stops `javascript`, `lodash-es`, `yoga-layout`, `@types/node`, `canvas-parser` and `target`.

Applied at both sites and run against the suite: **474/474, three times in a row.**

### Residual, stated plainly

A shorter name that is a prefix of a *different real package* — `socket` against `socket.io` — cannot be told apart by any regex. That needs the package-name list you keep for the other checks. Same class as the `got` vs the English word "got" note in the README.

### Unrelated, noticed while in there

A fresh Windows clone (`core.autocrlf=true`, no `.gitattributes`) fails 2 of the 474 — the `extension/` vs `web/` byte-for-byte sync and the bookmarklet build test. Both are LF vs CRLF in the checked-out text; on a clone made with `core.autocrlf=false` it is 474/474. A `.gitattributes` with `* text=auto eol=lf` closes it.

Happy to send the 27-case matrix as a test file if that is useful.
