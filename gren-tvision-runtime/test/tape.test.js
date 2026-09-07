'use strict';

// Unit tests for reading a tape.
//
// `record.test.js` is about what may be written; this is about what may be
// concluded. They are different failures: a recorder that writes a secret is a
// leak, and a reader that reports a drag as fifty events, or misses that
// twenty of them changed nothing, is a reader nobody uses -- which costs the
// tape its whole reason for existing.
//
// Every case here is a tape built by hand, because the shapes worth testing
// are the ones a session is unlikely to contain on demand: a file with two
// runs appended to it, a request nobody answered, a render with no message
// under it, a format older than this reader.

const test = require('node:test');
const assert = require('node:assert');

const { read, analyse, format } = require('../tape');
const { TAPE } = require('../record');
const { PROTOCOL } = require('../tui');

function header(over = {}) {
  return {
    tape: TAPE,
    at: '2026-09-07T00:00:00.000Z',
    redacted: true,
    program: { name: 'p', version: '1.0.0', argv: ['/x/p.js'], cwd: '/w' },
    protocol: PROTOCOL,
    runtime: { node: process.version, platform: 'linux', arch: 'x64', release: '0', timeZone: 'UTC' },
    terminal: { isTTY: true, columns: 80, rows: 25, env: {} },
    envNames: [],
    ...over,
  };
}

function tape(events, over = {}) {
  return [header(over), ...events].map((l) => JSON.stringify(l)).join('\n') + '\n';
}

/** The analysis of a one-session tape. */
function one(text, opts) {
  const { sessions } = read(text);
  return analyse(sessions[0], opts);
}

const render = (t, hash, windows = []) => ({ t, out: 'render', hash, windows, overlays: 0 });

test('a file with two runs appended to it reads as two sessions', () => {
  const text = tape([render(1, 'a'), { t: 2, end: 'exit' }]) + tape([render(1, 'b')]);
  const { sessions, problems } = read(text);
  assert.equal(sessions.length, 2);
  assert.equal(problems.length, 0);
  assert.equal(sessions[0].events.length, 2);
  assert.equal(sessions[1].events.length, 1);
});

test('a line that is not JSON is a problem and not the end of the reading', () => {
  const text = tape([render(1, 'a')]).trimEnd() + '\n{ not json\n' + JSON.stringify(render(2, 'b')) + '\n';
  const { sessions, problems } = read(text);
  assert.equal(sessions.length, 1);
  assert.equal(sessions[0].events.length, 2);
  assert.match(problems[0], /line 3 is not JSON/);
});

test('events before any header are a problem rather than a crash', () => {
  const { sessions, problems } = read(JSON.stringify(render(1, 'a')) + '\n');
  assert.equal(sessions.length, 0);
  assert.match(problems[0], /before any header/);
});

test('a drag is one row, saying where the window started and where it stopped', () => {
  const a = one(
    tape([
      render(1, 'h', ['w']),
      { t: 2, in: { type: 'windowResized', id: 'w', rect: [1, 1, 20, 10] } },
      render(3, 'h', ['w']),
      { t: 4, in: { type: 'windowResized', id: 'w', rect: [2, 1, 21, 10] } },
      render(5, 'h', ['w']),
      { t: 6, in: { type: 'windowResized', id: 'w', rect: [3, 1, 22, 10] } },
      render(7, 'h', ['w']),
    ])
  );
  const row = a.rows[1];
  assert.match(row.text, /^w moved ×3 /);
  assert.match(row.text, /\[1,1,20,10\] → \[3,1,22,10\]/);
});

test('a window pulled by its corner resized rather than moved', () => {
  const a = one(
    tape([
      render(1, 'h', ['w']),
      { t: 2, in: { type: 'windowResized', id: 'w', rect: [1, 1, 20, 10] } },
      render(3, 'i', ['w']),
      { t: 4, in: { type: 'windowResized', id: 'w', rect: [1, 1, 30, 10] } },
      render(5, 'j', ['w']),
    ])
  );
  assert.match(a.rows[1].text, /^w resized ×2/);
});

