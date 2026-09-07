'use strict';

// Reading a tape.
//
// `record.js` writes one; this reads it back. They are separate files because
// they are separate programs: the writer runs on the machine where the bug
// happened, inside the application, and must never be the reason the
// application stopped. The reader runs on yours, afterwards, and is allowed to
// be as slow and as opinionated as it likes.
//
// What this is *for* is the awkward truth about a tape: it is an input, not an
// account. A replayer will eventually feed it back and tell you whether the
// bug reproduces, but the first question anybody asks of a file somebody
// mailed them is "what did they do?", and 339 lines of JSON does not answer
// that. Nearly all of those lines are one gesture -- a window dragged across
// the screen is fifty `windowResized` messages -- so the report collapses runs
// and shows what each one changed.
//
// **What each one changed is the column that matters.** A render is recorded
// as a hash, and the hash is the only thing here that says whether the program
// did anything: an input followed by an identical hash is an input the model
// looked at and ignored. That is normally correct and occasionally the whole
// bug, and either way it is invisible in the raw file.

const { TAPE, digest } = require('./record');
const { PROTOCOL } = require('./tui');

// A render that arrives this long after anything else was not caused by it.
// The ones that follow an input follow it within a few milliseconds; the ones
// that arrive on their own are `Time.every` ticks, which is the one thing that
// makes a render appear with no message under it. The number is a threshold
// rather than a fact, and it is only used to decide how a line is *labelled*.
const UNPROMPTED_MS = 200;

// What each tape format added, so that reading an older one says which piece
// of the input is missing rather than only that a number differs. The entry is
// written when the number is bumped, by whoever bumps it, because a year later
// nobody can reconstruct it from the diff.
const ADDED_IN = {
  2: "the random values the program drew, and the machine's time zone",
  3: "the terminal's colour depth and the flags init was given",
};

/**
 * Parse a tape.
 *
 * Returns one entry per *session*, because a tape can hold more than one: the
 * recorder opens the file with 'a', on the grounds that two runs recording to
 * the same name is a mistake worth surviving rather than a file worth
 * destroying. Every line carrying a `tape` field starts a new session.
 *
 * Nothing here throws. A tape is a file from somebody else's disk that may
 * have been truncated by a full disk, mangled by a mail client, or cut short
 * by the crash it was recording, and a reader that refuses the whole file over
 * one bad line is a reader that fails exactly when it is needed.
 */
function read(text) {
  const sessions = [];
  const problems = [];
  let current = null;

  String(text)
    .split('\n')
    .forEach((line, i) => {
      const at = i + 1;
      if (!line.trim()) return;
      let value;
      try {
        value = JSON.parse(line);
      } catch (err) {
        problems.push(`line ${at} is not JSON (${err.message})`);
        return;
      }
      if (value && value.tape !== undefined) {
        current = { header: value, at, events: [] };
        sessions.push(current);
        return;
      }
      if (!current) {
        problems.push(`line ${at} comes before any header`);
        return;
      }
      current.events.push({ ...value, at });
    });

  return { sessions, problems };
}

/** `[x0,y0,x1,y1]` the way a person reads it. */
function rect(r) {
  return Array.isArray(r) ? `[${r.join(',')}]` : String(r);
}

/** Eight characters of a hash is plenty to tell two renders apart by eye. */
function short(hash) {
  return String(hash || '').slice(0, 8);
}

function seconds(ms) {
  return `${(ms / 1000).toFixed(1)}s`;
}

/**
 * The half of an inbound message that says which run of them it belongs to.
 *
 * Two consecutive messages collapse into one line when this is equal: a drag
 * is fifty `windowResized`s at the same id, and a wheel is twenty `scroll`s.
 * A `command` collapses on its own name, so three presses of the same menu
 * entry read as one line saying three, and two *different* commands never
 * merge.
 */
function runKey(message, port) {
  const on = port ? `${port}:` : '';
  switch (message.type) {
    case 'windowResized':
      return `${on}windowResized:${message.id}`;
    case 'scroll':
      return `${on}scroll:${message.id}`;
    case 'command':
      return `${on}command:${message.cmd}`;
    default:
      return null;
  }
}

/** As much of a value as belongs on one line. */
function clip(text, full) {
  return full || text.length <= 72 ? text : `${text.slice(0, 71)}…`;
}


