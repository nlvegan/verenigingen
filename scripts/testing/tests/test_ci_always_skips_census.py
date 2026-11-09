#!/usr/bin/env python3
"""Census of test modules that declare `CI_ALWAYS_SKIPS` (#2364).

The PR-side "Run selected test modules" step of _base-server-tests.yml fails a module whose
tests all skip, unless the module declares `CI_ALWAYS_SKIPS = "<reason>"`. Each marker turns
a red into a warning, so the set is pinned here: adding one is a visible, reviewed diff,
never a quiet way to get a PR green.

Stdlib only.
"""

import importlib.util
import re
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[3]
PKG = APP / "verenigingen"

ANY_MARKER = re.compile(r"^\s*CI_ALWAYS_SKIPS\b", re.M)

EXPECTED = {
    # Live Mollie charge; CI has no gateway credentials by design.
    "verenigingen.verenigingen_payments.mollie.tests.test_recurring_charge_live",
    # Real HTTP to a live web server; a CI runner has none. A WSGI rewrite would let this
    # one check something in CI and leave the census (#2364, option 1).
    "verenigingen.tests.integration.test_payment_processing_http_integration",
}


def marked_modules():
    found = {}
    for path in sorted(PKG.rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if ANY_MARKER.search(text):
            module = ".".join(path.relative_to(APP).with_suffix("").parts)
            found[module] = text
    return found


def _step_module():
    """The step tests' module, loaded by path so this works under `discover -s` and `-m`.
    Kept as a module object, never a top-level TestCase name, so it is not collected twice."""
    path = Path(__file__).with_name("test_module_mode_step.py")
    spec = importlib.util.spec_from_file_location("_module_mode_step_for_census", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def gate_accepts(source: str) -> bool:
    """Run the REAL workflow step on an all-skipped module with this source. Asking the
    gate itself (not a copy of its pattern) is what keeps this census from drifting from it."""
    runner = _step_module().ModuleStep("test_ok_module_is_green")
    rc, out = runner.run_step("Ran 2 tests in 0.1s\n\nOK (skipped=2)", module_source=source)
    return rc == 0 and "::warning::" in out


class CiAlwaysSkipsCensus(unittest.TestCase):
    def test_the_marked_set_is_exactly_the_reviewed_one(self):
        self.assertEqual(set(marked_modules()), EXPECTED)

    def test_every_marker_is_one_the_gate_actually_reads(self):
        # A marker the gate does not read looks declared and still fails every PR that selects it.
        unread = sorted(m for m, src in marked_modules().items() if not gate_accepts(src))
        self.assertEqual(unread, [], "write it as a top-level CI_ALWAYS_SKIPS = \"<reason>\"")


if __name__ == "__main__":
    unittest.main()
