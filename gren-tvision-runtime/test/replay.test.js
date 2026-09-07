'use strict';

// Unit tests for feeding a tape back in.
//
// The program under test is a fake one: an object shaped like what `gren make`
// produces, with ports that emit whatever the test tells them to. That is not
// a compromise, it is the only way to write most of these -- a real program
// cannot be asked to say the wrong thing, to say nothing at all, or to say one
// more thing than the tape has, and those are exactly the cases a replayer
// exists to report. `drive_record.py` takes the other end: a real session
// through a real pty, replayed.

const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');

const { replay } = require('../replay');
const { read } = require('../tape');
const { digest, TAPE } = require('../record');
const { PROTOCOL } = require('../tui');

const AT = '2026-09-07T12:00:00.000Z';
const START = Date.parse(AT);

function header(over = {}) {
  return {
    tape: TAPE,
    at: AT,
    redacted: true,
    program: { name: 'p', version: '1', argv: ['/x/p.js'], cwd: process.cwd(), flags: {} },
    protocol: PROTOCOL,
    runtime: { node: process.version, platform: 'linux', arch: 'x64', release: '0', timeZone: 'Asia/Seoul' },
    terminal: { isTTY: true, columns: 100, rows: 30, colorDepth: 24, env: {} },
    envNames: [],
    ...over,
  };
}

/** A render, and the line a tape would carry for it. */
const render = (n) => ({ type: 'render', protocol: PROTOCOL, windows: [{ id: 'w' }], overlays: [], n });
const expected = (t, message, over = {}) => ({
  t,
  out: 'render',
  hash: digest(JSON.stringify(message)),
  windows: (message.windows || []).map((w) => w.id),
  overlays: 0,
  ...over,
});

function tape(events, over = {}) {
  return [header(over), ...events].map((l) => JSON.stringify(l)).join('\n') + '\n';
}

const session = (text) => read(text).sessions[0];

/**
 * A program shaped like a compiled Gren module.
 *
 * `onInit` is called a turn after `init`, which is what a real one does -- its
 * first render waits on a config file coming off a disk.
 */
function program({ onInit, onMessage } = {}) {
  return {
    Gren: {
      Main: {
        init({ flags }) {
          const subs = { tuiOut: [], intlOut: [] };
          const emit = (message, port = 'tuiOut') => subs[port].forEach((f) => f(message));
          const ports = {
            tuiOut: { subscribe: (f) => subs.tuiOut.push(f) },
            intlOut: { subscribe: (f) => subs.intlOut.push(f) },
            tuiIn: { send: (m) => onMessage && onMessage(m, emit, 'tui') },
            intlIn: { send: (m) => onMessage && onMessage(m, emit, 'intl') },
          };
          setTimeout(() => onInit && onInit(emit, flags), 0);
          return { ports };
        },
      },
    },
  };
}

test('a program that says what the tape says replays', async () => {
  const a = render(1);
  const b = render(2);
  const t = tape([
    expected(10, a),
    { t: 20, in: { type: 'resized', cols: 100, rows: 28 } },
    expected(30, b),
    { t: 40, end: 'exit' },
  ]);
  const result = await replay(
    program({ onInit: (emit) => emit(a), onMessage: (m, emit) => emit(b) }),
    session(t)
  );
  assert.equal(result.ok, true, JSON.stringify(result.divergence));
  assert.equal(result.matched, 2);
});

test('a render that differs is reported, with the message fed last', async () => {
  const a = render(1);
  const t = tape([
    expected(10, a),
    { t: 20, in: { type: 'command', cmd: 'tool.hex' } },
    expected(30, render(2)),
    { t: 40, end: 'exit' },
  ]);
  const result = await replay(
    program({ onInit: (emit) => emit(a), onMessage: (m, emit) => emit(render(99)) }),
    session(t)
  );
  assert.equal(result.ok, false);
  assert.equal(result.matched, 1);
  assert.match(result.divergence.why, /the render differs/);
  assert.equal(result.divergence.after.message.cmd, 'tool.hex');
});