/** One line of the timeline, for a run of one or more messages. */
function describeRun(run, full) {
  const first = run[0];
  const last = run[run.length - 1];
  const times = run.length > 1 ? ` ×${run.length}` : '';

  switch (first.type) {
    case 'windowResized': {
      const [ax, ay, aw, ah] = first.rect || [];
      const [bx, by, bw, bh] = last.rect || [];
      // Moved or resized: a window dragged by its frame keeps its size, and
      // one dragged by its corner does not. They are different gestures and
      // reading fifty lines to work out which one happened is the thing this
      // report exists to save.
      const verb = aw - ax === bw - bx && ah - ay === bh - by ? 'moved' : 'resized';
      return run.length > 1
        ? `${first.id} ${verb}${times}  ${rect(first.rect)} → ${rect(last.rect)}`
        : `${first.id} ${verb} to ${rect(first.rect)}`;
    }
    case 'scroll': {
      if (run.length === 1) return `${first.id} scrolled to ${first.value}`;
      // Where it went, and not only where it stopped: a wheel rolled down and
      // back up again ends where it started, and "3 → 3" is the one shape that
      // reads as nothing having happened when quite a lot did.
      const values = run.map((m) => m.value).filter((v) => typeof v === 'number');
      const far = Math.max(...values);
      const near = Math.min(...values);
      const ends = [first.value, last.value];
      const excursion =
        far > Math.max(...ends) ? `, out to ${far}` : near < Math.min(...ends) ? `, back to ${near}` : '';
      return `${first.id} scrolled ${first.value} → ${last.value}${excursion}${times}`;
    }
    case 'command':
      return `command ${first.cmd}${times}`;
    case 'changed':
      return `${first.id} changed to ${JSON.stringify(first.value)}`;
    case 'select':
      return `${first.id} selected ${first.index}${first.text ? ` (${first.text})` : ''}`;
    case 'focus':
      return `${first.id} focused ${first.index}${first.text ? ` (${first.text})` : ''}`;
    case 'key':
      return `${first.id} key ${JSON.stringify(first.key)}`;
    case 'click':
      return `${first.id} ${first.right ? 'right-' : ''}click${first.doubled ? ' (double)' : ''} at ${first.x},${first.y}`;
    case 'drag':
      return `${first.id} drag to ${first.x},${first.y}${first.done ? ' (done)' : ''}`;
    case 'clipboardText':
    case 'editorText': {
      const what = first.type === 'editorText' ? `editor text for ${first.id}` : 'clipboard text';
      const where = first.fromSystem === false ? ' (from predc\'s own store)' : '';
      if (first.withheld) {
        return `${what}${where}: ${first.withheld.chars} characters, withheld (sha ${short(first.withheld.sha)})`;
      }
      return `${what}${where}: ${String(first.text || '').length} characters, kept`;
    }
    case 'resized':
      return `terminal ${first.cols}x${first.rows}`;
    case 'windowClosed':
      return `${first.id} closed`;
    case 'dialogClosed':
      return `dialog ${first.id} closed with ${first.cmd}`;
    default: {
      // Everything else, including a message type this reader predates. The
      // fields are printed rather than dropped, because a tape read by an
      // older reader than the recorder that wrote it is the ordinary case
      // once anybody else is running the program.
      const rest = Object.keys(first)
        .filter((k) => k !== 'type' && k !== 'at')
        .map((k) => `${k}=${JSON.stringify(first[k])}`)
        .join(' ');
      // Clipped, because an unknown message is printed whole and predc's time
      // converter answers with a day's worth of zones in one of them. `--all`
      // is where the whole thing belongs; a timeline is a page you scan.
      return `${first.type}${rest ? ` ${clip(rest, full)}` : ''}${times}`;
    }
  }
}

/**
 * Group the events into steps, and the steps into runs.
 *
 * A step is one inbound message and everything that came out because of it.
 * The renders in a step are its effect; anything else that came out -- a
 * `dialog`, a `readClipboard` -- is a request the program made, which will be
 * answered by an inbound message further down and gets a line of its own.
 */
function steps(events) {
  const out = [];
  let step = null;

  for (const ev of events) {
    if (ev.in) {
      step = { t: ev.t, at: ev.at, in: ev.in, port: ev.port, outs: [], last: ev.t };
      out.push(step);
      continue;
    }
    if (ev.out) {
      // A render nobody asked for is a `Time.every` tick, and it belongs to
      // itself rather than to whatever happened a second earlier.
      if (!step || ev.t - step.last > UNPROMPTED_MS) {
        step = { t: ev.t, at: ev.at, in: null, outs: [], last: ev.t };
        out.push(step);
      }
      step.outs.push(ev);
      step.last = ev.t;
      continue;
    }
    // A note, a crash, an end, a truncation: its own line, and it ends
    // whatever step was collecting, since nothing after it was caused by it.
    out.push({ t: ev.t, at: ev.at, other: ev, outs: [] });
    step = null;
  }

  return out;
}

