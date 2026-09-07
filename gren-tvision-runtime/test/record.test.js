'use strict';

// Unit tests for the tape.
//
// This is the layer the rules belong at, for the same reason `diff.test.js` is
// where "what the differ decides to call" belongs and `programmers-edc/tests/`
// is where "what predc writes into its config file" belongs: a pty driver can
// only reach the states the user interface can produce, and what a recorder
// must *not* write is a much bigger set than what a person can be driven into
// typing. The most important assertion in this file is a negative one -- that a
// secret handed to the program does not come out the other end -- and there is
// no keystroke that proves it.

const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');

const { createRecorder, recordRandomness, takeRecordFlags, redact, TAPE } = require('../record');

let n = 0;
function tapePath() {
  return path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'tape-')), `t${n++}.jsonl`);
}

/** The tape, parsed: the header and every line after it. */
function readTape(file) {
  const lines = fs
    .readFileSync(file, 'utf8')
    .split('\n')
    .filter((l) => l.length)
    .map((l) => JSON.parse(l));
  return { header: lines[0], events: lines.slice(1), raw: fs.readFileSync(file, 'utf8') };
}

function open(over = {}) {
  const file = tapePath();
  const rec = createRecorder({
    path: file,
    protocol: 22,
    argv: ['predc', 'hex', 'dump.bin'],
    cwd: '/work',
    env: { TERM: 'xterm-256color', AWS_SECRET_ACCESS_KEY: 'hunter2', HOME: '/home/x' },
    program: { name: 'predc', version: '0.1.0' },
    ...over,
  });
  return { file, rec };
}

test('the header says what the program was and what it was run on', () => {
  const { file, rec } = open();
  rec.close();
  const { header } = readTape(file);
  assert.equal(header.tape, TAPE);
  assert.equal(header.protocol, 22);
  assert.equal(header.program.name, 'predc');
  assert.equal(header.program.version, '0.1.0');
  // argv without the interpreter: the words the user typed are what a replay
  // has to reproduce, and `process.execPath` is not one of them.
  assert.deepEqual(header.program.argv, ['hex', 'dump.bin']);
  assert.equal(header.program.cwd, '/work');
  assert.equal(header.runtime.node, process.version);
});

test('the environment is recorded by name, and TERM by value', () => {
  const { file, rec } = open();
  rec.close();
  const { header, raw } = readTape(file);
  assert.deepEqual(header.envNames, ['AWS_SECRET_ACCESS_KEY', 'HOME', 'TERM']);
  assert.equal(header.terminal.env.TERM, 'xterm-256color');
  // The one that matters: knowing the variable is set is often the answer,
  // and what is in it never is.
  assert.ok(!raw.includes('hunter2'), 'a secret value must not reach the tape');
  assert.ok(!raw.includes('/home/x'), 'nor should a value that merely looks harmless');
});

test('an inbound message is the tape', () => {
  const { file, rec } = open();
  rec.inbound({ type: 'key', id: 'canvas', key: 'Ctrl-K' });
  rec.close();
  const { events } = readTape(file);
  assert.deepEqual(events[0].in, { type: 'key', id: 'canvas', key: 'Ctrl-K' });
  assert.equal(typeof events[0].t, 'number');
  assert.equal(events[0].port, undefined, 'the tui port is the default and is not named');
});

test('a second port is named, so a replay knows which stream to feed', () => {
  const { file, rec } = open();
  rec.inbound({ type: 'zones', zones: ['UTC'] }, 'intl');
  rec.close();
  assert.equal(readTape(file).events[0].port, 'intl');
});

test('a document is reduced to its shape, not kept', () => {
  const { file, rec } = open();
  rec.inbound({ type: 'editorText', id: 'note', text: 'the diary of a nobody' });
  rec.inbound({ type: 'clipboardText', text: 'ssh-rsa AAAA...', fromSystem: true });
  rec.close();
  const { events, raw } = readTape(file);
  assert.equal(events[0].in.text, undefined);
  assert.equal(events[0].in.withheld.chars, 21);
  assert.equal(events[0].in.withheld.field, 'text');
  assert.match(events[0].in.withheld.sha, /^[0-9a-f]{16}$/);
  // The rest of the message survives: the id is what says *which* editor, and
  // withholding it would withhold the bug.
  assert.equal(events[0].in.id, 'note');
  assert.equal(events[1].in.fromSystem, true);
  assert.ok(!raw.includes('nobody') && !raw.includes('ssh-rsa'));
});

