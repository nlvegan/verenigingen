#!/usr/bin/env python3
"""Generate verenigingen/tests/test_timings.json for balanced parallel sharding.

Frappe's run-parallel-tests splits test FILES across shards weighted by the
number of `def test_` methods (see frappe/parallel_test_runner.py get_test_weight).
That is a poor proxy for runtime: a file with 3 slow integration tests weighs 3,
a file with 40 trivial unit tests weighs 40 — so shards end up wildly uneven by
wall-clock.

This script produces a per-file weight that approximates real runtime:

    weight = round( measured_slow_seconds  +  FAST_TEST_COST * test_method_count )

- measured_slow_seconds: summed durations of the file's tests that ran >= 2s
  (Frappe only prints "(N.NNs)" for tests over SLOW_TEST_THRESHOLD=2s, so these
  are the only ones we can read from the run logs — but they dominate runtime).
  When a file appears in multiple run logs we take the MAX (stable upper bound).
- FAST_TEST_COST * count: a flat allowance for the many sub-2s tests, which are
  invisible in the logs but add up.

Usage (from frappe-bench root):
    python3 apps/verenigingen/scripts/testing/generate_test_timings.py /tmp/v20_shard*.log /tmp/v21_shard*.log
Writes apps/verenigingen/verenigingen/tests/test_timings.json

Getting fresh logs: take them from a GREEN server-tests run on develop. The workflow
uploads test_output_*.txt only `if: failure()`, so there is no artifact to download
from a passing run - use the job logs, which carry the same teed output:

    RUN=<run id from: gh run list --workflow=server-tests.yml --branch develop>
    gh api "repos/nlvegan/verenigingen/actions/runs/$RUN/jobs?per_page=100" \\
      --jq '.jobs[] | select(.name|test("Tests \\\\(")) | "\\(.id) \\(.name)"'
    # then per job id:
    gh api "repos/nlvegan/verenigingen/actions/jobs/<id>/logs" > /tmp/shard_<n>.log

Regenerate whenever the suite's shape changes materially (a coverage sweep, a large
module added or deleted). A stale table is not inert: files missing from it fall back
to the count heuristic, so the balance silently degrades toward where it started.
"""

import glob
import json
import os
import re
import sys

APP = "verenigingen"
APP_PKG_DIR = f"apps/{APP}/{APP}"  # the python package dir (apps/verenigingen/verenigingen)
FAST_TEST_COST = 0.55  # seconds per sub-2s test method (calibrated from baseline wall-clock)
OUT = f"apps/{APP}/{APP}/tests/test_timings.json"

ANSI = re.compile(r"\x1b\[[0-9;]*m")
# GitHub Actions prefixes every job-log line with an ISO timestamp. Job logs are the
# ONLY source of timing data from a green run: the workflow uploads test_output_*.txt
# as an artifact `if: failure()` only, so a passing run keeps nothing to download.
# Without stripping this, HEADER (anchored with ^) matches nothing and every module
# silently falls back to its count-based weight - a table that looks generated but
# carries no measurements at all.
GHA_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z ", re.M)
HEADER = re.compile(rf"^({APP}[\w.]+)\s*$")  # e.g. verenigingen.tests.payment.test_x.TestClass
DURATION = re.compile(r"\((\d+\.\d+)s\)")


def dotted_to_relfile(dotted):
    """verenigingen.tests.payment.test_x -> apps/verenigingen/verenigingen/tests/payment/test_x.py"""
    return f"apps/{APP}/" + dotted.replace(".", "/") + ".py"


def measured_slow_seconds(log_paths):
    """Per dotted module: (max >=2s-test seconds, slow-test count) across logs."""
    best = {}
    bestcnt = {}
    for path in log_paths:
        with open(path, errors="ignore") as f:
            txt = GHA_TS.sub("", ANSI.sub("", f.read()))
        cur = None
        per_run = {}
        per_cnt = {}
        for line in txt.splitlines():
            h = HEADER.match(line)
            if h and ".test" in h.group(1).lower():
                # strip the trailing .TestClass to get the module dotted path
                cur = h.group(1).rsplit(".", 1)[0]
                continue
            d = DURATION.search(line)
            if d and cur:
                per_run[cur] = per_run.get(cur, 0.0) + float(d.group(1))
                per_cnt[cur] = per_cnt.get(cur, 0) + 1
        for mod, secs in per_run.items():
            if secs > best.get(mod, 0.0):
                best[mod] = secs
                bestcnt[mod] = per_cnt[mod]
    return best, bestcnt


