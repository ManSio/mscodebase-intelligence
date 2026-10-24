import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const REF = 'D:/Project/_reference_repos/earlgreyhot1701D__readme-clew-2__HEAD-7d2c0e0';
const mod = await import(`file:///${REF}/scripts/sync-extension.mjs`);
const { NOTE, ROOT, drift } = mod;

const p = join(ROOT, 'extension/shared/README.txt');
const raw = readFileSync(p);
const txt = raw.toString('utf8');

console.log('file bytes      :', raw.length);
console.log('NOTE bytes      :', Buffer.byteLength(NOTE, 'utf8'));
console.log('file has CR     :', raw.includes(0x0d));
console.log('NOTE has CR     :', NOTE.includes('\r'));
console.log('equal as text   :', txt === NOTE);
console.log('equal normalized:', txt.replace(/\r\n/g, '\n') === NOTE);
console.log('drift()         :', JSON.stringify(drift()));

const a = txt, b = NOTE;
for (let i = 0; i < Math.max(a.length, b.length); i++) {
  if (a[i] !== b[i]) {
    console.log('first diff at char', i);
    console.log('  file=', JSON.stringify(a.slice(Math.max(0, i - 30), i + 30)));
    console.log('  note=', JSON.stringify(b.slice(Math.max(0, i - 30), i + 30)));
    break;
  }
}