#!/usr/bin/env python3
"""Census of test modules that declare `CI_ALWAYS_SKIPS` (#2364).

The PR census job accepts an all-skip run only for a module carrying that marker
(scripts/testing/check_ci_always_skips.py), so every marker widens what CI no longer checks.
This pins the SET: adding or removing a marker fails here until `PINNED` is updated, which makes
the change visible in review. Mark only a module that ALWAYS skips in CI (evidence: run it under
scripts/testing/run_without_credentials.sh and show every test skipped); a module that runs some
tests without credentials must not be marked.
"""

import importlib.util
import re
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "check_ci_always_skips", _ROOT / "scripts" / "testing" / "check_ci_always_skips.py"
)
cas = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cas)

PINNED = {
    "verenigingen/tests/backend/workflows/test_payment_failure_recovery.py",  # #2467, not credentials
    "verenigingen/tests/e2e/test_workflow_validation.py",  # class @unittest.skip'd, not credentials
    "verenigingen/tests/payment/test_payment_gateways_live.py",
    "verenigingen/tests/sepa/test_bank_integration_boundaries.py",  # env-gated, never set in CI
    "verenigingen/verenigingen_payments/ing_checkout/tests/test_client_live.py",
    "verenigingen/verenigingen_payments/mollie/tests/integration/test_real_api.py",
    "verenigingen/verenigingen_payments/mollie/tests/test_mollie_portal_endpoints_live.py",
    "verenigingen/verenigingen_payments/mollie/tests/test_recurring_charge_live.py",
    "verenigingen/verenigingen_payments/mollie/tests/test_subscription_cancel_bookkeeping_live.py",
    "verenigingen/verenigingen_payments/mollie/tests/test_subscription_service_live.py",
}

_ASSIGNMENT = re.compile(rf"^[ \t]*{cas.MARKER}\b[ \t]*[:=]", re.M)


def _scan():
    """`{relative path: marker value}` for every module under verenigingen/ with a module-level
    marker, plus the paths whose text assigns the name somewhere the checker would not see."""
    found, invisible = {}, []
    for path in sorted((_ROOT / "verenigingen").rglob("*.py")):
        source = path.read_text(errors="replace")
        if cas.MARKER not in source:
            continue
        rel = str(path.relative_to(_ROOT))
        try:
            reason = cas.marker_reason(source)
        except SyntaxError:
            continue
        if reason is not None:
            found[rel] = reason
        elif _ASSIGNMENT.search(source):
            invisible.append(rel)
    return found, invisible


class CiAlwaysSkipsCensus(unittest.TestCase):
    def test_the_set_of_marked_modules_is_the_pinned_set(self):
        found, _ = _scan()
        self.assertEqual(
            set(found),
            PINNED,
            "CI_ALWAYS_SKIPS markers changed. Adding one hides a module from the PR job's "
            "'checked nothing' gate: update PINNED in this file and justify it in the PR "
            "(evidence: the module skips every test under run_without_credentials.sh).",
        )

    def test_every_marker_carries_a_non_empty_reason(self):
        found, _ = _scan()
        for rel, reason in found.items():
            with self.subTest(module=rel):
                self.assertIsInstance(reason, str)
                self.assertTrue(reason.strip(), f"{rel} declares CI_ALWAYS_SKIPS without a reason")

    def test_no_marker_is_assigned_where_the_checker_cannot_see_it(self):
        # A nested or conditional marker reads as absent to the PR job: it would look like an
        # exemption and still go red.
        _, invisible = _scan()
        self.assertEqual(invisible, [])

    def test_control_the_scan_sees_a_real_marker_and_ignores_a_nested_one(self):
        # Without this a broken scan (empty result) would make the pinned-set test fail loudly,
        # but the "invisible" test above would pass vacuously.
        self.assertTrue(_ASSIGNMENT.search('class T:\n    CI_ALWAYS_SKIPS = "x"\n'))
        self.assertIsNone(cas.marker_reason('class T:\n    CI_ALWAYS_SKIPS = "x"\n'))
        self.assertEqual(cas.marker_reason('CI_ALWAYS_SKIPS = "x"\n'), "x")


if __name__ == "__main__":
    unittest.main()
