// RED TEAM, revision 2. Unambiguous cases are scored; genuinely debatable ones are
// shown but NOT scored (scoring a debatable case is how you fake a result).
const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

const NAIVE = (t, n) => t.toLowerCase().includes(String(n).toLowerCase());
const BOUND = (t, n) => new RegExp(`\\b${esc(n)}\\b`, 'i').test(t);
const V1 = (t, n) => new RegExp(`(?<![A-Za-z0-9_@/-])${esc(n)}(?![A-Za-z0-9_/.-])`, 'i').test(t);
const V2 = (t, n) => new RegExp(`(?<![A-Za-z0-9_@/-])${esc(n)}(?![A-Za-z0-9_]|[-./][A-Za-z0-9_])`, 'i').test(t);
const V3 = (t, n) => (n ? V2(t, n) : false);
// v5: token charset is npm's own (letters, digits, _ and -), so a dot or a slash does NOT
// extend the token. Keeps "We use ava." and treats "lodash/fp" as a mention of lodash.
const V5 = (t, n) => (n ? new RegExp(`(?<![A-Za-z0-9_@/-])${esc(n)}(?![A-Za-z0-9_-])`, 'i').test(t) : false);

const SCORED = [
  ['Tests run with `ava`.', 'ava', true, 'P backticks'],
  ['Uses ava@6.0.0 for tests', 'ava', true, 'P version pin'],
  ['npm i --save-dev ava', 'ava', true, 'P install cmd'],
  ['see the Ava library', 'ava', true, 'P capitalised'],
  ['We use ava.', 'ava', true, 'P SENTENCE END'],
  ['We use ava. It is fast.', 'ava', true, 'P period mid-sentence'],
  ['nyc, ava, and mocha', 'ava', true, 'P list'],
  ['- ava', 'ava', true, 'P bullet'],
  ['(ava)', 'ava', true, 'P parens'],
  ['ava!', 'ava', true, 'P bang'],
  ['use ava to run tests', 'ava', true, 'P plain'],
  ['See ava (the runner)', 'ava', true, 'P then bracket'],
  ['ava\nthe next line', 'ava', true, 'P before newline'],
  ['mozilla.org/en-us/docs/web/javascript/r', 'ava', false, 'N inside javascript'],
  ['we use lodash-es here', 'lodash', false, 'N sibling lodash-es'],
  ['a yoga-layout preset', 'yoga', false, 'N sibling yoga-layout'],
  ['@types/node helper', 'types', false, 'N inside @types'],
  ['@types/node helper', 'node', false, 'N node inside @types/node'],
  ['Run `npm i canvas-parser`', 'can', false, 'N inside canvas-parser'],
  ['target audience', 'get', false, 'N inside target'],
  ['my_ava custom', 'ava', false, 'N underscore prefix'],
  ['xava here', 'ava', false, 'N glued prefix'],
  ['ava2 runner', 'ava', false, 'N digit suffix'],
  ['uses Vite-Ava builder', 'ava', false, 'N hyphen-glued cap'],
  ['', 'ava', false, 'E empty text'],
  ['anything at all', '', false, 'E EMPTY NAME'],
  [' note here', '', false, 'E EMPTY NAME after space'],
];

// Debated in the field: a subpath/dot/filename. Both answers are defensible, so no score.
const DEBATABLE = [
  ['lodash/fp import', 'lodash', 'N? subpath of the SAME package'],
  ['lodash.merge called', 'lodash', 'N? dot method of the SAME package'],
  ['we use ava.js file', 'ava', 'E? a filename, maybe not the package'],
];

const RULES = [['naive', NAIVE], ['\\b', BOUND], ['v1', V1], ['v2', V2], ['v3', V3], ['v5', V5]];
const f = (b) => (b ? 'match' : 'no   ');
const fails = {};
let head = 'text'.padEnd(40) + 'name'.padEnd(8) + 'want  ' + RULES.map(([n]) => n.padEnd(6)).join('') + ' why';
console.log(head); console.log('-'.repeat(head.length + 6));
for (const [t, n, want, why] of SCORED) {
  const cells = RULES.map(([, fn]) => fn(t, n));
  cells.forEach((c, i) => { if (c !== want) fails[RULES[i][0]] = (fails[RULES[i][0]] || 0) + 1; });
  console.log(JSON.stringify(t).slice(0, 34).padEnd(40) + JSON.stringify(n).padEnd(8) + f(want) + '  ' + cells.map(f).join('') + ' ' + why);
}
console.log('');
console.log('SCORED RESULT'); for (const [n] of RULES) { const b = fails[n] || 0; console.log(`  ${n.padEnd(8)} ${SCORED.length - b}/${SCORED.length}${b ? '  <-- ' + b + ' wrong' : ''}`); }
console.log('');
console.log('DEBATABLE (no score - both answers arguable)');
for (const [t, n, why] of DEBATABLE) console.log('  ' + JSON.stringify(t).slice(0, 30).padEnd(32) + n.padEnd(8) + RULES.map(([, fn]) => f(fn(t, n))).join('') + ' ' + why);
console.log('  ' + '(columns: ' + RULES.map(([n]) => n).join(', ') + ')');
console.log('');
const b5 = fails['v5'] || 0;
console.log(b5 === 0 ? 'VERDICT: v5 scores 0 wrong on every unambiguous case, and keeps subpaths.' : `VERDICT: v5 fails ${b5} - not ready.`);