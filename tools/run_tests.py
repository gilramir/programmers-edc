#!/usr/bin/env python3
"""Run every pty driver, several at a time.

The suites are almost entirely *asleep*. Each one types at a pty and then waits
for Turbo Vision to repaint, so a serial run of the nineteen of them takes
three and a half minutes at nine percent of one core. They are independent --
separate processes, separate ptys, separate `mkdtemp` scratch directories -- so
the wall clock is the only thing that has to be spent in order.

Drivers are discovered rather than listed: any `test/drive*.py` under
`tvision-node`, `gren-tvision` or `programmers-edc` is a suite. Adding one used
to mean remembering to register it in two lists in `devbox.json`, which is
exactly the kind of bookkeeping this repo has been bitten by before.

`programmers-edc` is on that list for a reason worth writing down, because it
is a compromise. predc is meant to be an *independent* application -- it
depends on the package the way anyone else's program would -- and an
independent application does not have this runner, or `harness.py`, which lives
in `tvision-node/test`. Nothing distributable drives a Turbo Vision program
through a pty yet. Until something is, predc borrows both from the repo it
happens to sit in, and the borrowing is the finding: shipping the binding means
answering "how does a consumer test their own TUI app".

    tools/run_tests.py             # every suite
    tools/run_tests.py --asan      # the same, with TVNODE_ASAN=1
    tools/run_tests.py -j4         # fewer at a time
    tools/run_tests.py entries dir # just these

Each suite's output is held until it finishes and then printed whole, so a
failure reads the same as it does in a serial run.
"""

import argparse
import concurrent.futures
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUITE_DIRS = [
    os.path.join(ROOT, "tvision-node"),
    os.path.join(ROOT, "gren-tvision"),
    os.path.join(ROOT, "programmers-edc"),
]

# drive_regress.py deletes every `build/asan.*` before it starts and globs for
# them afterwards, because a report is a file rather than something to fish out
# of a repainting terminal. Both halves are wrong about a concurrent run: it
# would throw away another suite's report and then read one as its own. Run it
# by itself, before the rest.
SERIAL = {"drive_regress.py"}


def suites(only):
    """[(label, cwd, script)], in a stable order."""
    found = []
    for directory in SUITE_DIRS:
        test = os.path.join(directory, "test")
        for name in sorted(os.listdir(test)):
            if not name.startswith("drive") or not name.endswith(".py"):
                continue
            label = f"{os.path.basename(directory)}/{name[len('drive'):-3].lstrip('_') or 'basic'}"
            if only and not any(o in label for o in only):
                continue
            found.append((label, directory, os.path.join("test", name)))
    return found


def run(suite, env):
    label, cwd, script = suite
    started = time.time()
    done = subprocess.run([sys.executable, script], cwd=cwd, env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return label, done.returncode, done.stdout.decode("utf-8", "replace"), time.time() - started


def report(label, code, output, seconds, failures):
    print(f"\n===== {label}  ({seconds:.1f}s)" + ("" if code == 0 else "   FAILED"))
    sys.stdout.write(output)
    if code != 0:
        failures.append(label)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("only", nargs="*", help="substrings of suite names to run")
    parser.add_argument("--asan", action="store_true", help="set TVNODE_ASAN=1")
    parser.add_argument("-j", "--jobs", type=int, default=0,
                        help="how many at a time (default: half the cores under "
                             "ASAN, which is CPU-bound, and all of them otherwise)")
    args = parser.parse_args()

    cores = os.cpu_count() or 4
    # An instrumented process is genuinely busy, so ASAN gets fewer at once.
    # A plain run is waiting on ptys and can have as many as there are suites.
    jobs = args.jobs or (max(2, cores // 2) if args.asan else cores)

    env = dict(os.environ)
    if args.asan:
        env["TVNODE_ASAN"] = "1"

    todo = suites(args.only)
    if not todo:
        print("no suites matched", file=sys.stderr)
        return 1

    serial = [s for s in todo if os.path.basename(s[2]) in SERIAL]
    parallel = [s for s in todo if os.path.basename(s[2]) not in SERIAL]

    print(f"{len(todo)} suites, {jobs} at a time"
          + (" (ASAN)" if args.asan else "")
          + (f", {len(serial)} of them on their own" if serial else ""))

    failures = []
    started = time.time()

    for suite in serial:
        report(*run(suite, env), failures=failures)

    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(run, s, env): s for s in parallel}
        for future in concurrent.futures.as_completed(futures):
            report(*future.result(), failures=failures)

    elapsed = time.time() - started
    print(f"\n{len(todo)} suites in {elapsed:.1f}s")
    if failures:
        for label in sorted(failures):
            print(f"FAILED: {label}")
        return 1
    print("every suite passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
