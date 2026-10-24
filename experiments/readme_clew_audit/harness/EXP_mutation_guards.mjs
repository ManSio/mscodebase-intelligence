// Mutation test of readme-clew-2's fail-closed guards.
// Claim under test (README:193): "Every new guard was shown failing once"
//   => every guard, if broken, must turn the suite RED.
//
// Method: break ONE guard at a time in a scratch copy, run the full suite,
// record whether any test catches it, then restore. A mutation that leaves the
// whole suite green is a guard the suite does not actually protect.
//
// control: an UNRELATED no-op edit must leave the suite green (proves the
// harness itself does not manufacture redness).

import { readFileSync, writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

// Scratch copy location (override with CLEW_ROOT); never an author-absolute
// path (P-021).
const ROOT = process.env.CLEW_ROOT || join(tmpdir(), 'opencode', 'clew_lf_mode');

const MUTANTS = [
  { id: 'M1', file: 'lib/verifiers/dependencies.js',
    from: 'function inCodeContext(names, ctx) {',
    to: 'function inCodeContext(names, ctx) { return true;',
    what: 'prose guard disabled: every name is treated as a code-context claim' },

  { id: 'M2', file: 'lib/gate.js',
    from: 'const low = confidence < THRESHOLD;',
    to: 'const low = false;',
    what: 'the 0.8 confidence gate removed' },

  { id: 'M3', file: 'lib/verifiers/envvars.js',
    from: "const PLATFORM_SET = new Set(['PORT', 'NODE_ENV', 'CI', 'HOST']);",
    to: 'const PLATFORM_SET = new Set([]);',
    what: 'platform-set env vars no longer exempt' },

  { id: 'M4', file: 'lib/verifiers/envvars.js',
    from: 'if (files.some((f) => CONFIG_FILE.test(f) && !NOT_CONFIG.test(f) && !(f in sources))) return unverifiable;',
    to: '',
    what: 'unread-config guard removed (env vars can be called Contradicted from files never read)' },

  { id: 'M5', file: 'lib/verifiers/coverage.js',
    from: 'if (readme.includes(name.toLowerCase())) continue;',
    to: 'continue;',
    what: 'Missing suppression removed: every imported package is flagged, even documented ones' },

  { id: 'M6', file: 'lib/verifiers/dependencies.js',
    from: 'if (!JS_FILE.test(file)) continue;',
    to: '',
    what: 'import scan reads non-JS files too (imports in .md/.json/etc. now counted)' },

  { id: 'M7', file: 'lib/verifiers/references.js',
    from: 'build',
    to: 'buildXX',
    what: 'reference to build output renamed (checks whether build-output exclusion is load-bearing)' },
];

function runSuite() {
  try {
    const out = execFileSync('node', ['--test'], { cwd: ROOT, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
    return { pass: /# fail 0/.test(out) || /ℹ fail 0/.test(out), out };
  } catch (e) {
    const out = (e.stdout || '') + (e.stderr || '');
    return { pass: false, out };
  }
}

function restore() {
  execFileSync('git', ['checkout', '--', '.'], { cwd: ROOT });
}

function mutate(m) {
  const p = `${ROOT}/${m.file}`;
  const src = readFileSync(p, 'utf8');
  if (!src.includes(m.from)) return { ok: false, reason: 'anchor not found' };
  writeFileSync(p, src.replace(m.from, m.to), 'utf8');
  return { ok: true };
}

// ── control: no-op mutation must stay green ──
const base = runSuite();
console.log(`BASELINE suite pass=${base.pass}`);
const noop = { id: 'C0', file: 'lib/mood.js', from: 'export', to: 'export', what: 'no-op control' };
const before = readFileSync(`${ROOT}/lib/mood.js`, 'utf8');
writeFileSync(`${ROOT}/lib/mood.js`, before, 'utf8');
const ctl = runSuite();
console.log(`CONTROL  no-op suite pass=${ctl.pass}  (must be true, else harness is noisy)\n`);

const results = [];
for (const m of MUTANTS) {
  restore();
  const applied = mutate(m);
  if (!applied.ok) { console.log(`${m.id} SKIP (${applied.reason})`); results.push({ ...m, verdict: 'SKIPPED' }); continue; }
  const r = runSuite();
  const killed = !r.pass;
  const m2 = /^# fail (\d+)|^ℹ fail (\d+)/m.exec(r.out);
  const fails = m2 ? (m2[1] ?? m2[2]) : '?';
  console.log(`${m.id} ${killed ? 'KILLED  ' : 'SURVIVED'}  fail=${fails}  ${m.what}`);
  results.push({ id: m.id, killed, fails, what: m.what, file: m.file });
}
restore();

console.log('\n=== verdict ===');
const survived = results.filter((r) => !r.killed && r.verdict !== 'SKIPPED');
console.log(`mutants: ${results.length}  killed: ${results.filter(r=>r.killed).length}  survived: ${survived.length}`);
for (const s of survived) console.log(`  SURVIVED ${s.id}: ${s.what}`);