test('a run whose renders all match the screen it started on says so', () => {
  const a = one(
    tape([render(1, 'a'), { t: 2, in: { type: 'command', cmd: 'x' } }, render(3, 'a')])
  );
  assert.equal(a.rows[1].effect, 'unchanged');
});

test('and a run that changed the screen gives the hash a replay would compare', () => {
  const a = one(
    tape([render(1, 'a'), { t: 2, in: { type: 'command', cmd: 'x' } }, render(3, 'bbbbbbbbbb')])
  );
  assert.equal(a.rows[1].effect, 'bbbbbbbb');
});

test('a window that appeared and one that went away are named', () => {
  const a = one(
    tape([
      render(1, 'a', []),
      { t: 2, in: { type: 'command', cmd: 'tool.hex' } },
      render(3, 'b', ['hex']),
      { t: 4, in: { type: 'windowClosed', id: 'hex' } },
      render(5, 'c', []),
    ])
  );
  assert.match(a.rows[1].effect, /\+hex/);
  assert.match(a.rows[2].effect, /-hex/);
});

test('an input that produced no render at all is visible', () => {
  const a = one(tape([render(1, 'a'), { t: 2, in: { type: 'command', cmd: 'x' } }]));
  assert.equal(a.rows[1].effect, 'no render');
});

test('a rectangle with a negative origin is an anomaly', () => {
  const a = one(
    tape([
      render(1, 'a', ['w']),
      { t: 2, in: { type: 'windowResized', id: 'w', rect: [-5, 1, 59, 20] } },
      render(3, 'a', ['w']),
      { t: 4, end: 'exit' },
    ])
  );
  assert.equal(a.anomalies.length, 1);
  assert.match(a.anomalies[0].what, /off the top or left/);
});

test('and one past the edge is measured against the last resize, not the header', () => {
  // The header says 80x25 and the terminal then became 100x40. A rectangle
  // that fits the second and not the first must not be reported.
  const events = [
    { t: 1, in: { type: 'resized', cols: 100, rows: 40 } },
    render(2, 'a', ['w']),
    { t: 3, in: { type: 'windowResized', id: 'w', rect: [0, 0, 90, 30] } },
    render(4, 'a', ['w']),
    { t: 5, end: 'exit' },
  ];
  assert.deepEqual(one(tape(events)).anomalies, []);

  const past = events.slice();
  past[2] = { t: 3, in: { type: 'windowResized', id: 'w', rect: [0, 0, 120, 30] } };
  assert.match(one(tape(past)).anomalies[0].what, /past the 100x40 desktop/);
});

test('a request nobody answered is an anomaly, and an answered one is not', () => {
  const asked = [
    render(1, 'a'),
    { t: 2, in: { type: 'command', cmd: 'paste' } },
    { t: 2, out: 'readClipboard' },
    { t: 9, end: 'exit' },
  ];
  assert.match(one(tape(asked)).anomalies[0].what, /readClipboard was never answered/);

  const answered = asked.slice();
  answered.splice(3, 0, { t: 3, in: { type: 'clipboardText', fromSystem: true, text: 'hi' } });
  assert.deepEqual(one(tape(answered)).anomalies, []);
});

test('a tape that just stops says the program did not leave through an exit', () => {
  const a = one(tape([render(1, 'a')]));
  assert.match(a.anomalies[0].what, /no end line/);
});

test('a crash and a truncation are both anomalies', () => {
  const a = one(
    tape([
      render(1, 'a'),
      { t: 2, crash: 'uncaughtException', error: { message: 'boom' } },
      { t: 3, truncated: 16 },
      { t: 4, end: 'exit' },
    ])
  );
  assert.equal(a.anomalies.length, 2);
  assert.match(a.anomalies[0].what, /crashed in uncaughtException: boom/);
  assert.match(a.anomalies[1].what, /truncated/);
});

test('an older tape is told what it is missing, by name', () => {
  const a = one(tape([render(1, 'a'), { t: 2, end: 'exit' }], { tape: 1 }));
  assert.match(a.compatibility[0], /tape format 1, this build writes 2/);
  assert.match(a.compatibility[1], /random values/);
});

