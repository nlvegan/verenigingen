# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen Contributors
# See license.txt

"""Regression tests for the Mandate Sync utility.

This utility was deleted in commit 51705976 ("remove 87 orphaned utils") even
though it was NOT orphaned -- the "Sync mandates" button on the
verenigingen/www/mollie_member_reconciliation.html page calls it. These tests guard the JS
button contract (the dotted method path must resolve to a whitelisted function
returning a report with a `summary` block) and the core no-Mollie-call paths.
"""

from types import SimpleNamespace

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

    # --- core mandate-fetch logic, with a faked Mollie SDK (external seam) -----

    @staticmethod
    def _utility_with_mandates(mandate_statuses, *, sdk_available=True):
        """Build a MandateSyncUtility whose Mollie client is faked to return one
        customer with mandates of the given statuses. Faking the external Mollie
        SDK is the legitimate boundary -- no business logic is mocked."""
        from verenigingen.utils.admin_utilities.mandate_sync_utility import MandateSyncUtility

        mandates = [
            SimpleNamespace(
                id=f"mdt_{i}",
                status=status,
                method="directdebit",
                created_at="2026-01-01",
                signature_date="2026-01-01",
            )
            for i, status in enumerate(mandate_statuses)
        ]
        customer = SimpleNamespace(mandates=SimpleNamespace(list=lambda: list(mandates)))
        sdk = SimpleNamespace(customers=SimpleNamespace(get=lambda _cid: customer)) if sdk_available else None

        utility = MandateSyncUtility()
        utility.client = SimpleNamespace(sdk_client=sdk)
        return utility

    @staticmethod
    def _member(**overrides):
        base = dict(
            name="MEMBER-X",
            full_name="Test Member",
            mollie_customer_id="cst_x",
            mollie_mandate_id=None,
        )
        base.update(overrides)
        return frappe._dict(base)

    def test_single_valid_mandate_buckets_updated(self):
        utility = self._utility_with_mandates(["valid"])
        utility._process_member(self._member(), dry_run=True)
        self.assertEqual(len(utility.results["updated"]), 1)
        self.assertEqual(utility.results["updated"][0]["mandate_id"], "mdt_0")
        self.assertEqual(len(utility.results["errors"]), 0)

    def test_no_mandates_buckets_no_mandates(self):
        utility = self._utility_with_mandates([])
        utility._process_member(self._member(), dry_run=True)
        self.assertEqual(len(utility.results["no_mandates"]), 1)
        self.assertEqual(len(utility.results["updated"]), 0)

    def test_multiple_valid_mandates_need_manual_review(self):
        utility = self._utility_with_mandates(["valid", "valid"])
        utility._process_member(self._member(), dry_run=True)
        self.assertEqual(len(utility.results["multiple_mandates"]), 1)
        self.assertEqual(len(utility.results["updated"]), 0)

    def test_only_invalid_mandates_buckets_invalid(self):
        utility = self._utility_with_mandates(["invalid", "revoked"])
        utility._process_member(self._member(), dry_run=True)
        self.assertEqual(len(utility.results["invalid_mandates"]), 1)
        self.assertEqual(len(utility.results["updated"]), 0)

    def test_single_pending_mandate_is_used(self):
        """No valid mandate but one pending -> fall back to pending, bucket updated."""
        utility = self._utility_with_mandates(["pending"])
        utility._process_member(self._member(), dry_run=True)
        self.assertEqual(len(utility.results["updated"]), 1)
        self.assertEqual(utility.results["updated"][0]["mandate_id"], "mdt_0")
        self.assertEqual(len(utility.results["multiple_mandates"]), 0)

    def test_valid_is_preferred_over_pending(self):
        """With one valid + one pending, prefer the valid one -- and do NOT trip the
        >1 manual-review branch (preferred_mandates is the valid-only list)."""
        utility = self._utility_with_mandates(["valid", "pending"])
        utility._process_member(self._member(), dry_run=True)
        self.assertEqual(len(utility.results["updated"]), 1)
        self.assertEqual(utility.results["updated"][0]["mandate_id"], "mdt_0")  # the valid one
        self.assertEqual(len(utility.results["multiple_mandates"]), 0)

    def test_sdk_unavailable_buckets_error(self):
        # The error branch deliberately logs via frappe.log_error; mark it expected
        # so this test stays green under VERENIGINGEN_FAIL_ON_ERROR_LOG=1.
        self.expectErrorLog("Mandate Sync Error")
        utility = self._utility_with_mandates(["valid"], sdk_available=False)
        utility._process_member(self._member(), dry_run=True)
        self.assertEqual(len(utility.results["errors"]), 1)
        self.assertEqual(len(utility.results["updated"]), 0)

    def test_live_run_persists_mandate_id_on_member(self):
        """dry_run=False must actually write mollie_mandate_id onto the Member."""
        member = self.create_test_member(
            first_name="Mandate",
            last_name="SyncLive",
            email=f"mandate.sync.{frappe.generate_hash(length=6)}@example.com",
            mollie_customer_id="cst_live",
        )
        # Ensure the field starts empty so the assertion is meaningful.
        frappe.db.set_value("Member", member.name, "mollie_mandate_id", None)

        utility = self._utility_with_mandates(["valid"])
        utility._process_member(
            self._member(name=member.name, mollie_customer_id="cst_live"), dry_run=False
        )

        self.assertEqual(len(utility.results["updated"]), 1)
        self.assertEqual(
            frappe.db.get_value("Member", member.name, "mollie_mandate_id"), "mdt_0"
        )
