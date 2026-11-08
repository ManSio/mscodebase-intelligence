// Does the proposed token-boundary fix actually behave?
// Proposed: (?<![A-Za-z0-9_@/-])NAME(?![A-Za-z0-9_/.-])
// Tested against every case from EXP_coverage_substring.mjs before proposing it.

function mentions(readmeLower, name) {
  const esc = name.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&');
  return new RegExp(`(?<![A-Za-z0-9_@/-])${esc}(?![A-Za-z0-9_/.-])`, 'i').test(readmeLower);
}

const CASES = [
  // [readme, package, shouldCountAsMentioned, why]
  ['install lodash first', 'lodash', true, 'standalone name'],
  ['built with React 19', 'react', true, 'name + version'],
  ['we use lodash-es instead of hand-rolled helpers', 'lodash', false, 'lodash-es present, `lodash` itself never named'],
  ['once you got it working', 'got', true, 'the English verb IS the package name here -> genuinely ambiguous'],
  ['use the canvas element', 'can', false, '"can" inside "canvas"'],
  ['mozilla.org/en-us/docs/web/javascript/reference/iteratio', 'ava', false, '"ava"script (real yocto-queue case)'],
  ['uses the MCP SDK', '@modelcontextprotocol/sdk', false, 'alias, not the literal name'],
  ['the `ava` test runner', 'ava', true, 'backticked standalone'],
  ['ava@5.0.0', 'ava', true, 'name with version pin'],
  ['yoga-layout', 'yoga', false, 'subpath of another package'],
  ['we depend on leftpad', 'leftpad', true, 'plain mention'],
  ['nothing relevant here', 'leftpad', false, 'absent'],
];

let ok = 0, bad = 0;
for (const [readme, name, should, why] of CASES) {
  const got = mentions(readme.toLowerCase(), name);
  const pass = got === should;
  pass ? ok++ : bad++;
  console.log(pass ? 'ok   ' : 'FAIL ',
    `("${readme.slice(0, 42)}" , ${name})`.padEnd(58),
    'got=' + String(got).padEnd(6), 'want=' + String(should).padEnd(6), '|', why);
}
console.log(`\n${ok}/${CASES.length} correct, ${bad} wrong`);