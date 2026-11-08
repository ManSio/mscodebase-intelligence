// FROZEN EXPERIMENT INPUT — readme-clew-2 coverage.js substring semantics
// Frozen 2026-10-11, before running.
//
// Claim under test (from a third-party review): `readme.includes(name)`
// in lib/verifiers/coverage.js:24 is a token-match without normalization,
// so `missing` findings are mostly false positives (precision <0.3).
//
// Ground truth is BY CONSTRUCTION: each case declares whether the README
// really documents the package, and what the correct verdict must be.
// We do not ask "does it look right", we ask "did it match the declared truth".
//
// controls:
//   positive control — a package genuinely absent from the README MUST be flagged
//   negative control — a package genuinely named in the README MUST NOT be flagged

import { verifyCoverage } from './coverage_probe_target.mjs';

function pkg(dependencies = {}) {
  return { dependencies };
}

// [label, readme, importedPkg, declared?, shouldBeFlagged, why]
const CASES = [
  // --- negative control: documented, must NOT be flagged ---
  ['named exactly', 'install lodash first', 'lodash', pkg(), false,
    'README names it verbatim'],
  ['named with version', 'built with React 19', 'react', pkg(), false,
    'README names it with a version'],

  // --- positive control: undocumented, MUST be flagged ---
  ['truly absent', 'run the thing', 'lodash', pkg(), true,
    'README never mentions it'],
  ['absent, scoped', 'a tool', '@modelcontextprotocol/sdk', pkg(), true,
    'README never mentions the scoped name'],

  // --- suspected FALSE NEGATIVE: English word contains the package name ---
  ['short pkg vs English prose', 'once you got it working, ship it', 'got', pkg(), true,
    '"got" here is the English verb; package is undocumented'],
  ['pkg name inside another word', 'use the canvas element', 'can', pkg(), true,
    '"can" is a substring of "canvas"; package is undocumented'],
  ['pkg name inside longer pkg', 'we use lodash-es not lodash', 'lodash', pkg(), true,
    'lodash-es is a DIFFERENT package; `lodash` itself is undocumented'],

  // --- suspected FALSE POSITIVE: documented under a different name ---
  ['alias: MCP SDK', 'Uses the MCP SDK for tooling', '@modelcontextprotocol/sdk', pkg(), false,
    'documented under its common alias'],
  ['alias: "Model Context Protocol"', 'Built on the Model Context Protocol', '@modelcontextprotocol/sdk', pkg(), false,
    'documented under its spelled-out name'],
];

let correct = 0, wrong = 0;
const failures = [];

for (const [label, readme, name, p, shouldFlag, why] of CASES) {
  const repo = { pkg: p, files: ['src/a.js'], sources: { 'src/a.js': `import '${name}';` } };
  const findings = verifyCoverage(readme, repo);
  const flagged = findings.some((f) => f.name === name);
  const ok = flagged === shouldFlag;
  if (ok) correct++; else { wrong++; failures.push({ label, why, flagged, shouldFlag }); }
  console.log(
    ok ? 'ok   ' : 'FAIL ',
    label.padEnd(34),
    ('flagged=' + String(flagged)).padEnd(16),
    'expected=' + String(shouldFlag).padEnd(10),
    '|', why
  );
}

console.log(`\ncorrect ${correct}/${CASES.length}  wrong ${wrong}`);
if (failures.length) {
  console.log('\nDIVERGENCES (behaviour != ground truth):');
  for (const f of failures) console.log(' -', JSON.stringify(f));
}