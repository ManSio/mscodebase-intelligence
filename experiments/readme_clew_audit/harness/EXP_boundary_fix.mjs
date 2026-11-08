// Does one boundary rule fix BOTH sites without breaking the legitimate cases?
//
//   before : text.includes(name)
//   after  : new RegExp(`(?<![A-Za-z0-9_@/-])${esc(name)}(?![A-Za-z0-9_/.-])`, 'i').test(text)
//
// Frozen expectations. Every "keep" row MUST keep matching (no regression);
// every "stop" row MUST stop. Any mismatch is a verdict failure.

const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
function boundary(text, name) {
  return new RegExp(`(?<![A-Za-z0-9_@/-])${esc(name)}(?![A-Za-z0-9_/.-])`, 'i').test(text);
}
const raw = (text, name) => text.toLowerCase().includes(name.toLowerCase());
const fmt = (b) => (b ? 'match' : 'no');

const KEEP = [ // name genuinely IS documented -> must keep matching
  ['Tests run with `ava`.', 'ava', 'package in backticks'],
  ['Uses ava@6.0.0 for tests', 'ava', 'with a version pin'],
  ['npm i --save-dev ava', 'ava', 'inside an install command'],
  ['see the Ava library', 'ava', 'capitalised mid-sentence'],
  ['we use lodash-es not lodash', 'lodash', 'a real standalone mention beside another package'],
];

const STOP = [ // name only appears inside a longer word -> must stop matching
  ['mozilla.org/en-us/docs/web/javascript/reference/iteratio', 'ava', 'inside "javascript"'],
  ['the api changed', 'ava', 'inside "api"'],
  ['we use lodash-es', 'lodash', 'inside "lodash-es"'],
  ['Run `npm i canvas-parser`', 'can', 'inside "canvas-parser"'],
  ['a yoga-layout preset', 'yoga', 'inside "yoga-layout"'],
  ['target audience', 'get', 'inside "target"'],
  ['@types/node helper', 'types', 'inside "@types"'],
];

let bad = 0;
console.log('| text | name | before | after | want | verdict | why |');
console.log('|---|---|---|---|---|---|---|');
for (const [text, name, want, why] of [
  ...KEEP.map(([t, n, why]) => [t, n, true, why]),
  ...STOP.map(([t, n, why]) => [t, n, false, why]),
]) {
  const before = raw(text, name);
  const after = boundary(text, name);
  const ok = after === want;
  if (!ok) bad++;
  console.log(`| \`${text}\` | ${name} | ${fmt(before)} | ${fmt(after)} | ${fmt(want)} | ${ok ? 'ok' : '**MISMATCH**'} | ${why} |`);
}

const keepOk = KEEP.filter(([t, n]) => boundary(t, n)).length;
const stopOk = STOP.filter(([t, n]) => !boundary(t, n)).length;
const stopFixed = STOP.filter(([t, n]) => raw(t, n) && !boundary(t, n)).length;

console.log('');
console.log(`legitimate matches kept : ${keepOk}/${KEEP.length}`);
console.log(`false matches stopped  : ${stopOk}/${STOP.length}   (before the fix: ${STOP.filter(([t, n]) => !raw(t, n)).length}/${STOP.length} stopped)`);
console.log(`rows the fix changes   : ${stopFixed} of the ${STOP.length} false-match rows`);
console.log(`mismatches             : ${bad}`);
console.log('');
console.log(bad === 0 ? 'VERDICT: boundary rule is safe - no regression, fixes the substring half'
                     : 'VERDICT: mismatch present - do not propose');
console.log('');
console.log('Still out of reach for this rule, and honest to say so:');
console.log('  package "got" vs the English word "got" - both are real token matches.');
console.log('  @scope/name pairs where only part of the string is checked.');
console.log('  Those need an alias map or an ignore list, not a regex.');