test('--record-verbatim keeps the document', () => {
  const { file, rec } = open({ verbatim: true });
  rec.inbound({ type: 'editorText', id: 'note', text: 'the diary of a nobody' });
  rec.close();
  const { header, events } = readTape(file);
  assert.equal(header.redacted, false);
  assert.equal(events[0].in.text, 'the diary of a nobody');
});

test('a keystroke is never redacted, because redacting it is redacting the bug', () => {
  const { file, rec } = open();
  rec.inbound({ type: 'key', id: 'search', key: 'h' });
  rec.close();
  assert.equal(readTape(file).events[0].in.key, 'h');
});

test('a render is fingerprinted, never written', () => {
  const { file, rec } = open();
  const render = {
    type: 'render',
    protocol: 22,
    windows: [
      { id: 'env', items: [{ type: 'staticText', text: 'AWS_SECRET_ACCESS_KEY=hunter2' }] },
      { id: 'hex', items: [] },
    ],
    overlays: [{ id: 'o' }],
  };
  rec.outbound(render);
  rec.close();
  const { events, raw } = readTape(file);
  assert.equal(events[0].out, 'render');
  assert.deepEqual(events[0].windows, ['env', 'hex']);
  assert.equal(events[0].overlays, 1);
  assert.match(events[0].hash, /^[0-9a-f]{16}$/);
  // The measured reason renders are not recorded: `predc env` puts the user's
  // environment block in the render payload verbatim.
  assert.ok(!raw.includes('hunter2'), 'a render must not carry its payload onto the tape');
});

test('the same render twice has the same fingerprint, and a changed one does not', () => {
  const { file, rec } = open();
  const render = (title) => ({ type: 'render', windows: [{ id: 'w', title }] });
  rec.outbound(render('a'));
  rec.outbound(render('a'));
  rec.outbound(render('b'));
  rec.close();
  const [one, two, three] = readTape(file).events;
  assert.equal(one.hash, two.hash, 'a replay checks itself against these');
  assert.notEqual(one.hash, three.hash);
});

test('an outbound message keeps its type and its id and nothing else', () => {
  const { file, rec } = open();
  rec.outbound({ type: 'setEditorText', id: 'note', text: 'forty kilobytes of diary' });
  rec.outbound({ type: 'dialog', spec: { id: 'open', items: [] } });
  rec.outbound({ type: 'quit' });
  rec.close();
  const { events, raw } = readTape(file);
  assert.deepEqual(
    events.filter((e) => e.out).map((e) => [e.out, e.id]),
    [
      ['setEditorText', 'note'],
      ['dialog', 'open'],
      ['quit', undefined],
    ]
  );
  assert.ok(!raw.includes('diary'));
});

test('a crash is the last thing on the tape and carries the stack', () => {
  const { file, rec } = open();
  rec.inbound({ type: 'key', id: 'canvas', key: 'x' });
  rec.crash('uncaughtException', new TypeError('cannot read properties of undefined'));
  rec.close('error');
  const { events } = readTape(file);
  assert.equal(events[1].crash, 'uncaughtException');
  assert.equal(events[1].error.name, 'TypeError');
  assert.match(events[1].error.message, /cannot read properties/);
  assert.ok(Array.isArray(events[1].error.stack) && events[1].error.stack.length > 1);
  assert.equal(events[2].end, 'error');
});

test('a message that will not serialise does not take the program down', () => {
  const { file, rec } = open();
  const loop = { type: 'key' };
  loop.self = loop;
  rec.inbound(loop);
  rec.inbound({ type: 'key', id: 'c', key: 'y' });
  rec.close();
  const { events } = readTape(file);
  assert.ok(events[0].unserialisable, 'the failure is recorded rather than thrown');
  assert.equal(events[1].in.key, 'y', 'and the tape carries on');
});

test('the tape stops rather than filling a disk', () => {
  const { file, rec } = open({ maxBytes: 900 });
  for (let i = 0; i < 200; i++) rec.inbound({ type: 'key', id: 'canvas', key: String(i) });
  rec.close();
  const { events } = readTape(file);
  const last = events[events.length - 1];
  assert.equal(last.truncated, 900);
  assert.ok(events.length < 200, `stopped after ${events.length} events`);
  assert.ok(fs.statSync(file).size < 2000);
});

