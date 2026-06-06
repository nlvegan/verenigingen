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
"""

import glob
import json
import os
import re
import sys

APP = "verenigingen"
APP_PKG_DIR = f"apps/{APP}/{APP}"  # the python package dir (apps/verenigingen/verenigingen)
FAST_TEST_COST = 0.3  # seconds-equivalent charged per test method (covers sub-2s tests)
OUT = f"apps/{APP}/{APP}/tests/test_timings.json"

ANSI = re.compile(r"\x1b\[[0-9;]*m")
HEADER = re.compile(rf"^({APP}[\w.]+)\s*$")  # e.g. verenigingen.tests.payment.test_x.TestClass
DURATION = re.compile(r"\((\d+\.\d+)s\)")


def dotted_to_relfile(dotted):
    """verenigingen.tests.payment.test_x -> apps/verenigingen/verenigingen/tests/payment/test_x.py"""
    return f"apps/{APP}/" + dotted.replace(".", "/") + ".py"


def measured_slow_seconds(log_paths):
    """Sum >=2s test durations per dotted module, taking the max across logs."""
    best = {}
    for path in log_paths:
        with open(path, errors="ignore") as f:
            txt = ANSI.sub("", f.read())
        cur = None
        per_run = {}
        for line in txt.splitlines():
            h = HEADER.match(line)
            if h and ".test" in h.group(1).lower():
                # strip the trailing .TestClass to get the module dotted path
                cur = h.group(1).rsplit(".", 1)[0]
                continue
            d = DURATION.search(line)
            if d and cur:
                per_run[cur] = per_run.get(cur, 0.0) + float(d.group(1))
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
    slow = measured_slow_seconds(log_paths)

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
            count = count_test_methods(relfile)
            secs = slow.get(dotted, 0.0)
            weights[dotted] = max(1, round(secs + FAST_TEST_COST * count))

    with open(OUT, "w") as f:
        json.dump(dict(sorted(weights.items())), f, indent=1)
        f.write("\n")

    total = sum(weights.values())
    top = sorted(weights.items(), key=lambda x: -x[1])[:10]
    measured = sum(1 for m in weights if m in slow)
    print(f"Wrote {OUT}: {len(weights)} files, {measured} with measured slow-test data, total weight {total}")
    print("Heaviest files:")
    for mod, w in top:
        print(f"  {w:6d}  {mod}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["/tmp/v2*_shard*.log"]))