/**
 * What a tape says, as a structure. `format` turns it into a page.
 *
 * @param session  one entry from `read().sessions`
 * @param opts.collapse  merge runs of the same gesture (default true)
 */
function analyse(session, opts = {}) {
  const collapse = opts.collapse !== false;
  const header = session.header || {};
  const events = session.events || [];

  const compatibility = [];
  if (header.tape !== TAPE) {
    compatibility.push(`tape format ${header.tape}, this build writes ${TAPE}`);
    for (let v = (header.tape || 0) + 1; v <= TAPE; v += 1) {
      if (ADDED_IN[v]) compatibility.push(`  format ${v} added ${ADDED_IN[v]}, so this tape has neither`);
    }
  }
  if (header.protocol !== undefined && header.protocol !== PROTOCOL) {
    compatibility.push(
      `port protocol ${header.protocol}, this runtime speaks ${PROTOCOL} -- ` +
        'a replay against this build would be comparing two different programs'
    );
  }

  const rows = [];
  const anomalies = [];
  const windowsSeen = new Set();
  const counts = { in: 0, out: 0, render: 0, note: 0, random: 0 };
  const distinctRenders = new Set();
  const withheld = [];
  const random = { draws: 0, bytes: 0, withheld: 0 };
  const unanswered = new Map();

  // The desktop, which is what a window rectangle is measured against. The
  // header's terminal size is the guess the program starts from; the first
  // `resized` is the truth, and every one after it is a resize.
  let desktop = header.terminal
    ? { cols: header.terminal.columns, rows: header.terminal.rows }
    : null;
  let lastHash = null;
  let openWindows = [];
  let ended = null;
  let run = null;

  const flush = () => {
    if (!run) return;
    const renders = run.outs.filter((o) => o.out === 'render');
    const requests = run.outs.filter((o) => o.out !== 'render');

    let effect;
    if (!renders.length) {
      effect = 'no render';
    } else if (renders.every((r) => r.hash === run.hashBefore)) {
      // The column this report exists for: the model was handed something and
      // drew exactly what it was already drawing.
      effect = 'unchanged';
    } else {
      const gained = run.windowsAfter.filter((w) => !run.windowsBefore.includes(w));
      const lost = run.windowsBefore.filter((w) => !run.windowsAfter.includes(w));
      const marks = [...gained.map((w) => `+${w}`), ...lost.map((w) => `-${w}`)];
      effect =
        (marks.length ? `${marks.join(' ')}  ` : '') +
        short(renders[renders.length - 1].hash) +
        (renders.length > 1 ? `  (${renders.length} renders)` : '');
    }

    rows.push({
      t: run.t,
      at: run.at,
      text:
        (run.port ? `[${run.port}] ` : '') +
        (run.messages
        ? describeRun(run.messages, opts.collapse === false)
        : run.hashBefore === null
          ? 'the first render, which init produced'
          : 'a render with no message under it, so a Time.every tick'),
      effect,
      requests: requests.map(
        (r) => (r.port ? `[${r.port}] ` : '') + r.out + (r.id !== undefined ? ` ${r.id}` : '')
      ),
    });
    run = null;
  };

  for (const step of steps(events)) {
    // Captured before this step's own output is applied: "unchanged" is
    // measured against the screen as it stood when the message arrived.
    const hashBefore = lastHash;
    const windowsBefore = openWindows;

    if (step.other) {
      flush();
      const ev = step.other;
      if (ev.note) counts.note += 1;
      if (ev.rng) {
        counts.random += 1;
        random.draws += 1;
        random.bytes += ev.n || 0;
        if (ev.value === undefined) random.withheld += 1;
      }
      if (ev.end) ended = ev.end;
      if (ev.crash) anomalies.push({ at: ev.at, what: `the program crashed in ${ev.crash}: ${(ev.error && ev.error.message) || ''}` });
      if (ev.truncated) anomalies.push({ at: ev.at, what: 'the tape was truncated: the session outgrew the size limit' });
      rows.push({ t: step.t, at: step.at, text: describeOther(ev), effect: '' });
      continue;
    }

    const message = step.in;
    if (message) {
      counts.in += 1;
      if (message.withheld) withheld.push(message.withheld);
      if (message.type === 'resized') desktop = { cols: message.cols, rows: message.rows };
      if (Array.isArray(message.rect)) {
        const [x0, y0, x1, y1] = message.rect;
        if (x0 < 0 || y0 < 0) {
          anomalies.push({
            at: step.at,
            what: `${message.id} at ${rect(message.rect)}: its origin is off the top or left of the desktop`,
          });
        } else if (desktop && desktop.cols && (x1 > desktop.cols || y1 > desktop.rows)) {
          anomalies.push({
            at: step.at,
            what: `${message.id} at ${rect(message.rect)}: past the ${desktop.cols}x${desktop.rows} desktop`,
          });
        }
      }
      // A request the program made, and the answer it was given.
      // `readClipboard` is answered by `clipboardText` and `dialog` by
      // `dialogClosed`; one that never comes back is a model waiting for a
      // message that will not arrive, which is a hang rather than a wrong
      // picture, and looks like nothing at all on the raw tape.
      if (message.type === 'clipboardText') unanswered.delete('readClipboard');
      if (message.type === 'dialogClosed') unanswered.delete(`dialog ${message.id}`);
    }

    for (const o of step.outs) {
      counts.out += 1;
      if (o.out === 'render') {
        counts.render += 1;
        if (o.hash) distinctRenders.add(o.hash);
        openWindows = o.windows || [];
        openWindows.forEach((w) => windowsSeen.add(w));
        lastHash = o.hash;
      } else if (o.out === 'readClipboard') {
        unanswered.set('readClipboard', step.at);
      } else if (o.out === 'dialog') {
        unanswered.set(`dialog ${o.id}`, step.at);
      }
    }

    const key = message && collapse ? runKey(message, step.port) : null;
    if (run && key && key === run.key) {
      run.messages.push(message);
      run.outs.push(...step.outs);
      run.windowsAfter = openWindows;
      continue;
    }

    flush();
    run = {
      t: step.t,
      at: step.at,
      key,
      messages: message ? [message] : null,
      // A program with ports of its own has a second inbound stream --
      // predc's time converter answers over `intlIn` -- and folding the two
      // together would read as one conversation when it is two.
      port: step.port,
      outs: [...step.outs],
      hashBefore,
      windowsBefore,
      windowsAfter: openWindows,
    };
  }
  flush();

  for (const [what, at] of unanswered) {
    anomalies.push({ at, what: `${what} was never answered` });
  }
  if (!ended) {
    anomalies.push({
      at: null,
      what: 'no end line: the program did not leave through an exit it controls',
    });
  }

  return {
    header,
    compatibility,
    summary: {
      duration: events.length ? events[events.length - 1].t : 0,
      lines: events.length,
      counts,
      distinctRenders: distinctRenders.size,
      windows: [...windowsSeen],
      withheld,
      random,
      ended,
    },
    rows,
    anomalies,
  };
}


