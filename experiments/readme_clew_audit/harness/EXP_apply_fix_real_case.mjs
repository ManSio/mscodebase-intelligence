// A/B on the REAL case: same repo snapshot, old module vs patched module.
// Proof the patch changes behaviour only where it should.
const BEFORE = 'file:///D:/Project/_reference_repos/earlgreyhot1701D__readme-clew-2__HEAD-7d2c0e0/lib/verifiers/coverage.js';
const AFTER  = 'file:///D:/Project/_reference_repos/earlgreyhot1701D__readme-clew-2__LFverify/lib/verifiers/coverage.js';
const DBEFORE = 'file:///D:/Project/_reference_repos/earlgreyhot1701D__readme-clew-2__HEAD-7d2c0e0/lib/verifiers/dependencies.js';
const DAFTER  = 'file:///D:/Project/_reference_repos/earlgreyhot1701D__readme-clew-2__LFverify/lib/verifiers/dependencies.js';

const { verifyCoverage: covBefore } = await import(BEFORE);
const { verifyCoverage: covAfter }  = await import(AFTER);
const depBefore = await import(DBEFORE);
const depAfter  = await import(DAFTER);

// yocto-queue-shaped snapshot: one source file imports `ava`; README swaps avatar/javascript for it.
const repo = {
  pkg: { devDependencies: { ava: '^6.0.0' } },
  workspaces: [], files: [], workspacesTruncated: false,
  sources: { 'index.js': "import test from 'ava';\nexport default 1;\n" },
};

const READMES = [
  ['REAL BUG CASE (ava only inside javascript)', 'The API follows https://mozilla.org/en-us/docs/web/javascript/reference/iteration.'],
  ['CONTROL: README mentions ava properly',      'Tests are run with ava.'],
  ['CONTROL: README has no ava at all',          'A tiny queue library. No tests named here.'],
  ['CONTROL: ava as a lone word',                'We use ava for tests.'],
];

const missing = (fn, readme) => fn(readme, repo).filter((f) => f.bucket === 'missing').map((f) => f.name);
const row = (label, a, b) => {
  const sa = JSON.stringify(a), sb = JSON.stringify(b);
  console.log(`${label.padEnd(46)} before=${sa.padEnd(10)} after=${sb.padEnd(10)} ${sa === sb ? '(same)' : '(CHANGED)'}`);
};

console.log('--- coverage: is `ava` recognised as mentioned? ---');
for (const [label, readme] of READMES) {
  row(label, missing(covBefore, readme), missing(covAfter, readme));
}

console.log('');
console.log('--- dependencies: does the install line reach a code claim? ---');
const NAMES = [['ava', 'ava'], ['can', 'can']];
console.log(`module exports mentionsWord?  before=${typeof depBefore.mentionsWord}  after=${typeof depAfter.mentionsWord}`);
const ctx = { text: 'run `npm i canvas-parser` to start.', inFence: false };
for (const [label, name] of NAMES) {
  const b = depBefore.verifyDependency ? null : null;
  console.log(`  ${label.padEnd(6)} on install line => (see verifyDependency below)`);
}

// Direct: does a prose word inside a package-name token still reach a code claim?
// before: text.includes('can') true -> code claim; after: token rule -> false -> prose (safe).
console.log('');
console.log('--- the prose guard, called directly ---');
const beforeHit = depBefore.inCodeContext ? depBefore.inCodeContext(['can'], { text: 'run `npm i canvas-parser`', inFence: false }) : 'not exported';
const afterHit  = depAfter.mentionsWord ? ['can'].some((n) => depAfter.mentionsWord('run `npm i canvas-parser`', n)) : 'n/a';
console.log(`inCodeContext before (n/a if not exported) : ${depBefore.inCodeContext ? '' : 'not exported'}`);
console.log(`can inside "canvas-parser" recognised as a code claim?  before(n/a if not exported)`);
console.log(`  mentionsWord(after)     :     ${depAfter.mentionsWord('run npm i canvas-parser', 'can')}  (want false)`);
console.log(`  mentionsWord(after, ava):     ${depAfter.mentionsWord('run npm i ava', 'ava')}  (want true)`);
console.log(`  mentionsWord(after, lodash in "we use lodash-es here"): ${depAfter.mentionsWord('we use lodash-es here', 'lodash')}  (want false)`);
console.log(`  mentionsWord(after, ava at sentence end "we use ava."): ${depAfter.mentionsWord('we use ava.', 'ava')}  (want true)`);