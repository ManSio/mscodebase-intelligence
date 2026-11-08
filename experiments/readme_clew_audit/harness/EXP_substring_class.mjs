// EXP: the substring class across all three semantic-containment sites in lib/verifiers/.
// Calls HIS functions directly. No Jev, no network, $0.
//
// EXPECTATIONS, frozen before the run:
//
//  A (coverage.js:24)  A package whose name is only a SUBSTRING of an unrelated
//                      word is treated as documented -> the Missing finding is lost.
//                      CONTROL: the same name as a standalone token must be found missing.
//
//  B (dependencies.js:54)  The prose guard is supposed to keep prose names from
//                      being called Contradicted. If substring-only matches satisfy
//                      it, a name that is NOT on the line in code context can still
//                      reach the verifier.
//                      CONTROL: a name genuinely absent from the line must NOT reach it.
//
//  C (envvars.js:46)  A name that is a substring of unrelated package.json text
//                      makes the checker bail to unverifiable. If so this is the
//                      SAFE direction (over-cautious), not a defect.
//                      CONTROL: a name truly absent everywhere must reach contradicted.
//
// A result without both controls is not a result.

const BASE = 'file:///D:/Project/_reference_repos/earlgreyhot1701D__readme-clew-2__HEAD-7d2c0e0/lib/verifiers';
const { verifyCoverage } = await import(`${BASE}/coverage.js`);
const { verifyDependency } = await import(`${BASE}/dependencies.js`);
const { verifyEnvVar } = await import(`${BASE}/envvars.js`);

const lines = [];
const log = (s = '') => { lines.push(s); console.log(s); };
let fails = 0;

function arm(id, label, claim, controlClaim, actual, expected, ctrlActual, ctrlExpected) {
  const ok = actual === expected;
  const okc = ctrlActual === ctrlExpected;
  if (!ok || !okc) fails++;
  log(`${ok ? 'ok  ' : 'FAIL'} [${id}] ${label}`);
  log(`       claim   : ${claim}  -> ${actual}   (expect ${expected})`);
  log(`       control : ${controlClaim}  -> ${ctrlActual}   (expect ${ctrlExpected})`);
  log(`       controls ${okc ? 'PASS' : 'FAIL'}`);
  log('');
}

function repo(extra = {}) {
  return {
    pkg: { name: 'demo', dependencies: {}, devDependencies: {}, scripts: {} },
    files: ['package.json', 'index.js'],
    sources: { 'index.js': "const x = 1;\n" },
    workspaces: [],
    ...extra,
  };
}

// ---------------------------------------------------------------- A. coverage
log('=== A. coverage.js:24 — "is the package mentioned in the README?" ===');
{
  // The real instance: devDependency `ava`, README mentions .../javascript/... and "ava"script
  const r = repo();
  r.pkg.devDependencies = { ava: '^6' };
  r.sources = { 'index.js': "import t from 'ava';\n" };

  const readmeSub = 'See https://mozilla.org/en-us/docs/web/javascript/reference/iteratio for the api.';
  const readmeTok = 'Tests run with `ava`.';

  const a = verifyCoverage(readmeSub, r).map((f) => f.name);
  const c = verifyCoverage(readmeTok, r).map((f) => f.name);

  // harness control: a README that does NOT mention `ava` at all must be reported,
  // otherwise the harness cannot see a finding and every arm is void.
  const nowhere = verifyCoverage('Just a title and some prose.', r).map((f) => f.name);
  log(`       HARNESS CONTROL: no mention of \`ava\` anywhere -> ${nowhere.length === 1 ? 'reported' : 'suppressed'} (must be reported)`);
  if (nowhere.length !== 1) { fails++; log('       HARNESS CONTROL FAILED - arms void'); }
  log('');

  arm('A1', 'substring-only mention suppresses a real Missing',
    '`ava` present only inside "javascript"/"api"',
    '`ava` present as a standalone token',
    a.length === 0 ? 'suppressed' : 'reported', 'suppressed',
    c.length === 0 ? 'suppressed' : 'reported', 'suppressed');
}

// ---------------------------------------------------------------- B. prose guard
log('=== B. dependencies.js:54 — prose guard decides if a line is a code claim ===');
{
  const r = repo();
  r.pkg.dependencies = { leftpad: '^1' };
  r.sources = { 'index.js': "import leftpad from 'leftpad';\n" };

// name appears ONLY as a substring of a longer word on an install line
  const sub = { text: 'Run `npm i canvas-parser` to start.', inFence: false };
  // same name, same word, but plain prose - no install command
  const prose = { text: 'The canvas API is used for drawing.', inFence: false };
  // name genuinely absent from the line entirely
  const absent = { text: 'Run `npm i leftpad` to start.', inFence: false };

  const a = verifyDependency('can', r, sub).bucket;
  const p = verifyDependency('can', r, prose).bucket;
  const c = verifyDependency('nevermentioned', r, sub).bucket;

  log(`       install line, substring only : ${a}`);
  log(`       same word in plain prose     : ${p}   <- the guard holds here`);
  log(`       name absent from the line    : ${c}   <- the guard holds here`);
  log('');
  arm('B1', 'substring-only name on an install line',
    'name "can" vs install line containing only "canvas-parser"',
    'same name in prose, and name absent from install line',
    a, 'contradicted',
    p, 'unverifiable');
  if (c !== 'unverifiable') { fails++; log('       second control deviated'); }
}

// ---------------------------------------------------------------- C. envvars
log('=== C. envvars.js:46 — bail-out when the name appears anywhere in package.json ===');
{
  const r = repo();
  r.pkg.scripts = { greet: 'echo hi' };

  const a = verifyEnvVar('hi', r).bucket;   // 'hi' is a substring of 'echo hi'
  const c = verifyEnvVar('API_KEY', r).bucket; // genuinely nowhere

  arm('C1', 'substring-only hit inside package.json text',
    'name "hi" found only inside the script "echo hi"',
    'name "API_KEY" absent everywhere',
    a, 'contradicted',
    c, 'contradicted');
}

// ---------------------------------------------------------------- summary
log('='.repeat(64));
if (fails === 0) log('all arms behaved as expected');
else log(`${fails} arm(s) deviated from the frozen expectation`);