test('a message is fed the moment the cursor reaches it', async () => {
  // From inside the subscription that brought the cursor to it, which is a
  // decision with a measured alternative behind it: feeding the binding's port
  // a turn later instead makes a replay perfectly deterministic and wrong
  // about a third of the drivers, because a recording's messages are coupled
  // to the program's own progress -- Turbo Vision's pump delivers the next
  // event only once the last render has been applied -- and a free turn is
  // not. FINDINGS has the numbers.
  const order = [];
  const first = render(1);
  const second = render(2);
  const t = tape([
    expected(10, first),
    { t: 11, in: { type: 'resized', cols: 100, rows: 28 } },
    expected(12, second),
    { t: 13, out: 'atInstant', port: 'intl' },
    { t: 20, end: 'exit' },
  ]);
  const result = await replay(
    program({
      onInit: (emit) => {
        emit(first);
        // Init's chain continues after the render, in the same turn: the
        // resize has to have landed in between, which is where the recording
        // this was taken from has it.
        order.push('init continued');
        emit({ type: 'atInstant' }, 'intlOut');
      },
      onMessage: (m, emit) => {
        order.push(`got ${m.type}`);
        emit(second);
      },
    }),
    session(t)
  );
  assert.equal(result.ok, true, JSON.stringify(result.divergence));
  assert.deepEqual(order, ['got resized', 'init continued']);
});

test('a program that goes quiet is a divergence, and says what was wanted', async () => {
  const a = render(1);
  const t = tape([expected(10, a), expected(20, render(2)), { t: 30, end: 'exit' }]);
  const result = await replay(program({ onInit: (emit) => emit(a) }), session(t), {
    timeoutMs: 200,
  });
  assert.equal(result.ok, false);
  // Set aside first, in case it was only late, and reported when the tape ran
  // out with it still outstanding.
  assert.match(result.divergence.why, /produced nothing at all/);
});

test('a program with more to say than the tape has says so', async () => {
  // Two renders where the tape has one, with something still expected after
  // it -- which is what makes this an extra rather than the recorder having
  // stopped writing.
  const a = render(1);
  const t = tape([
    expected(10, a),
    { t: 11, out: 'atInstant', port: 'intl' },
    { t: 20, in: { type: 'command', cmd: 'x' } },
    expected(30, render(2)),
    { t: 40, end: 'exit' },
  ]);
  const result = await replay(
    program({
      onInit: (emit) => {
        emit(a);
        emit(render(99)); // one the tape does not have
        emit({ type: 'atInstant' }, 'intlOut');
      },
      onMessage: (m, emit) => emit(render(2)),
    }),
    session(t)
  );
  assert.equal(result.ok, false);
  assert.equal(result.extra.length, 1);
  assert.equal(result.extra[0].port, 'tui');
});

