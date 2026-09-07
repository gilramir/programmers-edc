// The time converter's JavaScript half, checked without a terminal.
//
// These are here rather than in `drive_time.py` because they are about the
// IANA database and not about the user interface, and a pty test is the wrong
// instrument for "what was Nepal's offset in 1970". Each one is a rule that a
// fixed-offset table would get wrong, which is the whole reason predc talks to
// `Intl` instead of carrying a table.
//
// Run by `drive_timezones.py`, which is how `tools/run_tests.py` finds them.

const tz = require('../bin/timezones.js');
let fails = 0;
function eq(what, got, want) {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g !== w) { console.log("FAIL " + what + "\n  got  " + g + "\n  want " + w); fails++; }
  else console.log("ok   " + what + "  " + g);
}

// A known instant: 2026-09-01T19:32:00Z
const r = tz.answer({type:"atInstant", posix: 1788291120, zones:["America/Chicago","Asia/Seoul","Asia/Kolkata","UTC"]});
eq("chicago row", r.rows[0], {zone:"America/Chicago",y:2026,mo:9,d:1,h:14,mi:32,s:0,offset:-300,abbrev:"CDT"});
eq("seoul row",   r.rows[1], {zone:"Asia/Seoul",y:2026,mo:9,d:2,h:4,mi:32,s:0,offset:540,abbrev:""});
eq("kolkata row", r.rows[2], {zone:"Asia/Kolkata",y:2026,mo:9,d:2,h:1,mi:2,s:0,offset:330,abbrev:""});
eq("utc row (its abbrev is suppressed: it restates the label)",     r.rows[3], {zone:"UTC",y:2026,mo:9,d:1,h:19,mi:32,s:0,offset:0,abbrev:""});

// Round trip: those wall parts back to the same instant.
const back = tz.answer({type:"fromParts", zone:"Asia/Seoul", y:2026,mo:9,d:2,h:4,mi:32,s:0, zones:["UTC"]});
eq("round trip posix", back.posix, 1788291120);
eq("round trip exact", back.adjusted, false);

// Spring forward: 2026-03-08 02:30 does not exist in Chicago.
const gap = tz.answer({type:"fromParts", zone:"America/Chicago", y:2026,mo:3,d:8,h:2,mi:30,s:0, zones:["America/Chicago"]});
eq("gap adjusted", gap.adjusted, true);
eq("gap pushes forward", [gap.rows[0].h, gap.rows[0].mi], [3,30]);

// Fall back: 2026-11-01 01:30 happens twice in Chicago; must pick one, not fail.
const dup = tz.answer({type:"fromParts", zone:"America/Chicago", y:2026,mo:11,d:1,h:1,mi:30,s:0, zones:["America/Chicago"]});
eq("ambiguous not adjusted", dup.adjusted, false);
eq("ambiguous takes the first, CDT", dup.rows[0].offset, -300);

// Seconds survive an edit of the minute fields.
const secs = tz.answer({type:"fromParts", zone:"UTC", y:2026,mo:9,d:1,h:19,mi:32,s:37, zones:["UTC"]});
eq("seconds kept", secs.posix, 1788291157);

// Half-hour and 45-minute offsets.
const np = tz.answer({type:"atInstant", posix: 0, zones:["Asia/Kathmandu","Pacific/Chatham"]});
const np26 = tz.answer({type:"atInstant", posix: 1788291120, zones:["Asia/Kathmandu"]});
eq("kathmandu is +5:45 now", np26.rows[0].offset, 345);
eq("kathmandu was +5:30 in 1970", np.rows[0].offset, 330);
eq("chatham", np.rows[1].offset, 765);

// Year 70 means 70, not 1970. `Date.UTC` reads a year of 0..99 as 1900..1999,
// which predc would have inherited the first time somebody typed a two-digit
// year meaning a two-digit year.
const early = tz.utcMs({y: 70, mo: 1, d: 1, h: 0, mi: 0, s: 0});
eq("year 70 is the first century", tz.wallAt("UTC", early).y, 70);
eq("and not 1970", early === 0, false);

// Anything past what a `Date` can hold is a sentence rather than a thrown
// RangeError, which used to take the whole program down with the terminal
// still in its alternate screen.
eq("an unreachable instant is reported",
   tz.answer({type:"atInstant", posix: 99999999999999999999, zones:["UTC"]}).problem,
   "range");
eq("and it costs no rows",
   tz.answer({type:"atInstant", posix: 1e18, zones:["UTC"]}).rows.length, 0);

// An abbreviation that merely restates the offset is no abbreviation. CLDR
// only carries real ones for North America in en-US.
eq("Chicago has a name", tz.abbrev("America/Chicago", Date.UTC(2026,8,1)), "CDT");
eq("and in winter a different one", tz.abbrev("America/Chicago", Date.UTC(2026,0,1)), "CST");
eq("Seoul has none worth a column", tz.abbrev("Asia/Seoul", Date.UTC(2026,8,1)), "");

// A pre-1970 instant.
const old = tz.answer({type:"atInstant", posix: -86400, zones:["UTC"]});
eq("1969", [old.rows[0].y, old.rows[0].mo, old.rows[0].d], [1969,12,31]);

// A zone this runtime does not know.
const bad = tz.answer({type:"atInstant", posix: 0, zones:["Mars/Olympus_Mons","UTC"]});
eq("unknown reported", bad.unknown, ["Mars/Olympus_Mons"]);
eq("unknown dropped", bad.rows.length, 1);

// The zone list.
const zs = tz.answer({type:"zoneList"});
eq("zone list size", zs.zones.length > 400, true);

// Three-segment name.
const arg = tz.answer({type:"atInstant", posix: 1788291120, zones:["America/Argentina/Ushuaia"]});
eq("ushuaia", arg.rows[0].offset, -180);

// The caller's own marker, carried back untouched.
//
// This side does not look at `restore` and that is the point of it: several
// requests can be in flight at once -- a clock tick asks for the same rows
// once a second -- and the converter has to tell the reply to the zone
// picker's request from the reply to a tick's. It used to keep a flag and
// clear it on "the answer", where the answer was whichever came back first,
// so whether the caret went home after choosing a zone depended on how many
// seconds had gone by. A reply that describes itself needs no such
// bookkeeping.
const marked = tz.answer({type:"atInstant", posix: 1788291120, zones:["UTC"], restore: true});
eq("the marker comes back on the reply", marked.restore, true);
eq("and the answer is the same answer", marked.rows[0].offset, 0);
const plain = tz.answer({type:"atInstant", posix: 1788291120, zones:["UTC"]});
eq("a request without it gets a reply without it", plain.restore, undefined);
const markedParts = tz.answer({type:"fromParts", zone:"UTC", y:2026,mo:9,d:1,h:19,mi:32,s:0, zones:["UTC"], restore: true});
eq("and it is the request's, not one kind of request's", markedParts.restore, true);

console.log(fails ? "\n" + fails + " FAILED" : "\nall checks passed");
process.exit(fails ? 1 : 0);
