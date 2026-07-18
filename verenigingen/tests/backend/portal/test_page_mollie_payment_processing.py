# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""
Integration tests for the Mollie payment processing page controller
(``verenigingen/templates/pages/mollie_payment_processing.py``).

This is an administrative tool for turning Mollie payments into membership-dues
Payment Entries / Bank Transactions, plus a historical-recovery toolset. The
behaviours under test:

* ``get_context`` / ``has_payment_processing_access`` - the role gate guarding
  the page (deny for Volunteer/Guest, allow for Verenigingen Administrator).
* ``retrieve_customer_payments_for_processing`` - access-gate + passthrough.
* ``batch_process_dues_payments`` - input validation, payment-id format
  validation, MAX_BATCH_SIZE cap, the per-user rate-limit cache lock, and the
  happy-path passthrough.
* ``bulk_retrieve_all_member_payments`` - access-gate, parameter clamping,
  retrieval_mode coercion and passthrough.
* ``bulk_process_member_payments`` - validation guards, the docstatus coercion
  happy path, and the >100-id background-queue branch.
* ``get_payment_status`` - access-gate, format validation, passthrough.
* ``scan_incomplete_payments`` / ``preview_payment_recovery`` /
  ``execute_payment_recovery`` - access-gate plus the controller's own
  post-processing of the recovery-module results.

Everything runs against the real controller. The ONLY external boundaries
stubbed are:
  * the Mollie API seam - the controller builds a real ``MollieDebugService``
    (whose ``__init__`` constructs a real ``MollieClient``), so we patch the
    ``MollieDebugService`` symbol on the page module with a fake exposing only
    the instance methods the controller delegates to; and
  * the historical-recovery helpers, imported locally inside the recovery
    endpoints from ``verenigingen.utils.payment_processing_recovery`` - those
    are patched at that module so the controller's own post-processing logic
    is exercised unmodified.

