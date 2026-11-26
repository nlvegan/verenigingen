#!/usr/bin/env python3
"""Self-test for doctype_name_validator.AUTHORITY_PROBES (#3332).

Each probe exists to prove ONE app is loaded. A probe that a second app also
defines proves nothing: "Payment Gateway Account" is an ERPNext doctype, so a
bench without the payments app still passed the probe and the gate ran against a
census silently missing every payments doctype.

Needs a bench with every REQUIRED app beside this one (the same condition as the
real-authority tests in test_doctype_name_validator.py); CI's standalone checkout
has no sibling apps, so these skip there, and the real-bench gate is
verenigingen/tests/test_doctype_name_ratchet.py.

Run: python -m unittest discover -s scripts/validation/tests -p 'test_doctype_name_authority_probes_3332.py'
"""
import importlib.util
import sys
import unittest
import unittest.mock
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "doctype_name_validator.py"
_spec = importlib.util.spec_from_file_location("doctype_name_validator", _MOD_PATH)
dnv = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = dnv
_spec.loader.exec_module(dnv)

# Skip only when a sibling app is genuinely absent (CI's standalone checkout). Do NOT
# skip on authority_problem(): a typo'd probe makes that non-None and would skip every
# test here, hiding exactly the defect these tests exist to catch.
_ABSENT_APPS = [app for app in dnv.REQUIRED_APPS if not dnv.doctypes_defined_by(app)]
_needs_real_bench = unittest.skipIf(
    bool(_ABSENT_APPS), f"needs a full multi-app bench; no doctypes loaded for {_ABSENT_APPS}"
)


@_needs_real_bench
class TestAuthorityProbesAreUniqueToTheirApp(unittest.TestCase):
    def test_every_probe_is_defined_by_exactly_its_own_app(self):
        self.assertEqual(dnv.probes_not_unique_to_their_app(), {})

    def test_probes_cover_exactly_the_required_apps(self):
        self.assertEqual(set(dnv.AUTHORITY_PROBES), set(dnv.REQUIRED_APPS))

    def test_control_the_uniqueness_check_can_see_a_shared_doctype(self):
        # Control: the real shape of #3332. erpnext defines this payments-era doctype.
        self.assertIn("Payment Gateway Account", dnv.doctypes_defined_by("erpnext"))
        self.assertNotIn("Payment Gateway Account", dnv.doctypes_defined_by("payments"))


@_needs_real_bench
class TestMissingPaymentsAppIsDetected(unittest.TestCase):
    def _without(self, app_name):
        # A bench that lacks the app: the loader never sees it, so a doctype another
        # app also defines is still attributed to that other app (known_doctypes()
        # is first-definer-wins, so filtering the full census would hide exactly that).
        remaining = tuple(a for a in dnv.REQUIRED_APPS if a != app_name)
        with unittest.mock.patch.object(dnv, "REQUIRED_APPS", remaining):
            return dnv.known_doctypes()

    def test_dropping_payments_is_reported(self):
        problem = dnv.authority_problem(self._without("payments"))
        self.assertIsNotNone(problem)
        self.assertIn("'payments'", problem)

    def test_control_the_full_authority_is_accepted(self):
        self.assertIsNone(dnv.authority_problem(dnv.known_doctypes()))

    def test_dropping_any_required_app_is_reported(self):
        for app in dnv.REQUIRED_APPS:
            with self.subTest(app=app):
                self.assertIsNotNone(dnv.authority_problem(self._without(app)))


if __name__ == "__main__":
    unittest.main()
