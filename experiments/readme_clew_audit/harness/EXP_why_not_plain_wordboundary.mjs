// Is the obvious fix (`\b<name>\b`) enough here, or does it need the class form?
// Question only, with both sides shown. No claim until it runs.

const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

const plain = (t, n) => new RegExp(`\\b${esc(n)}\\b`, 'i').test(t);
const classed = (t, n) => new RegExp(`(?<![A-Za-z0-9_@/-])${esc(n)}(?![A-Za-z0-9_/.-])`, 'i').test(t);

const CASES = [
  ['we use lodash-es', 'lodash', false, 'sibling package'],
  ['Run npm i canvas-parser', 'can', false, 'inside canvas-parser'],
  ['a yoga-layout preset', 'yoga', false, 'sibling package'],
  ['target audience', 'get', false, 'inside target'],
  ['@types/node helper', 'types', false, 'inside the scope'],
  ['the api changed', 'ava', false, 'inside api'],
  ['Tests run with `ava`', 'ava', true, 'real mention'],
  ['npm i --save-dev ava', 'ava', true, 'real mention'],
  ['Uses ava@6.0.0', 'ava', true, 'real mention'],
];

const f = (b) => (b ? 'match' : 'no  ');
console.log('text                         name    \\b      class   want');
console.log('-'.repeat(66));
let plainBad = 0, classBad = 0;
for (const [t, n, want, why] of CASES) {
  const p = plain(t, n), c = classed(t, n);
  if (p !== want) plainBad++;
  if (c !== want) classBad++;
  console.log(`${t.padEnd(28)} ${n.padEnd(7)} ${f(p).padEnd(7)} ${f(c).padEnd(7)} ${f(want).padEnd(6)} ${why}`);
}
console.log('');
console.log(`plain \\b<name>\\b : ${CASES.length - plainBad}/${CASES.length} correct`);
console.log(`class rule      : ${CASES.length - classBad}/${CASES.length} correct`);
console.log('');
if (classBad === 0 && plainBad > 0) console.log('=> the obvious \\b fix is NOT enough; the class form is needed');
else if (classBad === 0 && plainBad === 0) console.log('=> plain \\b would have been enough; the class form is extra safety');
else console.log('=> class rule also fails somewhere - do not propose either');