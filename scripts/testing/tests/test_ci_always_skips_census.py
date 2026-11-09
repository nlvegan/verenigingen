#!/usr/bin/env python3
"""Census of test modules that declare `CI_ALWAYS_SKIPS` (#2364).

The PR-side "Run selected test modules" step of _base-server-tests.yml fails a module whose
tests all skip, unless the module declares `CI_ALWAYS_SKIPS = "<reason>"`. Each marker turns
a red into a warning, so the set is pinned here: adding one is a visible, reviewed diff,
never a quiet way to get a PR green.

Stdlib only.
"""

import re
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[3]
PKG = APP / "verenigingen"

# The exact pattern the workflow step reads. A marker it would NOT read is an error too:
# it would look declared and still fail every PR that selects the module.
GATE_READS = re.compile(r"""^CI_ALWAYS_SKIPS = ["'][^"']+["']""", re.M)
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
            found[module] = bool(GATE_READS.search(text))
    return found


class CiAlwaysSkipsCensus(unittest.TestCase):
    def test_the_marked_set_is_exactly_the_reviewed_one(self):
        self.assertEqual(set(marked_modules()), EXPECTED)

    def test_every_marker_is_one_the_gate_actually_reads(self):
        unread = sorted(m for m, read in marked_modules().items() if not read)
        self.assertEqual(unread, [], "write it as a top-level CI_ALWAYS_SKIPS = \"<reason>\"")


if __name__ == "__main__":
    unittest.main()