/** A line that is neither a message in nor a message out. */
function describeOther(ev) {
  if (ev.note !== undefined) {
    return `note ${ev.note}${ev.data === undefined ? '' : ` ${JSON.stringify(ev.data)}`}`;
  }
  if (ev.crash !== undefined) {
    return `CRASH in ${ev.crash}: ${(ev.error && ev.error.message) || ''}`;
  }
  if (ev.end !== undefined) return `ended (${ev.end})`;
  if (ev.truncated !== undefined) return `TRUNCATED at ${ev.truncated} bytes`;
  if (ev.rng !== undefined) {
    const what = `${ev.n} ${ev.n === 1 ? 'byte' : 'bytes'} from ${ev.rng}`;
    return `random: ${what}, ${ev.value === undefined ? `withheld (sha ${short(ev.sha)})` : 'kept'}`;
  }
  if (ev.unserialisable !== undefined) return `a message that would not serialise: ${ev.unserialisable}`;
  return JSON.stringify(ev);
}


/** The launcher, when there is no program name to use instead. */
function path0(argv) {
  return (argv && argv[0] ? String(argv[0]).split('/').pop() : '?');
}


/** The header, as the handful of lines somebody actually needs. */
function describeHeader(header) {
  const term = header.terminal || {};
  const rt = header.runtime || {};
  const program = header.program || {};
  const env = term.env || {};
  const lines = [
    ['recorded', `${header.at || '?'}${header.redacted === false ? ', verbatim' : ', redacted'}`],
    ['program', `${program.name || '?'} ${program.version || ''}`.trim()],
    // `program.argv` is `process.argv` without the interpreter, so its first
    // entry is the script and the rest are the words the person typed. Those
    // are what a replay has to reproduce; the path to the launcher is not.
    [
      'command',
      [program.name || path0(program.argv), ...(program.argv || []).slice(1)].join(' ') ||
        '(no arguments)',
    ],
    ['where', program.cwd || '?'],
    [
      'terminal',
      `${term.columns || '?'}x${term.rows || '?'}${term.isTTY ? '' : ' (not a terminal)'}` +
        Object.keys(env)
          .map((k) => `  ${k}=${env[k]}`)
          .join(''),
    ],
    ['runtime', `node ${rt.node || '?'}, ${rt.platform || '?'} ${rt.arch || ''} ${rt.release || ''}`.trim() + (rt.timeZone ? `, ${rt.timeZone}` : '')],
    ['format', `tape ${header.tape}, protocol ${header.protocol}`],
  ];
  if (header.extra) {
    lines.push(['extra', Object.keys(header.extra).join(', ')]);
  }
  return lines.map(([k, v]) => `  ${k.padEnd(9)} ${v}`);
}

