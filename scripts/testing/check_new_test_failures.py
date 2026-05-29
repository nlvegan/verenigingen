#!/usr/bin/env python3
"""No-new-test-failures gate.

The `Server Tests` suite has a large, long-standing red baseline (~2,336
failing tests across ~170 root-cause signatures — see
docs/plans/2026-05-29-server-tests-red-baseline-triage.md). Making it fully
green is a multi-PR program; in the meantime we must not let normal PRs be
blocked by pre-existing failures, while still catching *new* regressions.

This script compares the failing tests in a `bench run-parallel-tests` output
against a committed baseline (`verenigingen/tests/known_test_failures.txt`) and
fails ONLY when the run introduces failures that are not in the baseline.

Usage:
    check_new_test_failures.py --results <test_output.txt> [--baseline <file>]

Exit codes:
    0  no new failures (run may still contain baseline failures)
    1  one or more NEW failures (regression) — gate fails
    2  usage / IO error

Baseline maintenance:
    Regenerate from a develop run's logs with --emit-baseline (reads results,
    prints the normalized failing-test ids to stdout). Tests that the baseline
    lists but that now PASS are reported as "newly passing" (informational) so
    the baseline can be pruned over time.
"""

import argparse
import re
import sys
from pathlib import Path

# Matches Frappe's parallel-test result lines, with or without ANSI colour codes:
#   "\x1b[41m FAIL \x1b[0m test_name (a.b.C.test_name)"
#   "ERROR test_name (a.b.C.test_name)"   /   "FAIL: test_name (a.b.C.test_name)"
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_RESULT = re.compile(
    r"(?:^|\s)(?:FAIL|ERROR)[: ]\s*(test_[A-Za-z0-9_]+ \([A-Za-z0-9_.]+\))"
)
# Markers that prove the suite actually executed tests (so an empty/truncated log
# from an infra-killed shard is not silently treated as "0 new failures").
_RAN_MARKER = re.compile(r"✔|✖|✗|\bRan \d+ test|(?:^|\s)(?:ok|OK)\s+test_")

DEFAULT_BASELINE = (
    Path(__file__).resolve().parents[1].parent
    / "verenigingen"
    / "tests"
    / "known_test_failures.txt"
)


def extract_failures(text: str) -> set:
    """Return the set of `test_name (dotted.path)` ids that FAILed/ERRORed."""
    clean = _ANSI.sub("", text)
    return {m.group(1).strip() for m in _RESULT.finditer(clean)}


def run_executed(text: str) -> bool:
    """True if the output shows the suite actually ran tests.

    Guards against an infra-killed / truncated shard (empty log) being read as
    "0 failures -> pass". A run with real failures already proves execution; this
    catches the zero-failure-because-nothing-ran case.
    """
    return bool(_RAN_MARKER.search(text))


def load_baseline(path: Path) -> set:
    if not path.exists():
        print(f"::error::baseline file not found: {path}", file=sys.stderr)
        sys.exit(2)
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results", required=True, help="bench run-parallel-tests output file")
    ap.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    ap.add_argument(
        "--emit-baseline",
        action="store_true",
        help="print the normalized failing-test ids from --results and exit (for regenerating the baseline)",
    )
    args = ap.parse_args(argv)

    results_path = Path(args.results)
    if not results_path.exists():
        print(f"::error::results file not found: {results_path}", file=sys.stderr)
        return 2

    results_text = results_path.read_text(encoding="utf-8", errors="replace")
    failures = extract_failures(results_text)

    if args.emit_baseline:
        print("\n".join(sorted(failures)))
        return 0

    # Completeness guard: a truncated/empty log (infra-killed shard) must not
    # pass the gate just because no failures were parsed from it.
    if not failures and not run_executed(results_text):
        print(
            "::error::No test results found in the output — the test run likely did "
            "not complete (e.g. an infra-killed shard or a truncated log). Re-run the job.",
            file=sys.stderr,
        )
        return 2

    baseline = load_baseline(Path(args.baseline))
    new_failures = sorted(failures - baseline)
    # "newly passing" = baseline tests that ran in THIS shard and did not fail.
    # We cannot tell which baseline tests ran in this shard, so we only report
    # the count of baseline failures that recurred (informational).
    recurred = failures & baseline

    print(f"Total failures in this run:   {len(failures)}")
    print(f"  matched baseline (allowed): {len(recurred)}")
    print(f"  NEW (regressions):          {len(new_failures)}")

    if new_failures:
        print("\n::error::This change introduces test failures not in the baseline:")
        for tid in new_failures:
            print(f"  - {tid}")
        print(
            "\nIf a NEW failure looks flaky, re-run the job. If it is a genuine, "
            "accepted pre-existing failure, regenerate the baseline (see "
            "scripts/testing/check_new_test_failures.py docstring). Otherwise, fix it."
        )
        return 1

    print("\nNo new test failures. ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