test('a tape from another protocol says a replay would compare two programs', () => {
  const a = one(tape([render(1, 'a'), { t: 2, end: 'exit' }], { protocol: PROTOCOL - 1 }));
  assert.match(a.compatibility[0], /two different programs/);
});

test('a wheel rolled out and back says how far it went, not only where it stopped', () => {
  const a = one(
    tape([
      render(1, 'a', ['h']),
      { t: 2, in: { type: 'scroll', id: 'h.s', value: 3 } },
      render(3, 'b', ['h']),
      { t: 4, in: { type: 'scroll', id: 'h.s', value: 18 } },
      render(5, 'c', ['h']),
      { t: 6, in: { type: 'scroll', id: 'h.s', value: 0 } },
      render(7, 'd', ['h']),
    ])
  );
  assert.match(a.rows[1].text, /scrolled 3 → 0, out to 18 ×3/);
});

test('a render with nothing under it is a tick, and the first one is init', () => {
  const a = one(tape([render(1, 'a'), render(9000, 'b')]));
  assert.match(a.rows[0].text, /first render/);
  assert.match(a.rows[1].text, /Time\.every tick/);
});

test('collapse:false keeps every message', () => {
  const events = [
    render(1, 'a', ['w']),
    { t: 2, in: { type: 'windowResized', id: 'w', rect: [1, 1, 20, 10] } },
    render(3, 'a', ['w']),
    { t: 4, in: { type: 'windowResized', id: 'w', rect: [2, 1, 21, 10] } },
    render(5, 'a', ['w']),
  ];
  assert.equal(one(tape(events)).rows.length, 2);
  assert.equal(one(tape(events), { collapse: false }).rows.length, 3);
});

test('a withheld draw is counted and says a replay cannot reproduce it', () => {
  const withheld = one(
    tape([render(1, 'a'), { t: 2, rng: 'getRandomValues', n: 16, sha: 'abc' }, { t: 3, end: 'exit' }])
  );
  assert.deepEqual(withheld.summary.random, { draws: 1, bytes: 16, withheld: 1 });
  assert.match(format(withheld), /a replay cannot reproduce them/);

  const kept = one(
    tape([render(1, 'a'), { t: 2, rng: 'getRandomValues', n: 16, value: 'AAA=' }, { t: 3, end: 'exit' }])
  );
  assert.equal(kept.summary.random.withheld, 0);
  assert.match(format(kept), /a replay can reproduce them/);
});

test('the report has the header, the summary and the timeline in it', () => {
  const text = format(
    one(tape([render(1, 'a', ['w']), { t: 2, in: { type: 'command', cmd: 'x' } }, render(3, 'b', ['w']), { t: 4, end: 'exit' }]))
  );
  assert.match(text, /program {3}p 1\.0\.0/);
  assert.match(text, /timeline/);
  assert.match(text, /command x/);
  // And no escape sequences: a tape of any length goes into a pager.
  assert.ok(!text.includes('\x1b'));
});

test('a second inbound stream is named and never folded into the first', () => {
  // predc's time converter answers over `intlIn`, which the launcher tees onto
  // the same tape. Two conversations that read as one would be worse than not
  // recording the second at all.
  const a = one(
    tape([
      render(1, 'a', ['time']),
      { t: 2, in: { type: 'command', cmd: 'zones' } },
      render(3, 'b', ['time']),
      { t: 4, in: { type: 'command', cmd: 'zones' }, port: 'intl' },
      render(5, 'c', ['time']),
    ])
  );
  assert.equal(a.rows.length, 3);
  assert.match(a.rows[2].text, /^\[intl\] command zones/);
});

test('a message this reader has never heard of is printed, and clipped', () => {
  const long = { type: 'rows', zones: 'x'.repeat(200) };
  const events = [render(1, 'a'), { t: 2, in: long }, render(3, 'b'), { t: 4, end: 'exit' }];
  // Printed rather than dropped: a tape written by a newer recorder than the
  // reader is the ordinary case the moment anybody else runs the program.
  assert.match(one(tape(events)).rows[1].text, /^rows zones="x+…$/);
  assert.ok(one(tape(events)).rows[1].text.length < 90);
  assert.ok(one(tape(events), { collapse: false }).rows[1].text.length > 200);
});