test('--record is taken out of argv, because the program parses argv itself', () => {
  const argv = ['/usr/bin/node', 'predc', '--record', '/tmp/bug.tape', 'hex', 'x.bin'];
  const record = takeRecordFlags(argv, 'predc');
  assert.deepEqual(record, { path: '/tmp/bug.tape', verbatim: false });
  assert.deepEqual(argv, ['/usr/bin/node', 'predc', 'hex', 'x.bin']);
});

test('--record-verbatim is the same flag with the withholding turned off', () => {
  const argv = ['node', 'predc', 'notes', '--record-verbatim', '/tmp/bug.tape'];
  const record = takeRecordFlags(argv, 'predc');
  assert.deepEqual(record, { path: '/tmp/bug.tape', verbatim: true });
  assert.deepEqual(argv, ['node', 'predc', 'notes']);
});

test('neither flag is null, not a recorder that writes nowhere', () => {
  const argv = ['node', 'predc', 'hex'];
  assert.equal(takeRecordFlags(argv, 'predc'), null);
  assert.deepEqual(argv, ['node', 'predc', 'hex']);
});

// The crash handlers have to be tested in a process of their own: they end in
// `process.exit(1)`, which is the behaviour under test and not something a
// test runner can be asked to tolerate.
test('a crash with no callback under it is caught, recorded and made visible', () => {
  const { execFileSync } = require('child_process');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'crash-'));
  const tape = path.join(dir, 'bug.tape');
  const log = path.join(dir, 'state', 'predc', 'crash.log');
  const script = path.join(dir, 'boom.js');
  fs.writeFileSync(
    script,
    `const { createRecorder, installCrashHandlers } = require(${JSON.stringify(
      path.join(__dirname, '..', 'record.js')
    )});
     const rec = createRecorder({ path: ${JSON.stringify(tape)}, protocol: 22 });
     installCrashHandlers({ recorder: rec, crashLog: ${JSON.stringify(log)},
                            program: { name: 'predc', version: '0.1.0' } });
     rec.inbound({ type: 'key', id: 'canvas', key: 'q' });
     // From a timer, which is the case the binding cannot see: a callback that
     // throws synchronously is caught in C++ and rethrown once the terminal is
     // back, and this one is not a callback at all.
     setTimeout(() => { throw new Error('the pump is not under this'); }, 0);
    `
  );

  let status = 0;
  let stdout = '';
  let stderr = '';
  try {
    execFileSync(process.execPath, [script], { encoding: 'utf8' });
  } catch (err) {
    status = err.status;
    stdout = err.stdout;
    stderr = err.stderr;
  }

  assert.equal(status, 1, 'a crash is an exit 1, not a hang');

  // The terminal comes back. Without this the user sees a hung window: the
  // process is gone and the alternate screen is still up.
  assert.ok(stdout.includes('\x1b[?1049l'), 'leaves the alternate screen');
  assert.ok(stdout.includes('\x1b[?25h'), 'brings the cursor back');
  assert.ok(stdout.includes('\x1b[?1000l'), 'stops mouse reporting');

  // Said out loud, and kept.
  assert.match(stderr, /the pump is not under this/);
  assert.match(stderr, /crash\.log/);
  assert.match(stderr, /everything you typed/);

  const { events } = readTape(tape);
  const crash = events.find((e) => e.crash);
  assert.equal(crash.crash, 'uncaughtException');
  assert.match(crash.error.message, /the pump is not under this/);
  assert.equal(events[0].in.key, 'q', 'and the event before it is still there');

  // The crash log exists whether or not anybody asked for a tape, which is the
  // entire point of it: a crash happens on the run nobody was recording.
  const logged = JSON.parse(fs.readFileSync(log, 'utf8').trim());
  assert.equal(logged.where, 'uncaughtException');
  assert.equal(logged.program.name, 'predc');
  assert.equal(logged.tape, tape);
});

test('a rejected promise is the same crash', () => {
  const { execFileSync } = require('child_process');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'crash-'));
  const log = path.join(dir, 'crash.log');
  const script = path.join(dir, 'boom.js');
  fs.writeFileSync(
    script,
    `const { installCrashHandlers } = require(${JSON.stringify(
      path.join(__dirname, '..', 'record.js')
    )});
     installCrashHandlers({ crashLog: ${JSON.stringify(log)} });
     Promise.reject(new Error('nobody awaited this'));
    `
  );
  let status = 0;
  try {
    execFileSync(process.execPath, [script], { encoding: 'utf8' });
  } catch (err) {
    status = err.status;
  }
  assert.equal(status, 1);
  const logged = JSON.parse(fs.readFileSync(log, 'utf8').trim());
  assert.equal(logged.where, 'unhandledRejection');
  assert.match(logged.error.message, /nobody awaited this/);
  assert.equal(logged.tape, undefined, 'no tape was asked for, and none is claimed');
});

