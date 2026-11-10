"""#2361: `bench execute` seeding must run under the test context the runner sets.

`bench execute` leaves `frappe.in_test` False, so Frappe's password-strength policy
refuses erpnext's fixture users ("This is a top-10 common password.") on a fresh site.
The seed entry point must switch the test context on for `before_tests` and restore it.
"""

import unittest

import frappe
from frappe.tests.utils import toggle_test_mode

import verenigingen.tests.setup as setup_module


class TestSeedForStandaloneModuleRuns(unittest.TestCase):
    def setUp(self):
        self._real = setup_module.before_tests
        self.addCleanup(setattr, setup_module, "before_tests", self._real)
        self.seen = {}
        # The runner has in_test ON; `bench execute` has it OFF. Reproduce the latter,
        # or the assertions below hold without the entry point doing anything.
        self.addCleanup(toggle_test_mode, frappe.in_test)
        toggle_test_mode(False)
        self.addCleanup(setattr, frappe.flags, "mute_emails", frappe.flags.mute_emails)
        frappe.flags.mute_emails = False

    def _probe(self, raises=False):
        def probe():
            self.seen["in_test"] = frappe.in_test
            self.seen["flag"] = frappe.local.flags.in_test
            self.seen["muted"] = frappe.flags.mute_emails
            if raises:
                raise RuntimeError("seed failed")

        setup_module.before_tests = probe

    def test_before_tests_runs_in_test_mode_with_mail_muted(self):
        self._probe()
        setup_module.seed_for_standalone_module_runs()
        self.assertEqual(self.seen, {"in_test": True, "flag": True, "muted": True})

    def test_the_context_is_restored_afterwards_and_on_failure(self):
        before = (frappe.in_test, frappe.local.flags.in_test, frappe.flags.mute_emails)
        self._probe(raises=True)
        with self.assertRaises(RuntimeError):
            setup_module.seed_for_standalone_module_runs()
        self.assertEqual(
            (frappe.in_test, frappe.local.flags.in_test, frappe.flags.mute_emails), before
        )
