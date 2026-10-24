// A/B on site 2: the prose guard that can end in a false Contradicted.
// Calls the real exported function on both modules, same snapshot.
const BEFORE = await import('file:///D:/Project/_reference_repos/earlgreyhot1701D__readme-clew-2__HEAD-7d2c0e0/lib/verifiers/dependencies.js');
const AFTER  = 'file:///D:/Project/_reference_repos/earlgreyhot1701D__readme-clew-2__LFverify/lib/verifiers/dependencies.js';
const after = await import(AFTER);

const repo = { pkg: { dependencies: { express: '^4' } }, workspaces: [], files: [], sources: { 'index.js': "import x from 'express';\n" } };

const CASES = [
  ['can', 'run `npm i canvas-parser` to start.', 'substring of another package on an install line'],
  ['can', 'the canvas API draws things.', 'plain prose word'],
  ['express', 'run `npm i express` to start.', 'real package on an install line'],
  ['lodash', 'run `npm i lodash-es` instead.', 'sibling package on an install line'],
  ['leftpad', 'run `npm i leftpad` to start.', 'TRUE POSITIVE: real, undeclared package'],
];

console.log('name      text                                    BEFORE        AFTER         why');
console.log('-'.repeat(96));
let changed = 0;
for (const [name, text, why] of CASES) {
  const b = BEFORE.verifyDependency(name, repo, { text }).bucket;
  const a = after.verifyDependency(name, repo, { text }).bucket;
  if (a !== b) changed++;
  console.log(`${name.padEnd(9)} ${text.padEnd(39)} ${b.padEnd(13)} ${a.padEnd(13)} ${why}`);
}
console.log('');
console.log(`rows changed: ${changed} of ${CASES.length}`);
console.log('');
console.log('want: `can` in "canvas-parser" AND `lodash` in "lodash-es" stop being read as code claims');
console.log('      (contradicted -> unverifiable), while the two real commands stay contradicted.');