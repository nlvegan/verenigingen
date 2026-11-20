#!/usr/bin/env python3
"""Decide whether a test module's "checked nothing" result is acceptable (#2364).

The PR census job (`_base-server-tests.yml`, "Run selected test modules") fails a module that
ran no tests or skipped all of them: exit 0 plus an `OK` line is not proof anything was checked.
Some modules legitimately ALWAYS skip in CI (a live-gateway test needs credentials a runner
never has, so every PR touching a helper it imports would go red whatever its diff).

Such a module declares, at module level:

    CI_ALWAYS_SKIPS = "<one-line reason>"

and only then is an all-skip run accepted, with a notice naming the reason. The set of marked
modules is pinned by scripts/validation/tests/test_ci_always_skips_census.py, so adding a marker
is a visible, reviewed change. An unmarked all-skip module stays red.

Usage (the workflow calls this only when ran == 0 or skipped >= ran):
    check_ci_always_skips.py --module <dotted> --ran N --skipped N --app-root <apps/verenigingen>
Exit 0 = acceptable, 1 = red. GitHub annotations go to stdout.
"""

import argparse
import ast
import sys
from pathlib import Path

MARKER = "CI_ALWAYS_SKIPS"


def marker_reason(source: str):
    """The module-level marker's FINAL value: None when absent (or deleted), otherwise a str
    (possibly empty), or a non-str when the last binding is not a string literal. The last
    binding wins, as at import time. Raises SyntaxError on unparseable source."""
    result = None
    for node in ast.parse(source).body:
        if isinstance(node, ast.Delete) and any(
            isinstance(t, ast.Name) and t.id == MARKER for t in node.targets
        ):
            result = None
        elif isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == MARKER for t in node.targets
        ):
            result = node.value.value if isinstance(node.value, ast.Constant) else ""
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == MARKER:
            result = node.value.value if isinstance(node.value, ast.Constant) else ""
    return result


def decide(source, module: str, ran: int, skipped: int):
    """`(acceptable, annotation_lines)` for a module that ran `ran` tests, `skipped` of them skipped.
    `source` is the module's text, or None when it could not be read."""
    if ran > 0 and skipped < ran:
        reason = _safe_reason(source)
        if isinstance(reason, str) and reason.strip():
            return True, [f"::notice::{module} carries {MARKER} but ran {ran - skipped} test(s); the marker may be stale"]
        return True, []
    checked_nothing = f"::error::{module} checked nothing: ran {ran} test(s), {skipped} skipped"
    reason = _safe_reason(source)
    if reason is None:
        return False, [checked_nothing, f"If it can never run in CI, declare {MARKER} = \"<reason>\" at module level (#2364)"]
    if not isinstance(reason, str) or not reason.strip():
        return False, [checked_nothing, f"::error::{module} declares {MARKER} without a non-empty string reason"]
    return True, [f"::notice::{module} checked nothing in CI by declaration ({MARKER}): {reason.strip()}"]


def _safe_reason(source):
    if source is None:
        return None
    try:
        return marker_reason(source)
    except SyntaxError:
        return None


def module_path(app_root: Path, module: str) -> Path:
    return app_root / Path(*module.split(".")).with_suffix(".py")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--module", required=True)
    ap.add_argument("--ran", type=int, required=True)
    ap.add_argument("--skipped", type=int, required=True)
    ap.add_argument("--app-root", type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        source = module_path(args.app_root, args.module).read_text()
    except OSError:
        source = None
    ok, lines = decide(source, args.module, args.ran, args.skipped)
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