test('redact leaves an ordinary message alone rather than cloning it', () => {
  const message = { type: 'click', id: 'w', x: 3, y: 4 };
  assert.equal(redact(message), message);
});

// --- What never crossed a port -------------------------------------------
//
// `Crypto` is a Gren task rather than a message, so nothing in the runtime
// sees a draw happen; the recorder reaches into node's crypto module to hear
// about it. These are the tests that the reaching works, that it hands back
// what it was given, and -- the one that matters -- that the bytes themselves
// stay off a redacted tape, for the same reason a clipboard does: the whole
// point of the random tool is to make a value somebody is about to use.

test('the header says which zone the machine thinks it is in', () => {
  const { file, rec } = open();
  rec.close();
  const { header } = readTape(file);
  assert.equal(header.runtime.timeZone, Intl.DateTimeFormat().resolvedOptions().timeZone);
});

test('TZ is recorded by value, because it decides what two tools draw', () => {
  const { file, rec } = open({ env: { TZ: 'Asia/Seoul', SECRET: 'hunter2' } });
  rec.close();
  const { header, raw } = readTape(file);
  assert.equal(header.terminal.env.TZ, 'Asia/Seoul');
  assert.ok(!raw.includes('hunter2'));
});

test('a random draw is recorded as a shape, and the bytes are not on the tape', () => {
  const { file, rec } = open();
  recordRandomness(rec);
  const array = new Uint8Array(8);
  require('crypto').getRandomValues(array);
  recordRandomness(null);
  rec.close();

  const { events, raw } = readTape(file);
  const draw = events.find((e) => e.rng);
  assert.equal(draw.rng, 'getRandomValues');
  assert.equal(draw.n, 8);
  assert.equal(draw.value, undefined);
  assert.equal(typeof draw.sha, 'string');
  assert.ok(!raw.includes(Buffer.from(array).toString('base64')));
});

test('the program is handed the system\'s own randomness, unchanged', () => {
  const { file, rec } = open();
  recordRandomness(rec);
  // Two draws of the same length that came out equal would mean the wrapper
  // was answering rather than passing through.
  const a = new Uint8Array(16);
  const b = new Uint8Array(16);
  require('crypto').getRandomValues(a);
  require('crypto').getRandomValues(b);
  recordRandomness(null);
  rec.close();
  assert.notDeepEqual([...a], [...b]);
  assert.notDeepEqual([...a], new Array(16).fill(0));
  assert.equal(readTape(file).events.filter((e) => e.rng).length, 2);
});

test('verbatim keeps the bytes, because then the value is the bug', () => {
  const { file, rec } = open({ verbatim: true });
  recordRandomness(rec);
  const array = new Uint8Array(8);
  require('crypto').getRandomValues(array);
  recordRandomness(null);
  rec.close();
  const draw = readTape(file).events.find((e) => e.rng);
  assert.equal(draw.value, Buffer.from(array).toString('base64'));
  assert.equal(draw.sha, undefined);
});

test('aiming the interception at nothing stops it recording', () => {
  const { file, rec } = open();
  recordRandomness(rec);
  recordRandomness(null);
  require('crypto').getRandomValues(new Uint8Array(4));
  rec.close();
  assert.equal(readTape(file).events.filter((e) => e.rng).length, 0);
});

test('a UUID is a draw too', () => {
  const { file, rec } = open();
  recordRandomness(rec);
  const id = require('crypto').randomUUID();
  recordRandomness(null);
  rec.close();
  const draw = readTape(file).events.find((e) => e.rng === 'randomUUID');
  assert.equal(draw.n, 36);
  assert.match(id, /^[0-9a-f-]{36}$/);
  assert.ok(!readTape(file).raw.includes(id));
});

test('the notice on the way out says whether the random values were kept', () => {
  const { rec } = open();
  assert.match(rec.notice, /everything you typed/);
  assert.match(rec.notice, /random\n  values generated; keystrokes were not/);
  assert.match(rec.notice, /Look at it before you send it/);

  const { rec: v } = open({ verbatim: true });
  assert.match(v.notice, /every random value the program generated/);
});