TS_LINE = re.compile(r"^\ufeff?(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?)Z (.*)$")
END_OF_RUN = re.compile(r"^Tests:\s*\d+")


def _parse_ts(stamp):
    from datetime import datetime

    return datetime.fromisoformat(stamp[:26])


def measured_elapsed_seconds(log_paths):
    """Per dotted module: real wall-clock seconds, max across logs (#2184 follow-up).

    GitHub prefixes every job-log line with a timestamp, so a module's cost is the time from
    its first class header to the next module's header (or the "Tests: N" summary). Unlike the
    printed "(N.NNs)" durations this includes setUpClass and every sub-2s test - measured on
    run 42372760702, test_payment_history_scalability took ~800s and weighed 59. Classes of one
    module are summed; a log without timestamps contributes nothing.
    """
    best = {}
    for path in log_paths:
        marks = []
        with open(path, errors="ignore", encoding="utf-8-sig") as f:
            for raw in f:
                m = TS_LINE.match(raw.rstrip("\n"))
                if not m:
                    continue
                body = ANSI.sub("", m.group(2)).strip()
                h = HEADER.match(body)
                if h and ".test" in h.group(1).lower():
                    marks.append((_parse_ts(m.group(1)), h.group(1).rsplit(".", 1)[0]))
                elif END_OF_RUN.match(body) and marks:
                    marks.append((_parse_ts(m.group(1)), None))
                    break
        per_run = {}
        for (t, mod), (t2, _) in zip(marks, marks[1:]):
            per_run[mod] = per_run.get(mod, 0.0) + (t2 - t).total_seconds()
        for mod, secs in per_run.items():
            best[mod] = max(best.get(mod, 0.0), secs)
    return best


def count_test_methods(relfile):
    try:
        with open(relfile, errors="ignore") as f:
            return f.read().count("def test_")
    except OSError:
        return 0


def main(log_globs):
    log_paths = []
    for g in log_globs:
        log_paths.extend(glob.glob(g))
    if not log_paths:
        print("No log files matched; pass shard log paths/globs as args.", file=sys.stderr)
        return 1
    slow, slowcnt = measured_slow_seconds(log_paths)
    elapsed = measured_elapsed_seconds(log_paths)

    # Walk every test file so the table is complete (files with no slow tests
    # still get a count-based weight; new files fall back in the runner patch).
    weights = {}
    for root, dirs, files in os.walk(APP_PKG_DIR):
        for d in ("node_modules", ".git", "public", "__pycache__"):
            if d in dirs:
                dirs.remove(d)
        for fn in files:
            if not (fn.startswith("test_") and fn.endswith(".py")) or fn == "test_runner.py":
                continue
            relfile = os.path.join(root, fn)
            # dotted module path relative to the package dir's parent
            dotted = os.path.relpath(relfile, f"apps/{APP}").replace("/", ".")[: -len(".py")]
            if dotted in elapsed:
                # Real wall-clock time from the timestamped log: includes setUpClass.
                weights[dotted] = max(1, round(elapsed[dotted]))
                continue
            count = count_test_methods(relfile)
            secs = slow.get(dotted, 0.0)
            # measured slow-test seconds + a flat allowance for the remaining
            # sub-2s tests (don't double-charge the slow ones already in `secs`).
            fast = max(0, count - slowcnt.get(dotted, 0))
            weights[dotted] = max(1, round(secs + FAST_TEST_COST * fast))

    with open(OUT, "w") as f:
        json.dump(dict(sorted(weights.items())), f, indent=1)
        f.write("\n")

    total = sum(weights.values())
    top = sorted(weights.items(), key=lambda x: -x[1])[:10]
    timed = sum(1 for m in weights if m in elapsed)
    measured = sum(1 for m in weights if m in slow and m not in elapsed)
    print(
        f"Wrote {OUT}: {len(weights)} files, {timed} timed from log timestamps, "
        f"{measured} more from slow-test durations, total weight {total}"
    )
    print("Heaviest files:")
    for mod, w in top:
        print(f"  {w:6d}  {mod}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["/tmp/v2*_shard*.log"]))
