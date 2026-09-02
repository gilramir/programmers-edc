'use strict';

// The time converter's half of predc that cannot be written in Gren.
//
// A time zone is not a number. `America/Chicago` was -06:00 until the second
// Sunday in March and is -05:00 now, was -05:00 all year round in 1974, and
// will be whatever the United States Congress decides next; the answer lives in
// the IANA database, which ships inside every JavaScript runtime as `Intl` and
// nowhere inside Gren. So this file is where the calendar arithmetic happens,
// and the Gren side does none of it: no leap years, no month lengths, no
// daylight saving, no tzdata.
//
// Three things it answers, over the `intlOut`/`intlIn` port pair:
//
//   {type:"zoneList"}                        -> {type:"zones", zones:[...]}
//   {type:"atInstant", posix, zones}         -> {type:"rows", ...}
//   {type:"fromParts", zone, y,mo,d,h,mi,s, zones}
//                                            -> {type:"rows", ...}
//
// **Every reply carries the whole window**, which is the one decision here
// worth arguing about. A per-zone request would be the obvious shape and it is
// the wrong one twice over: it is N round trips per keystroke instead of one,
// and it makes the Gren side hold a half-updated table while the answers
// straggle in. One request, one reply, one coherent screen.
//
// The seconds ride along untouched. predc's fields are minute-resolution
// because that is what anybody typing a time wants, but the instant is a POSIX
// timestamp and throwing its seconds away would make the box on the screen
// disagree with the number the user pasted into it.

// `Intl.DateTimeFormat` is expensive to build and free to reuse, and a window
// with five zones rebuilds the same handful on every keystroke.
const wallCache = new Map();
const nameCache = new Map();

