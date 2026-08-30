const m0 = require('./build/Release/m0.node');

const checks = [
  ['addon loaded', typeof m0.add === 'function'],
  ['add(2,3) === 5', m0.add(2, 3) === 5],
  ['ncursesw reachable', /ncurses/i.test(m0.cursesVersion())],
];

let ok = true;
for (const [name, pass] of checks) {
  console.log(`${pass ? 'ok  ' : 'FAIL'}  ${name}`);
  ok = ok && pass;
}
console.log(`\nnode      ${process.version}  (${process.execPath})`);
console.log(`ncurses   ${m0.cursesVersion()}`);
process.exit(ok ? 0 : 1);
