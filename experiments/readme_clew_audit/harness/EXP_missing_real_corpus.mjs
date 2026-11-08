// E-Missing-Substring — real-corpus incidence of the coverage.js substring check.
// Input frozen in ../frozen/CORPUS.md before this file was run.

import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs';
import { join, relative } from 'node:path';
import { tmpdir } from 'node:os';
import { execFileSync } from 'node:child_process';
import { verifyCoverage } from './coverage_probe_target.mjs';
import { importedPackages } from './deps_probe_target.mjs';

// Explicit input location (override with CLEW_CORPUS); default is a temp dir,
// never an author-absolute path (P-021).
const CORPUS = process.env.CLEW_CORPUS || join(tmpdir(), 'opencode', 'clew_corpus');
const SOURCE_EXT = /\.(?:[cm]?js|[cm]?ts|jsx|tsx)$/;
const SKIP_DIR = /(^|\/)(?:examples?|demos?|tests?|__tests__|fixtures|docs)\//i;

function walk(root, acc = []) {
  for (const e of readdirSync(root, { withFileTypes: true })) {
    const p = join(root, e.name);
    if (e.isDirectory()) {
      if (e.name === 'node_modules' || e.name === '.git') continue;
      walk(p, acc);
    } else acc.push(p);
  }
  return acc;
}

// does `name` occur in the README as a standalone token (not as part of another word)?
function tokenMention(readmeLower, name) {
  const esc = name.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&');
  // allow the bare name and its subpath form (pkg/sub -> pkg)
  const re = new RegExp(`(?<![a-z0-9_@/-])${esc}(?![a-z0-9_/-])`, 'i');
  return re.test(readmeLower);
}

const rows = [];
let supTotal = 0, supReal = 0, supSubstringOnly = 0;
const substringInstances = [];

for (const dir of readdirSync(CORPUS)) {
  const root = join(CORPUS, dir);
  const readmePath = join(root, 'README.md');
  if (!existsSync(readmePath)) { console.log(`SKIP ${dir}: no README.md`); continue; }
  const readme = readFileSync(readmePath, 'utf8');
  let pkg = {};
  try { pkg = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8')); } catch { }

  const all = walk(root).map((p) => relative(root, p).split('\\').join('/'));
  const files = all;
  const sourcePaths = all.filter((f) => SOURCE_EXT.test(f) && !SKIP_DIR.test(f)).sort().slice(0, 20);
  const sources = {};
  for (const f of sourcePaths) { try { sources[f] = readFileSync(join(root, f), 'utf8'); } catch { } }

  const repo = { pkg, files, sources };
  const findings = verifyCoverage(readme, repo);
  const flagged = new Set(findings.map((f) => f.name));
  const imported = importedPackages(sources);
  const readmeLower = readme.toLowerCase();

  let dReal = 0, dSub = 0;
  for (const name of imported.keys()) {
    if (flagged.has(name)) continue;              // this one WAS reported
    supTotal++;                                    // suppressed
    if (readmeLower.includes(name.toLowerCase())) {
      // suppressed by a substring hit — is it a real standalone mention?
      if (tokenMention(readmeLower, name)) { supReal++; dReal++; }
      else {
        supSubstringOnly++; dSub++;
        substringInstances.push({ repo: dir, name });
      }
    }
  }
  rows.push({ repo: dir, imported: imported.size, flaggedMissing: findings.length, suppressedReal: dReal, suppressedSubstringOnly: dSub });
}

console.log('\n=== per repo ===');
console.table(rows);
console.log('\n=== totals ===');
console.log('suppressed total           :', supTotal);
console.log('  genuine token mention    :', supReal);
console.log('  SUBSTRING-ONLY (bug hits):', supSubstringOnly);
console.log('\n=== substring-only instances (false negatives) ===');
for (const i of substringInstances) console.log(' -', i.repo, '->', i.name);

// ── controls run on the SAME harness, on the SAME code path ──
console.log('\n=== controls ===');
const ctlFlag = verifyCoverage('nothing relevant here', {
  pkg: {}, files: ['a.js'], sources: { 'a.js': "import 'leftpad';" },
});
console.log('positive control (absent pkg MUST be flagged):',
  ctlFlag.some((f) => f.name === 'leftpad') ? 'ok' : 'BROKEN');
const ctlNoFlag = verifyCoverage('we depend on leftpad', {
  pkg: {}, files: ['a.js'], sources: { 'a.js': "import 'leftpad';" },
});
console.log('negative control (named pkg MUST NOT be flagged):',
  ctlNoFlag.length === 0 ? 'ok' : 'BROKEN');
const ctlSub = verifyCoverage('once you got it working', {
  pkg: {}, files: ['a.js'], sources: { 'a.js': "import 'got';" },
});
console.log('substring control (bug MUST reproduce):',
  ctlSub.length === 0 ? 'reproduced (control can fail)' : 'DID NOT REPRODUCE');