function wallFormat(zone) {
  let f = wallCache.get(zone);
  if (!f) {
    f = new Intl.DateTimeFormat('en-US', {
      timeZone: zone,
      // Not `hour12: false`, which gives midnight as hour 24 in some runtimes.
      // `h23` is the cycle that means what it says.
      hourCycle: 'h23',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
    wallCache.set(zone, f);
  }
  return f;
}

function nameFormat(zone) {
  let f = nameCache.get(zone);
  if (!f) {
    f = new Intl.DateTimeFormat('en-US', { timeZone: zone, timeZoneName: 'short' });
    nameCache.set(zone, f);
  }
  return f;
}

// The wall clock in `zone` at an instant, as numbers.
function wallAt(zone, ms) {
  const out = {};
  for (const { type, value } of wallFormat(zone).formatToParts(ms)) {
    if (type !== 'literal') out[type] = value;
  }
  return {
    y: Number(out.year),
    mo: Number(out.month),
    d: Number(out.day),
    h: Number(out.hour),
    mi: Number(out.minute),
    s: Number(out.second),
  };
}

// `Date.UTC` reads a year of 0..99 as 1900..1999, which is a bug we would
// inherit for free the first time somebody typed a year of 70 meaning 70.
function utcMs(p) {
  let ms = Date.UTC(p.y, p.mo - 1, p.d, p.h, p.mi, p.s);
  if (p.y >= 0 && p.y <= 99) {
    const d = new Date(ms);
    d.setUTCFullYear(p.y);
    ms = d.getTime();
  }
  return ms;
}

// How far ahead of UTC `zone` is at an instant, in minutes. Read off the wall
// clock rather than asked for: `Intl` will format a zone's local time but has
// no API that hands back its offset as a number.
function offsetMinutes(zone, ms) {
  return Math.round((utcMs(wallAt(zone, ms)) - ms) / 60000);
}

// The abbreviation, when there is one.
//
// CLDR only carries real abbreviations for North American zones in `en-US`:
// `America/Chicago` is `CDT`, and `Asia/Seoul` is `GMT+9`, which is the offset
// column spelled differently and worth no width at all. So a name that is
// merely `GMT±h` is reported as no name, and the row shows its offset alone.
// `CDT` is kept because it says something the offset does not -- that daylight
// saving is in effect right now.
function abbrev(zone, ms) {
  const part = nameFormat(zone)
    .formatToParts(ms)
    .find((p) => p.type === 'timeZoneName');
  const text = part ? part.value : '';
  return /^(GMT|UTC)([+-]|$)/.test(text) ? '' : text;
}

// A wall clock in a zone back to the instant it names.
//
// Guess that the zone is at UTC, look up what it actually was near that guess,
// subtract. That lands inside the right day but can land on the wrong side of
// a daylight-saving change, so look the offset up again at the corrected
// instant and subtract that too. Both answers are then kept, because near a
// transition they are different instants and neither one is obviously the
// right one.
//
// **Twice a year the wall clock is not a function.** In Chicago, 02:30 on the
// second Sunday in March never happens and 01:30 on the first Sunday in
// November happens twice, and a converter that does not decide what it means
// by those is a converter that is quietly wrong two days a year.
//
//   - Two candidates read back as the time asked for: the clock went
//     backwards and this instant is ambiguous. Take the **earlier**, which is
//     the first time the clock read it and is what `fold = 0` means
//     everywhere else that has had to name this.
//   - Neither reads back: the clock jumped and this time does not exist. Take
//     the **later**, so that a missing 02:30 becomes 03:30 and not 01:30 --
//     forward is the direction the clock moved, and an answer earlier than
//     what was typed is the surprising one. `adjusted` says so out loud, and
//     the caller puts it on the message line.
function resolve(zone, parts) {
  const target = utcMs(parts);
  const first = target - offsetMinutes(zone, target) * 60000;
  const second = target - offsetMinutes(zone, first) * 60000;

  const matches = (ms) => {
    const got = wallAt(zone, ms);
    return (
      got.y === parts.y &&
      got.mo === parts.mo &&
      got.d === parts.d &&
      got.h === parts.h &&
      got.mi === parts.mi
    );
  };

  const exact = [first, second].filter(matches);
  return exact.length > 0
    ? { ms: Math.min(...exact), adjusted: false }
    : { ms: Math.max(first, second), adjusted: true };
}

// One row per zone, all at the same instant. `UTC` is always the last one and
// is not in the caller's list: `Intl.supportedValuesOf` does not offer it --
// there are no single-segment names in the 418 it knows -- but every
// `DateTimeFormat` accepts it, and predc shows it whether or not anybody asked.
function rowsAt(zones, ms) {
  return zones.map((zone) => {
    const w = wallAt(zone, ms);
    return {
      zone,
      y: w.y,
      mo: w.mo,
      d: w.d,
      h: w.h,
      mi: w.mi,
      s: w.s,
      offset: offsetMinutes(zone, ms),
      abbrev: abbrev(zone, ms),
    };
  });
}

// A zone name from a config file written by hand, or by a predc running on a
// machine with a newer tzdata than this one. Asking `Intl` is the only way to
// know, and it throws rather than answering.
function known(zone) {
  try {
    wallFormat(zone).format(0);
    return true;
  } catch (_) {
    return false;
  }
}

// What a `Date` can be: ±8.64e15 milliseconds either side of 1970, which is
// about ±273,790 years. Past it every `Intl` call throws a RangeError, and a
// throw inside a port subscription takes the whole program down with it -- so
// a person holding a digit key down closed predc, which is how this was found.
// It is checked rather than caught, so that the reply can say which of the two
// things went wrong.
const REACH = 8.64e12;

function outOfReach(posix) {
  return !Number.isFinite(posix) || Math.abs(posix) > REACH;
}

function nothing(posix, problem) {
  return { type: 'rows', posix, rows: [], adjusted: false, unknown: [], problem };
}

function answer(message) {
  switch (message.type) {
    case 'zoneList':
      return { type: 'zones', zones: Intl.supportedValuesOf('timeZone') };

    case 'atInstant': {
      if (outOfReach(message.posix)) return nothing(message.posix, 'range');
      const zones = message.zones.filter(known);
      return {
        type: 'rows',
        posix: message.posix,
        rows: rowsAt(zones, message.posix * 1000),
        adjusted: false,
        unknown: message.zones.filter((z) => !known(z)),
        problem: '',
      };
    }

    case 'fromParts': {
      if (!known(message.zone)) {
        // The row being typed in is a zone this runtime has never heard of.
        // Nothing can be computed from it, and the caller is told so rather
        // than handed a plausible wrong instant.
        return {
          type: 'rows',
          posix: message.posix,
          rows: [],
          adjusted: false,
          unknown: [message.zone],
          problem: '',
        };
      }
      const { ms, adjusted } = resolve(message.zone, message);
      if (outOfReach(Math.floor(ms / 1000))) return nothing(message.posix, 'range');
      const zones = message.zones.filter(known);
      return {
        type: 'rows',
        posix: Math.floor(ms / 1000),
        rows: rowsAt(zones, ms),
        adjusted,
        unknown: message.zones.filter((z) => !known(z)),
        problem: '',
        // Echoed back so the reply describes itself. Several requests can be
        // in flight at once and a caller that had to remember what it asked
        // would sometimes match the wrong one up.
        asked: {
          zone: message.zone,
          y: message.y,
          mo: message.mo,
          d: message.d,
          h: message.h,
          mi: message.mi,
        },
      };
    }

    default:
      return { type: 'unknown', about: String(message.type) };
  }
}

/**
 * Subscribe to a compiled Gren program's time-zone port pair.
 *
 * `run()` in gren-tvision-runtime hands back the app precisely so that a
 * program with ports of its own can do this; the runtime claims `tuiOut` and
 * `tuiIn` and nothing else.
 */
function attach(app, options = {}) {
  const outPort = options.outPort || 'intlOut';
  const inPort = options.inPort || 'intlIn';
  if (!app.ports || !app.ports[outPort] || !app.ports[inPort]) {
    throw new Error(`predc: the program must declare ports named ${outPort} and ${inPort}.`);
  }
  app.ports[outPort].subscribe((message) => {
    // A belt to `outOfReach`'s braces. Nothing here should throw any more, but
    // an exception out of a port subscription kills the process with the
    // terminal still in its alternate screen -- which is the worst possible
    // way for a converter to disagree with you about a date.
    let reply;
    try {
      reply = answer(message);
    } catch (err) {
      reply = {
        type: 'rows',
        posix: message.posix || 0,
        rows: [],
        adjusted: false,
        unknown: [],
        problem: String((err && err.message) || err),
      };
    }
    app.ports[inPort].send(reply);
  });
}

module.exports = { attach, answer, rowsAt, resolve, offsetMinutes, wallAt, utcMs, abbrev };
