#!/usr/bin/env python3
"""Test-leak ratchet gate.

A test that leaves a record behind does not fail. A *later* test in the same shard
collides with the leftover and fails, naming neither the record nor the test that
produced it -- five failures across #326/#327 were exactly that shape. #329 fixed the
attribution half: `EnhancedTestCase` now prints one line per leaked record,

    TEST-LEAK <module.Class.method> <Doctype>::<name> <reason>

This is the other half: the lines are compared against a committed per-module baseline
so the number can only fall (#328).

Per MODULE, not per test id, deliberately: a leak count is a property of what a module
leaves in the database, and test methods get renamed and split far more often than
modules do. A per-id baseline would go stale on every refactor and teach people to
regenerate it, which defeats a ratchet.

Usage:
    check_test_leaks.py --results <shard.log> [--baseline <file>] [--update]
    check_test_leaks.py --results <shard.log> --emit-baseline    # counts, for seeding

Exit codes:
    0  no module leaks more than its baseline
    1  at least one module leaks MORE than its baseline (regression) -- gate fails
    2  usage / IO error, or the run did not finish (inconclusive, NOT clean)

Scope: a shard log covers only that shard's ~110 modules. Modules absent from the log
did not run and are left untouched -- neither judged nor ratcheted.
"""

import argparse
import re
import sys
from collections import Counter
from pathlib import Path
from typing import NamedTuple

_ANSI = re.compile(r"\x1b\[[0-9;]*m")

# The marker line as `format_leak_lines` emits it, as it ARRIVES in a shard log:
# indented and behind frappe's U+25B9 stdout marker, so it is never at column 0.
# The dotted `module.Class.method` id is the whole guard against matching prose that
# merely mentions the marker; the record identity is deliberately NOT required, so a
# line CI truncated mid-record still counts as the leak it is.
_LEAK = re.compile(
    r"TEST-LEAK\s+([A-Za-z_][\w.]*\.[A-Za-z_]\w*\.[A-Za-z_]\w*)(?:\s+(.*))?$",
    re.MULTILINE,
)

# The class header the parallel runner prints on its own line before running a class:
#   verenigingen.tests.test_a.ClassA
# Column 0 and nothing else on the line -- indented lines are test results.
_CLASS_HEADER = re.compile(r"^([A-Za-z_][\w.]*\.[A-Z]\w*)\s*$")

# Authoritative end-of-run sentinel from ParallelTestRunner.print_result(). Absent =
# the shard crashed/hung/was killed before finishing, so "no leaks parsed" means
# nothing. Mirrors the same guard in check_new_test_failures.py.
_SENTINEL = re.compile(r"Tests:\s*\d+,\s*Failing:\s*\d+,\s*Errors:\s*\d+")

DEFAULT_BASELINE = (
    Path(__file__).resolve().parents[1].parent / "verenigingen" / "tests" / "known_test_leaks.txt"
)


class Leak(NamedTuple):
    test_id: str
    module: str
    detail: str


def extract_leaks(text: str, on_unparseable=None) -> list:
    """Every distinct leaked record in the log, in the order it was reported.

    Distinct on (test id, record): under VERENIGINGEN_FAIL_ON_TEST_LEAK the same
    record is printed AND echoed inside the AssertionError, and counting that twice
    reports a regression that is one leak seen in two places. Keying on the test id
    alone would be far worse -- it would drop every record after the first that a
    single test leaks, which is the normal shape (a Member and its Membership).
    """
    clean = _ANSI.sub("", text)
    leaks = []
    seen = set()
    for match in _LEAK.finditer(clean):
        test_id = match.group(1)
        module = test_id.rsplit(".", 2)[0]
        # A cut inside the id still matches a SHORTER dotted path, and rsplit would
        # then name a package rather than a module ("verenigingen.tests.payment").
        # That is never in the baseline, so it would fail an unrelated PR while
        # naming something that does not exist. Frappe only collects `test_*.py`,
        # so a real module's last component always starts with `test_`; anything
        # else is a truncated line, and dropping it beats inventing a module.
        if not module.rsplit(".", 1)[-1].startswith("test_"):
            if on_unparseable:
                on_unparseable(match.group(0))
            continue
        detail = (match.group(2) or "").strip()
        if (test_id, detail) in seen:
            continue
        seen.add((test_id, detail))
        leaks.append(Leak(test_id=test_id, module=module, detail=detail))
    return leaks


def count_by_module(leaks) -> dict:
    return dict(Counter(leak.module for leak in leaks))


def modules_that_ran(text: str) -> set:
    """Modules this log shows actually executing."""
    clean = _ANSI.sub("", text)
    return {
        match.group(1).rsplit(".", 1)[0]
        for match in (_CLASS_HEADER.match(line) for line in clean.splitlines())
        if match
    }


def run_completed(text: str) -> bool:
    return bool(_SENTINEL.search(_ANSI.sub("", text)))


class BaselineError(Exception):
    """The baseline file is unusable -- a usage error, not a leak regression."""


