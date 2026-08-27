#!/usr/bin/env python3
"""No-new-test-failures gate.

This gates against `verenigingen/tests/known_test_failures.txt`; read that file's
header for what it currently contains, and `test_committed_baseline_is_empty` in
verenigingen/tests/test_check_new_test_failures.py for what is enforced. As of
2026-07-26 it is empty, so a red result here is a NEW failure -- do not reach for
"probably pre-existing".

Note the gate is only as good as the parser below: a failure the result regex
does not match is invisible to it, and the sentinel shortfall warning cannot fire
for small counts (`reported_total * 0.9 - 5` is negative for totals <= 5).

This docstring used to cite "~2,336 failing tests across ~170 root-cause
signatures" from docs/plans/2026-05-29-server-tests-red-baseline-triage.md. That
was a 2026-05-29 snapshot and it answered the "is this red pre-existing?" question
wrongly for months; the triage doc remains accurate about that date and useless as
a statement about today. Removed with #573, which deleted the other copy of the
same stale answer (`known_test_failures_v16.txt`).

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
    prints the normalized failing-test ids to stdout). Baseline entries that
    recurred in this run are reported as a count (`matched baseline (allowed)`).
    This script does NOT report "newly passing" -- it cannot tell which baseline
    tests ran in a given shard; see the comment above `recurred` in main().
"""

import argparse
import re
import sys
from pathlib import Path

# Matches Frappe's parallel-test result lines, with or without ANSI colour codes:
#   "\x1b[41m FAIL \x1b[0m test_name (a.b.C.test_name)"
#   "ERROR test_name (a.b.C.test_name)"   /   "FAIL: test_name (a.b.C.test_name)"
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
# Frappe prints each failure/error in the END-OF-RUN summary (printErrors) as
#   " FAIL  <name> (<dotted.path>)"  /  " ERROR  <name> (<dotted.path>)"
# where <name> is a test method (test_*) OR a fixture hook whose failure fails a
# whole class/module (setUpClass, setUpModule, setUp, tearDownClass, ...). We must
# capture the hook forms too — a NEW setUpClass error fails an entire class.
_RESULT = re.compile(
    r"(?:^|\s)(?:FAIL|ERROR)[: ]\s*"
    r"((?:test_[A-Za-z0-9_]+|setUpClass|setUpModule|setUp|tearDownClass|tearDownModule|tearDown)"
    r" \([A-Za-z0-9_.]+\))"
)
# Authoritative end-of-run sentinel, emitted by ParallelTestRunner.print_result()
# via click.echo(TestResult) AFTER the failure summary — present on EVERY completed
# run (even green), absent if the shard crashed/hung mid-run. Requiring it closes
# the false-pass hole where a crash before the summary leaves only streamed "✖"
# markers (which carry no dotted path and are NOT in the summary the regex reads).
_SENTINEL = re.compile(r"Tests:\s*(\d+),\s*Failing:\s*(\d+),\s*Errors:\s*(\d+)")

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


def run_completed(text: str):
    """Return (failing, errors) from the end-of-run sentinel, or None if absent.

    None means the shard did NOT finish (crashed/hung/killed before
    print_result), so the failure summary the gate diffs against was never
    emitted — the run must be treated as inconclusive, not "0 new failures".
    """
    m = _SENTINEL.search(text)
    if not m:
        return None
    return int(m.group(2)), int(m.group(3))


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

    # Completeness guard: require the authoritative end-of-run sentinel. Without
    # it the shard crashed/hung before emitting the failure summary, so "0 parsed
    # failures" is meaningless — fail safe rather than rubber-stamp a green check.
    completed = run_completed(results_text)
    if completed is None:
        print(
            "::error::End-of-run sentinel ('Tests: N, Failing: N, Errors: N') not found — "
            "the test run did not complete (infra-killed/hung shard or truncated log). "
            "This is treated as a gate failure; re-run the job.",
            file=sys.stderr,
        )
        return 2

    reported_failing, reported_errors = completed
    reported_total = reported_failing + reported_errors
    # Sanity cross-check (informational): parsed unique test ids should be close to
    # the suite's reported failing+errors. They won't match exactly — subTests are
    # counted per-subtest in the sentinel but collapse to one method id here. A
    # large shortfall hints the parser missed a new result format.
    if len(failures) < reported_total * 0.9 - 5:
        print(
            f"::warning::parsed {len(failures)} failing test ids but the suite reported "
            f"{reported_total} (failing={reported_failing}, errors={reported_errors}); the "
            f"result parser may be missing some lines — review scripts/testing/check_new_test_failures.py",
        )

    baseline = load_baseline(Path(args.baseline))
    new_failures = sorted(failures - baseline)
    # "newly passing" = baseline tests that ran in THIS shard and did not fail.
    # We cannot tell which baseline tests ran in this shard, so we only report
    # the count of baseline failures that recurred (informational).
    recurred = failures & baseline

    print(f"Run completed (suite reported failing={reported_failing}, errors={reported_errors})")
    print(f"Parsed failing test ids:      {len(failures)}")
    print(f"  matched baseline (allowed): {len(recurred)}")
    print(f"  NEW (regressions):          {len(new_failures)}")

    if new_failures:
        print("\n::error::This change introduces test failures not in the baseline:")
        for tid in new_failures:
            print(f"  - {tid}")
        print(
            "\nIf a NEW failure looks flaky, re-run the job. Otherwise fix it: "
            "the baseline has been EMPTY since 2026-07-26, so 'it was already "
            "failing' is almost certainly wrong. Baselining a red test is a "
            "deliberate act that needs a recorded reason (see "
            "verenigingen/tests/known_test_failures.txt)."
        )
        return 1

    print("\nNo new test failures. ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
