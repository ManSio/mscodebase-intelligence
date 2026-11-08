// FROZEN EXPERIMENT INPUT — readme-clew-2 import-extraction recall
// Frozen 2026-10-11 before running. Verifies/refutes the claim that
// dependencies.js SPEC regex misses dynamic imports and `export ... from`.
//
// Method: call the REAL importedPackages() from their code on synthetic
// source snippets whose correct answer we know by construction.
// positive control: plain `import x from 'pkg'` MUST be found.
// negative control: a relative path and a node: builtin MUST NOT be returned.

import { importedPackages } from './deps_probe_target.mjs';

// Each case: [label, sourceText, expectedPackage|null]
const CASES = [
  ['static default', "import x from 'lodash';", 'lodash'],
  ['static named', "import { a } from 'lodash';", 'lodash'],
  ['static bare (side-effect)', "import 'lodash';", 'lodash'],
  ['dynamic import()', "const m = await import('lodash');", 'lodash'],
  ['dynamic import({})', "const m = await import(`lodash`);", 'lodash'], // backtick!
  ['export ... from', "export { a } from 'lodash';", 'lodash'],
  ['export * from', "export * from 'lodash';", 'lodash'],
  ['require()', "const x = require('lodash');", 'lodash'],
  ['scoped import', "import x from '@scope/pkg';", '@scope/pkg'],
  ['deep path import', "import x from 'lodash/merge';", 'lodash'],
  // negative controls:
  ['relative path', "import x from './local.js';", null],
  ['node builtin', "import fs from 'node:fs';", null],
  ['bare builtin', "import path from 'path';", null],
];

let posOK = 0, posTotal = 0, missed = [];
let negOK = 0, negTotal = 0, leaked = [];
for (const [label, text, expected] of CASES) {
  const found = importedPackages({ 'a.js': text });
  const got = [...found.keys()];
  const hit = got.includes(expected);
  if (expected !== null) {
    posTotal++;
    if (hit) posOK++; else missed.push([label, expected, got]);
  } else {
    negTotal++;
    const leakedAny = got.length > 0;
    if (!leakedAny) negOK++; else leaked.push([label, got]);
  }
  console.log(
    (expected !== null ? '[POS]' : '[NEG]'),
    (hit === (expected !== null) ? 'ok  ' : 'FAIL'),
    label.padEnd(26),
    'expected=' + String(expected).padEnd(16),
    'got=' + JSON.stringify(got)
  );
}
console.log(`\nPOS ${posOK}/${posTotal}   NEG ${negOK}/${negTotal}`);
if (missed.length) { console.log('MISSED:'); for (const m of missed) console.log('  ', JSON.stringify(m)); }
if (leaked.length) { console.log('LEAKED:'); for (const l of leaked) console.log('  ', JSON.stringify(l)); }