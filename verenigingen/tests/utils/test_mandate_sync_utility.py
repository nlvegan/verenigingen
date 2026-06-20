# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen Contributors
# See license.txt

"""Regression tests for the Mandate Sync utility.

This utility was deleted in commit 51705976 ("remove 87 orphaned utils") even
though it was NOT orphaned -- the "Sync mandates" button on the
mollie_member_reconciliation portal page calls it. These tests guard the JS
button contract (the dotted method path must resolve to a whitelisted function
returning a report with a `summary` block) and the core no-Mollie-call paths.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase

# The exact dotted path the portal button (mollie_member_reconciliation.html) calls.
BUTTON_METHOD_PATH = "verenigingen.utils.admin_utilities.mandate_sync_utility.run_mandate_sync"

# The summary keys the page JS reads off the result (unwrapOperationResult -> data.summary).
JS_SUMMARY_KEYS = {
    "updated",
    "already_set",
    "no_mandates",
    "multiple_mandates",
    "invalid_mandates",
    "errors",
}


class TestMandateSyncUtility(VereningingenTestCase):
    def test_button_method_path_resolves_and_is_whitelisted(self):
        """The portal 'Sync mandates' button calls a dotted path; it must resolve
        to a whitelisted function or the button 404s."""
        method = frappe.get_attr(BUTTON_METHOD_PATH)
        self.assertTrue(callable(method))
        self.assertIn(method, frappe.whitelisted)

    def test_generate_report_summary_has_js_contract_keys(self):
        """The report the button renders must expose every summary key the JS reads."""
        from verenigingen.utils.admin_utilities.mandate_sync_utility import MandateSyncUtility

        utility = MandateSyncUtility()
        report = utility._generate_report(dry_run=True)

        self.assertIn("summary", report)
        self.assertEqual(set(report["summary"].keys()), JS_SUMMARY_KEYS)
        # Fresh run -> every bucket zero.
        self.assertTrue(all(v == 0 for v in report["summary"].values()))
        self.assertTrue(report["dry_run"])

    def test_process_member_with_existing_mandate_skips_mollie(self):
        """A member that already has mollie_mandate_id must be bucketed as
        already_set WITHOUT any Mollie API call (deterministic, no SDK)."""
        from verenigingen.utils.admin_utilities.mandate_sync_utility import MandateSyncUtility

        utility = MandateSyncUtility()
        member = frappe._dict(
            name="MEMBER-TEST",
            full_name="Test Member",
            mollie_customer_id="cst_test",
            mollie_mandate_id="mdt_existing",
        )
        utility._process_member(member, dry_run=True)

        self.assertEqual(len(utility.results["already_set"]), 1)
        self.assertEqual(utility.results["already_set"][0]["mandate_id"], "mdt_existing")
        # No other bucket touched, and crucially no error from a missing SDK call.
        self.assertEqual(len(utility.results["updated"]), 0)
        self.assertEqual(len(utility.results["errors"]), 0)