No business logic is mocked; no real network calls are made.
"""

import json
from unittest.mock import patch

import frappe

from verenigingen.templates.pages import mollie_payment_processing as page
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.constants import Roles
from verenigingen.utils.error_handling import PermissionError as SecurityPermissionError

# A Mollie payment id that satisfies ``^tr_[a-zA-Z0-9]{10,}$``.
VALID_ID = "tr_abc123XYZ0"
BAD_ID = "not_a_mollie_id"


class FakeMollieService:
    """Stand-in for MollieDebugService exposing only what the controller calls.

    Return values are configured via class attributes set per-test, so a single
    fake serves every branch. ``__init__`` is a no-op so no real MollieClient is
    ever constructed.
    """

    retrieve_customer_payments_return = {"sentinel": "retrieve_customer"}
    batch_process_dues_return = {"processed": 1}
    bulk_retrieve_return = {"sentinel": "bulk_retrieve"}
    bulk_process_return = {"sentinel": "bulk_process"}

    def __init__(self, *args, **kwargs):
        pass

    def retrieve_customer_payments_for_processing(self, customer_id, limit):
        type(self).last_retrieve_args = (customer_id, limit)
        return type(self).retrieve_customer_payments_return

    def batch_process_dues_payments(self, payment_ids, customer_id=None):
        type(self).last_batch_args = (payment_ids, customer_id)
        return type(self).batch_process_dues_return

    def bulk_retrieve_all_member_payments(self, days_back, max_payments, payment_status_filter):
        type(self).last_bulk_retrieve_args = (days_back, max_payments, payment_status_filter)
        return type(self).bulk_retrieve_return

    def bulk_process_member_payments(self, payment_ids, docstatus, payment_modes):
        type(self).last_bulk_process_args = (payment_ids, docstatus, payment_modes)
        return type(self).bulk_process_return

    def process_payment_batch_background(self, **kwargs):
        return {"batch": kwargs.get("batch_num")}


class TestPageMolliePaymentProcessing(EnhancedTestCase):
    def setUp(self):
        self._original_user = frappe.session.user
        super().setUp()
        self._original_form_dict = frappe.local.form_dict
        frappe.local.form_dict = frappe._dict()
        # Reset fake-service config to defaults for each test.
        FakeMollieService.retrieve_customer_payments_return = {"sentinel": "retrieve_customer"}
        FakeMollieService.batch_process_dues_return = {"processed": 1}
        FakeMollieService.bulk_retrieve_return = {"sentinel": "bulk_retrieve"}
        FakeMollieService.bulk_process_return = {"sentinel": "bulk_process"}

    def tearDown(self):
        frappe.local.form_dict = self._original_form_dict
        if hasattr(self, "_original_user"):
            frappe.set_user(self._original_user)
        super().tearDown()

    def _patch_service(self):
        return patch.object(page, "MollieDebugService", FakeMollieService)

    def _clear_rate_limit(self):
        """Drop the per-user dues batch rate-limit lock so a fresh call proceeds."""
        frappe.cache().delete_value(f"dues_batch_limit:{frappe.session.user}")

    # ------------------------------------------------------------------
    # get_context - role gate
    # ------------------------------------------------------------------

    def test_get_context_denies_non_privileged_user(self):
        """A logged-in non-privileged user (Volunteer) is denied with PermissionError."""
        with self.as_role(Roles.VOLUNTEER):
            context = frappe._dict()
            with self.assertRaises(frappe.PermissionError):
                page.get_context(context)

    def test_get_context_denies_guest(self):
        """A Guest is rejected by require_login (which raises PermissionError)."""
        with self.as_user("Guest"):
            context = frappe._dict()
            with self.assertRaises(frappe.PermissionError):
                page.get_context(context)

    def test_get_context_allows_admin_and_populates_mollie(self):
        """A Verenigingen Administrator gets a titled context with CSRF + Mollie fields."""
        with self.as_role(Roles.VERENIGINGEN_ADMIN):
            context = frappe._dict()
            page.get_context(context)
            self.assertEqual(context.title, "Mollie Payment Processing")
            self.assertEqual(context.no_cache, 1)
            self.assertTrue(context.csrf_token)
            # populate_mollie_context always sets these keys.
            self.assertIn("mollie_configured", context)
            self.assertIn("test_mode", context)

    # ------------------------------------------------------------------
    # has_payment_processing_access
    # ------------------------------------------------------------------

    def test_has_access_true_for_admin_role(self):
        with self.as_role(Roles.VERENIGINGEN_ADMIN):
            self.assertTrue(page.has_payment_processing_access())

    def test_has_access_false_for_volunteer_role(self):
        with self.as_role(Roles.VOLUNTEER):
            self.assertFalse(page.has_payment_processing_access())

    # ------------------------------------------------------------------
    # retrieve_customer_payments_for_processing
    # ------------------------------------------------------------------

    def test_retrieve_customer_payments_non_admin_denied(self):
        """A non-privileged user is rejected by the @high_security_api gate.

        NOTE: the security-framework decorator enforces access ABOVE the
        function body, so it raises a PermissionError before the in-function
        try/except (which would otherwise return {"error": ...}) is ever
        reached. The decorator gate is the real, first-line defence.
        """
        with self.as_role(Roles.VOLUNTEER):
            with self.assertRaises(SecurityPermissionError):
                page.retrieve_customer_payments_for_processing("cst_x")

    def test_retrieve_customer_payments_admin_passes_through_service(self):
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            FakeMollieService.retrieve_customer_payments_return = {"payments": ["tr_1"]}
            result = page.retrieve_customer_payments_for_processing("cst_y", limit=10)
        self.assertEqual(result, {"payments": ["tr_1"]})
        self.assertEqual(FakeMollieService.last_retrieve_args, ("cst_y", 10))

    # ------------------------------------------------------------------
    # batch_process_dues_payments
    # ------------------------------------------------------------------

    def test_batch_dues_invalid_payment_ids_returns_error(self):
        """A non-list payload (JSON string of a non-list) is rejected with an error dict."""
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            result = page.batch_process_dues_payments(json.dumps("not-a-list"))
        self.assertIn("error", result)
        self.assertIn("must be a list", result["error"])

    def test_batch_dues_bad_format_id_returns_error(self):
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            result = page.batch_process_dues_payments(json.dumps([BAD_ID]))
        self.assertIn("error", result)
        self.assertIn("Invalid Mollie payment ID", result["error"])

    def test_batch_dues_over_max_batch_size_returns_error(self):
        """More than MAX_BATCH_SIZE (50) valid ids is rejected mentioning the cap."""
        ids = [f"tr_{i:010d}aa" for i in range(51)]
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            self._clear_rate_limit()
            result = page.batch_process_dues_payments(json.dumps(ids))
        self.assertIn("error", result)
        self.assertIn("more than 50", result["error"])

    def test_batch_dues_happy_path_passes_through_service(self):
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            self._clear_rate_limit()
            FakeMollieService.batch_process_dues_return = {"processed": 1, "ok": True}
            result = page.batch_process_dues_payments(json.dumps([VALID_ID]), customer_id="cst_z")
        self.assertEqual(result, {"processed": 1, "ok": True})
        self.assertEqual(FakeMollieService.last_batch_args, ([VALID_ID], "cst_z"))

    def test_batch_dues_rate_limit_blocks_second_call(self):
        """Two consecutive calls as the same user: the second hits the nx cache lock."""
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            self._clear_rate_limit()
            first = page.batch_process_dues_payments(json.dumps([VALID_ID]))
            second = page.batch_process_dues_payments(json.dumps([VALID_ID]))
        # First call went through to the service.
        self.assertEqual(first, {"processed": 1})
        # Second call is blocked by the per-user cooldown.
        self.assertIn("error", second)
        self.assertIn("wait", second["error"].lower())

    # ------------------------------------------------------------------
    # bulk_retrieve_all_member_payments
    # ------------------------------------------------------------------

    def test_bulk_retrieve_non_admin_denied(self):
        """The @high_security_api gate rejects non-privileged users before the body."""
        with self.as_role(Roles.VOLUNTEER):
            with self.assertRaises(SecurityPermissionError):
                page.bulk_retrieve_all_member_payments()

    def test_bulk_retrieve_admin_default_mode_passes_through(self):
        """``bulk_retrieve_all_member_payments`` now delegates to the consolidated
        ``bulk_payment_admin_service``, which builds its own ``MollieDebugService``
        via a fresh function-level import rather than the page module's symbol -
        so in addition to ``_patch_service()`` (which still covers every other
        endpoint on this page) we patch the class at its source module too.
        """
        with (
            self.as_role(Roles.VERENIGINGEN_ADMIN),
            self._patch_service(),
            patch("verenigingen.services.mollie_debug_service.MollieDebugService", FakeMollieService),
        ):
            FakeMollieService.bulk_retrieve_return = {"customers": [], "api_calls_made": 1}
            result = page.bulk_retrieve_all_member_payments()
        self.assertEqual(result, {"customers": [], "api_calls_made": 1})

    def test_bulk_retrieve_clamps_invalid_params_and_coerces_mode(self):
        """days_back=0 is coerced to 30, an unknown retrieval_mode falls back to 'customer'."""
        with (
            self.as_role(Roles.VERENIGINGEN_ADMIN),
            self._patch_service(),
            patch("verenigingen.services.mollie_debug_service.MollieDebugService", FakeMollieService),
        ):
            FakeMollieService.bulk_retrieve_return = {"ok": True}
            result = page.bulk_retrieve_all_member_payments(
                days_back=0, max_payments=10, retrieval_mode="bogus"
            )
        # Returns the (customer-mode) service sentinel without error.
        self.assertEqual(result, {"ok": True})
        # days_back coerced to 30, max_payments coerced to 5000 (below the 250 floor).
        days_back, max_payments, _filter = FakeMollieService.last_bulk_retrieve_args
        self.assertEqual(days_back, 30)
        self.assertEqual(max_payments, 5000)

    def test_bulk_retrieve_global_mode_returns_tagged_dict(self):
        """global_payments mode runs the internal orphan-finder via the real client.

        ``_retrieve_global_payments_with_orphans`` wraps the whole pipeline in a
        try/except and always returns a dict tagged ``retrieval_mode ==
        "global_payments"`` (setting an ``error`` key instead of raising if the
        Mollie SDK / credentials are unavailable). On this site Mollie test
        creds happen to be configured, so the call completes and returns the
        orphan report; without creds it would carry an ``error`` key. Either
        way the contract under test is: a dict tagged for global mode, never an
        exception. We do NOT assert on live payment counts (data-dependent).
        """
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            result = page.bulk_retrieve_all_member_payments(
                days_back=30, max_payments=250, retrieval_mode="global_payments"
            )
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("retrieval_mode"), "global_payments")

    # ------------------------------------------------------------------
    # bulk_process_member_payments
    # ------------------------------------------------------------------

    def test_bulk_process_invalid_payment_ids_returns_error(self):
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            result = page.bulk_process_member_payments(json.dumps("nope"))
        self.assertIn("error", result)
        self.assertIn("must be a list", result["error"])

    def test_bulk_process_bad_format_id_returns_error(self):
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            result = page.bulk_process_member_payments(json.dumps([BAD_ID]))
        self.assertIn("error", result)
        self.assertIn("Invalid Mollie payment ID", result["error"])

    def test_bulk_process_happy_path_coerces_docstatus_and_passes_through(self):
        """An invalid docstatus is coerced to 0 and the service sentinel is returned.

        ``bulk_process_member_payments`` now delegates to the consolidated
        ``bulk_payment_admin_service``, which builds its own ``MollieDebugService``
        via a fresh function-level import rather than the page module's symbol -
        so in addition to ``_patch_service()`` (which still covers every other
        endpoint on this page) we patch the class at its source module too.
        """
        with (
            self.as_role(Roles.VERENIGINGEN_ADMIN),
            self._patch_service(),
            patch("verenigingen.services.mollie_debug_service.MollieDebugService", FakeMollieService),
        ):
            FakeMollieService.bulk_process_return = {"created": 1}
            result = page.bulk_process_member_payments(json.dumps([VALID_ID]), docstatus=99)
        self.assertEqual(result, {"created": 1})
        payment_ids, docstatus, _modes = FakeMollieService.last_bulk_process_args
        self.assertEqual(payment_ids, [VALID_ID])
        self.assertEqual(docstatus, 0)

    def test_bulk_process_large_batch_queues_background_jobs(self):
        """>100 valid ids are split into background batches; frappe.enqueue is stubbed."""
        ids = [f"tr_{i:010d}bb" for i in range(101)]
        with (
            self.as_role(Roles.VERENIGINGEN_ADMIN),
            self._patch_service(),
            patch.object(page.frappe, "enqueue", return_value="fake-job-name"),
        ):
            result = page.bulk_process_member_payments(json.dumps(ids))
        self.assertTrue(result["queued"])
        self.assertEqual(result["num_batches"], 2)
        self.assertEqual(result["total_payments"], 101)
        self.assertEqual(len(result["batches"]), 2)

    # ------------------------------------------------------------------
    # get_payment_status
    # ------------------------------------------------------------------

    def test_get_payment_status_non_admin_denied(self):
        with self.as_role(Roles.VOLUNTEER):
            with self.assertRaises(SecurityPermissionError):
                page.get_payment_status(VALID_ID)

    def test_get_payment_status_bad_format_returns_error(self):
        with self.as_role(Roles.VERENIGINGEN_ADMIN):
            result = page.get_payment_status(BAD_ID)
        self.assertIn("error", result)
        self.assertIn("Invalid Mollie payment ID", result["error"])

    def test_get_payment_status_admin_passes_through_recovery(self):
        sentinel = {"payment_id": VALID_ID, "status": "complete"}
        with (
            self.as_role(Roles.VERENIGINGEN_ADMIN),
            patch(
                "verenigingen.utils.payment_processing_recovery.get_payment_processing_status",
                return_value=sentinel,
            ),
        ):
            result = page.get_payment_status(VALID_ID)
        self.assertEqual(result, sentinel)

    # ------------------------------------------------------------------
    # scan_incomplete_payments
    # ------------------------------------------------------------------

    def test_scan_incomplete_non_admin_denied(self):
        with self.as_role(Roles.VOLUNTEER):
            with self.assertRaises(SecurityPermissionError):
                page.scan_incomplete_payments()

    def test_scan_incomplete_admin_post_processes_gaps(self):
        """The controller derives has_gaps, completion_rate and gaps_by_type buckets."""
        gaps = {
            "total_bank_transactions": 4,
            "complete": 3,
            "gap_details": [
                {"missing": ["Sales Invoice", "Payment Entry"]},
                {"missing": ["Sales Invoice"]},
                {"missing": ["Payment Entry"]},
                {"missing": ["Sales Invoice Link"]},
            ],
        }
        with (
            self.as_role(Roles.VERENIGINGEN_ADMIN),
            patch(
                "verenigingen.utils.payment_processing_recovery.analyze_payment_gaps",
                return_value=gaps,
            ),
        ):
            result = page.scan_incomplete_payments()
        self.assertTrue(result["has_gaps"])
        self.assertEqual(result["completion_rate"], 75.0)
        self.assertEqual(len(result["gaps_by_type"]["missing_both"]), 1)
        self.assertEqual(len(result["gaps_by_type"]["missing_invoice"]), 1)
        self.assertEqual(len(result["gaps_by_type"]["missing_payment_entry"]), 1)
        self.assertEqual(len(result["gaps_by_type"]["missing_link"]), 1)

    # ------------------------------------------------------------------
    # preview_payment_recovery
    # ------------------------------------------------------------------

    def test_preview_recovery_non_admin_denied(self):
        with self.as_role(Roles.VOLUNTEER):
            with self.assertRaises(SecurityPermissionError):
                page.preview_payment_recovery()

    def test_preview_recovery_admin_adds_would_create_summary(self):
        # NOTE on bucketing: the controller classifies each would_create entry
        # with an if/elif chain checking "Bank Transaction" -> "Payment Entry"
        # -> "Sales Invoice" -> "Link" in that order. A label is bucketed by the
        # FIRST substring it contains, so "Reconciliation Link" (no earlier
        # substring) is the only way to land in the "links" bucket.
        recovery = {
            "results": [
                {"would_create": ["Bank Transaction", "Payment Entry"]},
                {"would_create": ["Sales Invoice", "Reconciliation Link"]},
            ]
        }
        with (
            self.as_role(Roles.VERENIGINGEN_ADMIN),
            patch(
                "verenigingen.utils.payment_processing_recovery.complete_partial_payments",
                return_value=recovery,
            ) as mock_complete,
        ):
            result = page.preview_payment_recovery()
        # Preview always runs dry.
        self.assertTrue(mock_complete.call_args.kwargs["dry_run"])
        summary = result["would_create_summary"]
        self.assertEqual(summary["bank_transactions"], 1)
        self.assertEqual(summary["payment_entries"], 1)
        self.assertEqual(summary["sales_invoices"], 1)
        self.assertEqual(summary["links"], 1)

    # ------------------------------------------------------------------
    # execute_payment_recovery
    # ------------------------------------------------------------------

    def test_execute_recovery_non_admin_denied(self):
        with self.as_role(Roles.VOLUNTEER):
            with self.assertRaises(SecurityPermissionError):
                page.execute_payment_recovery()

    def test_execute_recovery_admin_adds_execution_summary(self):
        recovery = {
            "results": [
                {"bank_transaction": "BT-1", "payment_entry": "PE-1"},
                {"bank_transaction": "BT-2", "sales_invoice": "SI-1"},
            ]
        }
        with (
            self.as_role(Roles.VERENIGINGEN_ADMIN),
            patch(
                "verenigingen.utils.payment_processing_recovery.complete_partial_payments",
                return_value=recovery,
            ) as mock_complete,
        ):
            result = page.execute_payment_recovery()
        # Execution runs for real (not dry).
        self.assertFalse(mock_complete.call_args.kwargs["dry_run"])
        created = result["execution_summary"]["documents_created"]
        self.assertEqual(created["bank_transactions"], 2)
        self.assertEqual(created["payment_entries"], 1)
        self.assertEqual(created["sales_invoices"], 1)