/**
 * The report.
 *
 * Plain text with no colour in it, deliberately: a tape of any length goes
 * into a pager or a diff, and both of those are worse with escape sequences in
 * them than they are without.
 */
function format(analysis, opts = {}) {
  const out = [];
  const s = analysis.summary;

  out.push(...describeHeader(analysis.header));
  out.push(
    `  session   ${seconds(s.duration)}, ${s.lines} lines, ${s.counts.in} in, ${s.counts.render} renders (${s.distinctRenders} distinct)`
  );
  out.push(`  ended     ${s.ended || 'no end line'}`);
  if (s.windows.length) out.push(`  windows   ${s.windows.join(', ')}`);
  if (s.withheld.length) {
    const chars = s.withheld.reduce((n, w) => n + (w.chars || 0), 0);
    out.push(`  withheld  ${s.withheld.length} document(s), ${chars} characters in total`);
  }
  if (s.random && s.random.draws) {
    // The one part of the input a redacted tape deliberately does not carry.
    // Saying so here is what keeps a replay's divergence from looking like a
    // bug in the program.
    out.push(
      `  random    ${s.random.draws} draw(s), ${s.random.bytes} bytes` +
        (s.random.withheld
          ? ` -- ${s.random.withheld} withheld, so a replay cannot reproduce them`
          : ' -- kept, so a replay can reproduce them')
    );
  }

  if (analysis.compatibility.length) {
    out.push('', 'compatibility');
    analysis.compatibility.forEach((c) => out.push(`  ${c}`));
  }

  if (analysis.anomalies.length) {
    out.push('', 'anomalies');
    // One line per kind, with a count and the first place to look: twelve
    // rects with a negative origin is one defect and not twelve.
    const seen = new Map();
    for (const a of analysis.anomalies) {
      const kind = a.what.replace(/\[-?\d+(,-?\d+)*\]/g, '[...]').replace(/\d+/g, 'N');
      const had = seen.get(kind);
      if (had) had.count += 1;
      else seen.set(kind, { count: 1, first: a });
    }
    for (const { count, first } of seen.values()) {
      out.push(
        `  ${first.at ? `line ${first.at}`.padEnd(10) : ''.padEnd(10)} ${first.what}` +
          (count > 1 ? `  (${count} of these)` : '')
      );
    }
  }

  if (opts.timeline !== false) {
    out.push('', 'timeline');
    for (const row of analysis.rows) {
      const when = (opts.lines ? `${row.at}`.padStart(6) + ' ' : '') + seconds(row.t).padStart(8);
      const text = row.effect ? row.text.padEnd(52) : row.text;
      out.push(`${when}  ${text}${row.effect ? `  → ${row.effect}` : ''}`);
      (row.requests || []).forEach((r) =>
        out.push(`${''.padStart(when.length)}  ${''.padEnd(52)}  ↳ asked for ${r}`)
      );
    }
  }

  return out.join('\n');
}

module.exports = { read, analyse, format, describeHeader, TAPE, PROTOCOL, digest };