def load_baseline(path: Path) -> dict:
    """`<module> <count>` per line; `#` comments and blanks ignored.

    Raises rather than letting a bad line become an exit-1: exit 1 means "this
    change leaks more", and a malformed baseline must never be able to say that.
    A duplicate entry is refused outright -- last-wins would let someone APPEND
    `mod 9` beneath `mod 1` and silently raise a ratchet that is supposed to be
    incapable of rising.
    """
    baseline = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        module, _, count = line.rpartition(" ")
        module = module.strip()
        try:
            parsed = int(count)
        except ValueError:
            raise BaselineError(f"{path}:{number}: expected '<module> <count>', got {raw!r}")
        if module in baseline:
            raise BaselineError(
                f"{path}:{number}: '{module}' is listed twice "
                f"({baseline[module]} and {parsed}). Edit the existing entry."
            )
        baseline[module] = parsed
    return baseline


def render_baseline(counts: dict, header_lines) -> str:
    body = "\n".join(f"{module} {count}" for module, count in sorted(counts.items()))
    return "\n".join([*header_lines, body]) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True, help="bench run-parallel-tests output file")
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    parser.add_argument(
        "--emit-baseline",
        action="store_true",
        help="print the observed per-module counts and exit (for seeding the baseline)",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="ratchet the baseline DOWN to what this run observed (refuses on a regression)",
    )
    args = parser.parse_args(argv)

    results_path = Path(args.results)
    if not results_path.exists():
        print(f"::error::results file not found: {results_path}", file=sys.stderr)
        return 2

    text = results_path.read_text(encoding="utf-8", errors="replace")
    unparseable = []
    leaks = extract_leaks(text, on_unparseable=unparseable.append)
    observed = count_by_module(leaks)

    incomplete = not run_completed(text)
    if incomplete:
        print(
            "::error::End-of-run sentinel ('Tests: N, Failing: N, Errors: N') not found -- "
            "the run did not complete (killed/hung shard or truncated log), so 'no leaks' "
            "would be an artefact of the log ending early. Re-run the job.",
            file=sys.stderr,
        )
        return 2

    if unparseable:
        # Not fatal: each is a leak we could not attribute, so the count is a floor.
        print(
            f"::warning::{len(unparseable)} TEST-LEAK line(s) were truncated mid-identifier "
            f"and skipped, e.g. {unparseable[0]!r}"
        )

    if args.emit_baseline:
        for module, count in sorted(observed.items()):
            print(f"{module} {count}")
        return 0

    baseline_path = Path(args.baseline)
    if not baseline_path.exists():
        print(f"::error::baseline file not found: {baseline_path}", file=sys.stderr)
        return 2
    try:
        baseline = load_baseline(baseline_path)
    except BaselineError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 2

    # A module that leaked obviously ran, even if its header was swallowed.
    ran = modules_that_ran(text) | set(observed)

    regressions = sorted(
        (module, observed[module], baseline.get(module, 0))
        for module in observed
        if observed[module] > baseline.get(module, 0)
    )
    improvements = sorted(
        (module, observed.get(module, 0), baseline[module])
        for module in ran
        if module in baseline and observed.get(module, 0) < baseline[module]
    )

    print(f"Modules run in this log: {len(ran)}")
    print(f"Leaked records parsed:   {len(leaks)} across {len(observed)} module(s)")
    print(f"  regressions:           {len(regressions)}")
    print(f"  improvements:          {len(improvements)}")

    if regressions:
        print("\n::error::These modules leak more records than their baseline allows:")
        for module, now, allowed in regressions:
            print(f"  - {module}: {now} leaked, baseline {allowed}")
        for leak in leaks:
            if any(leak.module == module for module, _, _ in regressions):
                print(f"      {leak.test_id}  {leak.detail}")
        print(
            "\nA leaked record outlives its test and fails a later one in the same shard. "
            "Make the test own and release what it creates; see "
            "verenigingen/tests/utils/leak_guard.py. Run the module with "
            "VERENIGINGEN_FAIL_ON_TEST_LEAK=1 to fail at the leak instead of here."
            "\n\nA leak can also be timing-dependent -- cleanup gives up after three "
            "QueryTimeoutError retries (tests/utils/base.py) -- so if this names a module "
            "your change did not touch, re-run the job before digging."
        )
        if args.update:
            print("::error::--update refuses to raise a baseline; nothing written.")
        return 1

    if args.update and improvements:
        header = [
            line
            for line in baseline_path.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith("#")
        ]
        updated = dict(baseline)
        for module, now, _ in improvements:
            updated[module] = now
        baseline_path.write_text(render_baseline(updated, header), encoding="utf-8")
        print(f"\nBaseline ratcheted down for {len(improvements)} module(s).")

    if improvements and not args.update:
        print("\nThese modules now leak less than their baseline (re-run with --update):")
        for module, now, allowed in improvements:
            print(f"  - {module}: {now} leaked, baseline {allowed}")

    print("\nNo module leaks more than its baseline. ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