test('but what it says after the tape stops is the recorder stopping', async () => {
  // The `end` line is written as the process leaves. Whatever the program said
  // on its way out was never written down, and holding a replay to it would be
  // holding it to the recorder's timing rather than the program's.
  const a = render(1);
  const result = await replay(
    program({
      onInit: (emit) => {
        emit(a);
        emit(render(2));
      },
    }),
    session(tape([expected(10, a), { t: 20, end: 'exit' }]))
  );
  assert.equal(result.ok, true, JSON.stringify(result.divergence || result.extra));
  assert.match(result.warnings.join('\n'), /after the tape's last line/);
});

test('two ports may swap places between an input and the next', async () => {
  // Init's own chain and the terminal's messages interleave differently on
  // two runs of the same session -- `predc time` records both orders. Within
  // one port the order is the program's and is asserted; across two it is the
  // recording machine's disk and is not.
  const a = render(1);
  const b = render(2);
  const t = tape([
    expected(10, a),
    { t: 20, in: { type: 'resized', cols: 100, rows: 28 } },
    expected(30, b),
    { t: 31, out: 'atInstant', port: 'intl' },
    { t: 40, end: 'exit' },
  ]);
  const result = await replay(
    program({
      onInit: (emit) => emit(a),
      onMessage: (m, emit) => {
        // The other way round from the tape.
        emit({ type: 'atInstant' }, 'intlOut');
        emit(b);
      },
    }),
    session(t)
  );
  assert.equal(result.ok, true, JSON.stringify(result.divergence));
  assert.equal(result.matched, 3);
});

test('the clock is the tape\'s, and it moves with the messages', async () => {
  const seen = [];
  const a = render(1);
  const t = tape([
    expected(10, a),
    { t: 2500, in: { type: 'command', cmd: 'x' } },
    expected(2501, render(2)),
    { t: 2600, end: 'exit' },
  ]);
  await replay(
    program({
      onInit: (emit) => {
        seen.push(Date.now());
        emit(a);
      },
      onMessage: (m, emit) => {
        seen.push(Date.now());
        emit(render(2));
      },
    }),
    session(t)
  );
  assert.equal(seen[0], START);
  assert.equal(seen[1], START + 2500);
});

test('Time.every is driven rather than waited for', async () => {
  // A tick a minute into the recording fires at once, because the clock is not
  // the wall's. The render it produces is on the tape with no message under it.
  const a = render(1);
  const tick = render(2);
  // With the reading the tick takes on its way: `Time.every` builds its
  // `Posix` from `Time.now`, so a tick on a tape always has one in front of
  // it, and that is what tells a replay this render is a timer going off
  // rather than the second half of an update.
  const t = tape([
    expected(10, a),
    { t: 60009, now: START + 60009 },
    expected(60010, tick),
    { t: 60020, end: 'exit' },
  ]);
  const started = Date.now();
  const result = await replay(
    program({
      onInit: (emit) => {
        emit(a);
        setInterval(() => emit(tick), 60000);
      },
      onMessage: () => {},
    }),
    session(t),
    { timeoutMs: 2000 }
  );
  assert.equal(result.ok, true, JSON.stringify(result.divergence));
  assert.ok(Date.now() - started < 2000, 'it should not have waited a minute');
});

test('recorded random bytes are handed back, and withheld ones are named', async () => {
  const bytes = Buffer.from([1, 2, 3, 4, 5, 6, 7, 8]);
  const drawn = [];
  const draw = () => {
    const array = new Uint8Array(8);
    require('crypto').getRandomValues(array);
    drawn.push(Buffer.from(array).toString('base64'));
  };
  const a = render(1);

  const kept = tape([
    { t: 5, rng: 'getRandomValues', n: 8, value: bytes.toString('base64') },
    expected(10, a),
    { t: 20, end: 'exit' },
  ]);
  await replay(program({ onInit: (emit) => { draw(); emit(a); } }), session(kept));
  assert.equal(drawn[0], bytes.toString('base64'));

  const withheld = tape([
    { t: 5, rng: 'getRandomValues', n: 8, sha: 'abcd' },
    expected(10, a),
    { t: 20, end: 'exit' },
  ]);
  const result = await replay(
    program({ onInit: (emit) => { draw(); emit(a); } }),
    session(withheld)
  );
  // Zeroes, not fresh randomness: a replay that could not reproduce a draw
  // must at least fail the same way twice.
  assert.equal(drawn[1], Buffer.alloc(8).toString('base64'));
  assert.match(result.warnings.join('\n'), /withheld from this tape/);
});

test('the program is given a directory of its own, and the recorded config in it', async () => {
  let sawHome = null;
  let sawConfig = null;
  const a = render(1);
  // With `XDG_CONFIG_HOME` among the names the recording had, so the replay
  // sets one: where the recording had none, the file goes under the scratch
  // `HOME` instead, which is where the program's own default rule looks.
  const t = tape([expected(10, a), { t: 20, end: 'exit' }], {
    envNames: ['HOME', 'XDG_CONFIG_HOME'],
    extra: { config: { path: '/home/somebody/.config/p/config.toml', contents: 'theme = "gren"\n' } },
  });
  const realHome = process.env.HOME;
  await replay(
    program({
      onInit: (emit) => {
        sawHome = process.env.HOME;
        sawConfig = fs.readFileSync(path.join(process.env.XDG_CONFIG_HOME, 'p', 'config.toml'), 'utf8');
        emit(a);
      },
    }),
    session(t)
  );
  assert.notEqual(sawHome, realHome);
  assert.equal(sawConfig, 'theme = "gren"\n');
  // And it is gone afterwards, along with everything else it changed.
  assert.equal(process.env.HOME, realHome);
  assert.ok(!fs.existsSync(sawHome));
});

test('in place, it says out loud that the program writes for real', async () => {
  const a = render(1);
  const t = tape([expected(10, a), { t: 20, end: 'exit' }]);
  const result = await replay(program({ onInit: (emit) => emit(a) }), session(t), {
    inPlace: true,
  });
  assert.match(result.warnings.join('\n'), /writes for real/);
});

test('everything it changed about the process is changed back', async () => {
  const realNow = Date.now;
  const realInterval = global.setInterval;
  const realArgv = process.argv;
  const realCwd = process.cwd();
  const realTZ = process.env.TZ;
  const a = render(1);
  await replay(
    program({ onInit: (emit) => emit(a) }),
    session(tape([expected(10, a), { t: 20, end: 'exit' }]))
  );
  assert.equal(Date.now, realNow);
  assert.equal(global.setInterval, realInterval);
  assert.equal(process.argv, realArgv);
  assert.equal(process.cwd(), realCwd);
  assert.equal(process.env.TZ, realTZ);
});

test('the zone is the recording\'s, since two of predc\'s tools draw from it', async () => {
  let zone = null;
  const a = render(1);
  await replay(
    program({
      onInit: (emit) => {
        zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        emit(a);
      },
    }),
    session(tape([expected(10, a), { t: 20, end: 'exit' }]))
  );
  assert.equal(zone, 'Asia/Seoul');
});

test('argv is put back, because it decides whether there is a program to run', async () => {
  let argv = null;
  const a = render(1);
  await replay(
    program({
      onInit: (emit) => {
        argv = process.argv.slice(1);
        emit(a);
      },
    }),
    session(tape([expected(10, a), { t: 20, end: 'exit' }], {
      program: { name: 'p', version: '1', argv: ['/x/p.js', 'hex', 'dump.bin'], cwd: process.cwd(), flags: {} },
    }))
  );
  assert.deepEqual(argv, ['/x/p.js', 'hex', 'dump.bin']);
});

test('a protocol older than this build is a warning before it is a divergence', async () => {
  const a = render(1);
  const result = await replay(
    program({ onInit: (emit) => emit(a) }),
    session(tape([expected(10, a), { t: 20, end: 'exit' }], { protocol: PROTOCOL - 1 }))
  );
  assert.match(result.warnings.join('\n'), /two different programs/);
});

test('a program with no tuiIn is refused rather than misreported', async () => {
  const bare = { Gren: { Main: { init: () => ({ ports: {} }) } } };
  await assert.rejects(
    () => replay(bare, session(tape([{ t: 10, end: 'exit' }]))),
    /not a gren-tvision program/
  );
});

test('a render that repeats the screen is walked past, on either side', async () => {
  // `predc random` diverges on whether the terminal's resize arrives before or
  // after the Crypto task comes back: one order redraws the old page and then
  // the new, the other redraws the new one twice. Both are two screens, and
  // the differ patches nothing for the repeat.
  const a = render(1);
  const b = render(2);

  // The tape has one where the program makes two.
  const extraFromProgram = await replay(
    program({
      onInit: (emit) => emit(a),
      onMessage: (m, emit) => {
        emit(a);
        emit(b);
      },
    }),
    session(tape([
      expected(10, a),
      { t: 20, in: { type: 'resized', cols: 80, rows: 23 } },
      expected(30, b),
      { t: 40, end: 'exit' },
    ]))
  );
  assert.equal(extraFromProgram.ok, true, JSON.stringify(extraFromProgram.divergence));

  // And the tape has two where the program makes one.
  const extraOnTape = await replay(
    program({ onInit: (emit) => emit(a), onMessage: (m, emit) => emit(b) }),
    session(tape([
      expected(10, a),
      { t: 20, in: { type: 'resized', cols: 80, rows: 23 } },
      expected(29, a),
      expected(30, b),
      { t: 40, end: 'exit' },
    ]))
  );
  assert.equal(extraOnTape.ok, true, JSON.stringify(extraOnTape.divergence));
  assert.match(extraOnTape.warnings.join('\n'), /repeated the screen already drawn/);
});

test('the second render of one update is not mistaken for a tick', async () => {
  // A tick reads the clock on its way; a second render from the same message
  // does not. Nothing else tells them apart -- `demo` produces its second
  // render three milliseconds later and `predc time` produces a tick eight
  // milliseconds after a resize, so no threshold sorts both.
  const a = render(1);
  const b = render(2);
  let ticks = 0;
  const result = await replay(
    program({
      onInit: (emit) => emit(a),
      onMessage: (m, emit) => {
        setInterval(() => {
          ticks += 1;
          emit(render(99));
        }, 1000);
        // The second render, a turn later and with no reading in front of it.
        setTimeout(() => emit(b), 0);
      },
    }),
    session(tape([
      expected(10, a),
      { t: 20, in: { type: 'command', cmd: 'x' } },
      expected(23, b),
      { t: 30, end: 'exit' },
    ]))
  );
  assert.equal(result.ok, true, JSON.stringify(result.divergence));
  assert.equal(ticks, 0, 'no timer should have been fired');
});

test('a message can go in one step early when what came out is exactly right', async () => {
  // A Cmd resolving through a Task comes out after the render beside it, and
  // the terminal's next message lands in between: the tape has an inbound
  // message between two things one update sent out, and a driver that waits
  // for the second before sending waits for a message that is waiting for it.
  const a = render(1);
  const b = render(2);
  const result = await replay(
    program({
      onInit: (emit) => emit(a),
      onMessage: (m, emit) => {
        if (m.type === 'command') {
          emit({ type: 'focus', id: 'w' });
          emit(b);
        }
      },
    }),
    session(tape([
      expected(10, a),
      { t: 20, in: { type: 'command', cmd: 'x' } },
      { t: 21, out: 'focus', id: 'w' },
      { t: 22, in: { type: 'focus', id: 'w', index: 0, text: 'x' } },
      expected(23, b),
      { t: 30, end: 'exit' },
    ]))
  );
  assert.equal(result.ok, true, JSON.stringify(result.divergence));
});

test('a tick on the tape is fired where the tape has it, and not inferred', async () => {
  // The clock reading a tick takes is a signature and not a fact -- a reading
  // between a message going in and the render it produced belongs to that
  // update. A tape written by a recorder that watches `setInterval` says which
  // is which, and the driver fires the timer at that line rather than working
  // out where one must have gone off.
  const a = render(1);
  const b = render(2);
  const tock = render(3);
  let fired = 0;
  const result = await replay(
    program({
      onInit: (emit) => {
        // Subscribed before the first render goes out, which is the order a
        // Gren program has: emitting first would drive the whole tape from
        // inside this call, reaching the tick before the timer exists.
        setInterval(() => {
          fired += 1;
          emit(tock);
        }, 1000);
        emit(a);
      },
      onMessage: (m, emit) => {
        // An update that reads the clock and then renders: the reading in
        // front of *this* render must not be taken for a timer.
        Date.now();
        emit(b);
      },
    }),
    session(tape([
      expected(10, a),
      { t: 20, in: { type: 'command', cmd: 'x' } },
      { t: 21, now: START + 21 },
      expected(22, b),
      { t: 1010, tick: 1000 },
      { t: 1011, now: START + 1011 },
      expected(1012, tock),
      { t: 1020, end: 'exit' },
    ]))
  );
  assert.equal(result.ok, true, JSON.stringify(result.divergence));
  assert.equal(fired, 1, 'exactly the one tick the tape has');
});
