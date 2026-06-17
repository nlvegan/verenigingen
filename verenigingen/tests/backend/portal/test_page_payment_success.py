# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""
Integration tests for the payment success / return page controller
(``verenigingen/templates/pages/payment_success.py``).

This is the page users land on when returning from an external payment
provider (Mollie, Pay.nl/ING Checkout, Ponto). The most important behaviour
under test is ``validate_payment_document_access`` - the IDOR guard that
prevents arbitrary documents from being read via the public status page.

Everything runs against real ORM documents created via the factory. The only
external boundaries stubbed are the Mollie payment-status gateway (no live
creds on CI) and the Pay.nl status API, both of which are stubbed at the
import seam, never the page's own business logic.
"""

from unittest.mock import patch

import frappe

from verenigingen.templates.pages import payment_success
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPagePaymentSuccess(EnhancedTestCase):
    def setUp(self):
        self._original_user = frappe.session.user
        super().setUp()
        self._original_form_dict = frappe.local.form_dict
        frappe.local.form_dict = frappe._dict()

    def tearDown(self):
        frappe.local.form_dict = self._original_form_dict
        if hasattr(self, "_original_user"):
            frappe.set_user(self._original_user)
        super().tearDown()

    def _make_donation(self, **kwargs):
        donation = self.create_test_donation(**kwargs)
        self.track_doc("Donation", donation.name)
        return donation

    # ------------------------------------------------------------------
    # validate_payment_document_access - the IDOR guard
    # ------------------------------------------------------------------

    def test_validate_rejects_doctype_not_in_whitelist(self):
        """A doctype outside ALLOWED_PAYMENT_DOCTYPES is rejected before any DB hit."""
        is_valid, result = payment_success.validate_payment_document_access("User", "Administrator", "tr_x")
        self.assertFalse(is_valid)
        # result is an error message string, not a doc.
        self.assertIsInstance(result, str)

    def test_validate_rejects_missing_document(self):
        """An allowed doctype with a non-existent docname returns 'not found'."""
        is_valid, result = payment_success.validate_payment_document_access(
            "Donation", "Donation-DOES-NOT-EXIST-XYZ", None
        )
        self.assertFalse(is_valid)
        self.assertIsInstance(result, str)

    def test_validate_accepts_when_no_payment_id_required(self):
        """A real, allowed document with no payment_id check passes and returns the doc."""
        donation = self._make_donation()
        is_valid, result = payment_success.validate_payment_document_access("Donation", donation.name, None)
        self.assertTrue(is_valid)
        self.assertEqual(result.name, donation.name)

    def test_validate_payment_id_mismatch_is_rejected(self):
        """A wrong payment_id for an existing document is rejected (IDOR / reference forgery)."""
        donation = self._make_donation(payment_id="tr_correct_id")
        is_valid, result = payment_success.validate_payment_document_access(
            "Donation", donation.name, "tr_WRONG_id"
        )
        self.assertFalse(is_valid)
        self.assertIsInstance(result, str)

    def test_validate_payment_id_match_passes(self):
        """A matching payment_id resolves to the real document."""
        donation = self._make_donation(payment_id="tr_match_me")
        is_valid, result = payment_success.validate_payment_document_access(
            "Donation", donation.name, "tr_match_me"
        )
        self.assertTrue(is_valid)
        self.assertEqual(result.name, donation.name)

    def test_validate_payment_id_required_but_doc_has_none(self):
        """If a payment_id is supplied but the doc carries none, access is denied."""
        donation = self._make_donation()  # no payment_id
        is_valid, result = payment_success.validate_payment_document_access(
            "Donation", donation.name, "tr_some_id"
        )
        self.assertFalse(is_valid)

    # ------------------------------------------------------------------
    # get_context - Mollie-style doctype/docname/payment_id flow
    # ------------------------------------------------------------------

    def test_get_context_no_params_shows_invalid_reference(self):
        """With no recognised params, the page reports an invalid reference message."""
        frappe.local.form_dict = frappe._dict()
        context = frappe._dict()
        payment_success.get_context(context)
        self.assertEqual(context.payment_status, "unknown")
        self.assertIn("Invalid payment reference", context.payment_message)

    def test_get_context_disallowed_doctype_is_error(self):
        """A disallowed doctype passed via form_dict surfaces an error status, not the doc."""
        frappe.local.form_dict = frappe._dict({"doctype": "User", "docname": "Administrator"})
        context = frappe._dict()
        payment_success.get_context(context)
        self.assertEqual(context.payment_status, "error")
        # No document info leaked.
        self.assertEqual(context.document_info, {})

    def test_get_context_paid_document_reports_completed(self):
        """An already-paid document (no payment_id) is reported as completed with next steps."""
        donation = self._make_donation(paid=1)
        frappe.local.form_dict = frappe._dict({"doctype": "Donation", "docname": donation.name})
        context = frappe._dict()
        payment_success.get_context(context)
        self.assertEqual(context.payment_status, "completed")
        self.assertEqual(context.document_info["docname"], donation.name)
        self.assertTrue(len(context.next_steps) > 0)

    def test_get_context_payment_id_non_mollie_reports_unknown(self):
        """A validated payment_id on a non-Mollie document yields the 'unknown' fallback.

        Donations carry no ``payment_method`` field, so check_payment_status takes
        its non-Mollie branch and reports that automatic status checks are not
        possible for this method - the real, reachable behaviour for the allowed
        doctypes on this site.
        """
        donation = self._make_donation(paid=0, payment_id="tr_ctx_check")
        frappe.local.form_dict = frappe._dict(
            {
                "doctype": "Donation",
                "docname": donation.name,
                "payment_id": "tr_ctx_check",
            }
        )
        context = frappe._dict()
        payment_success.get_context(context)

        self.assertEqual(context.payment_status, "unknown")
        self.assertEqual(context.document_info["docname"], donation.name)

    def test_check_payment_status_non_mollie_method(self):
        """check_payment_status returns 'unknown' for a document with no Mollie method."""
        donation = self._make_donation(payment_id="tr_x")
        result = payment_success.check_payment_status(donation, "tr_x")
        self.assertEqual(result["status"], "unknown")

    # ------------------------------------------------------------------
    # Pay.nl / ING Checkout return branch
    # ------------------------------------------------------------------

    def test_ing_checkout_completed_status(self):
        """Status code 100 from Pay.nl maps to 'completed'."""
        context = frappe._dict()
        with patch(
            "verenigingen.verenigingen_payments.ing_checkout.api.payment.get_payment_status",
            return_value={"success": True, "status_code": 100},
        ):
            payment_success.handle_ing_checkout_return(context, "EX-1234")
        self.assertEqual(context.payment_status, "completed")

    def test_ing_checkout_cancelled_status(self):
        """Status code -90 from Pay.nl maps to 'cancelled'."""
        context = frappe._dict()
        with patch(
            "verenigingen.verenigingen_payments.ing_checkout.api.payment.get_payment_status",
            return_value={"success": True, "status_code": -90},
        ):
            payment_success.handle_ing_checkout_return(context, "EX-1234")
        self.assertEqual(context.payment_status, "cancelled")

    def test_ing_checkout_api_failure_is_error(self):
        """A non-success result from the Pay.nl API surfaces as an error status."""
        context = frappe._dict()
        with patch(
            "verenigingen.verenigingen_payments.ing_checkout.api.payment.get_payment_status",
            return_value={"success": False, "message": "boom"},
        ):
            payment_success.handle_ing_checkout_return(context, "EX-1234")
        self.assertEqual(context.payment_status, "error")
        self.assertEqual(context.payment_message, "boom")

    # ------------------------------------------------------------------
    # Ponto Payment Link return branch
    # ------------------------------------------------------------------

    def test_ponto_link_not_found_is_error(self):
        """A non-existent Ponto Payment Link returns an error status."""
        context = frappe._dict()
        payment_success.handle_ponto_payment_link_return(context, "PONTO-LINK-DOES-NOT-EXIST")
        self.assertEqual(context.payment_status, "error")

    # ------------------------------------------------------------------
    # get_next_steps - pure helper, all branches
    # ------------------------------------------------------------------

    def test_next_steps_completed_donation_includes_receipt(self):
        steps = payment_success.get_next_steps("completed", "Donation", "X")
        titles = [s["title"] for s in steps]
        self.assertIn("Receipt", titles)

    def test_next_steps_failed_offers_retry(self):
        steps = payment_success.get_next_steps("failed", "Donation", "X")
        actions = [s.get("action") for s in steps]
        self.assertIn("/donate", actions)

    def test_next_steps_pending_no_action_links(self):
        steps = payment_success.get_next_steps("pending", "Donation", "X")
        self.assertTrue(all(s.get("action") is None for s in steps))

    # ------------------------------------------------------------------
    # refresh_payment_status API endpoint
    # ------------------------------------------------------------------

    def test_refresh_status_invalid_reference_returns_failure(self):
        """The public refresh endpoint never leaks doc existence on a bad reference."""
        result = payment_success.refresh_payment_status("User", "Administrator", "tr_x")
        self.assertFalse(result["success"])

    def test_refresh_status_valid_document(self):
        """A valid, payment_id-matched document succeeds via the public endpoint.

        With no Mollie payment_method the status resolves to 'unknown', but the
        endpoint still reports success and never leaks beyond the validated doc.
        """
        donation = self._make_donation(payment_id="tr_refresh", paid=0)
        result = payment_success.refresh_payment_status("Donation", donation.name, "tr_refresh")
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["is_paid"], 0)

    def test_refresh_status_payment_id_mismatch_rejected(self):
        """A wrong payment_id is rejected even for a real allowed document."""
        donation = self._make_donation(payment_id="tr_real")
        result = payment_success.refresh_payment_status("Donation", donation.name, "tr_forged")
        self.assertFalse(result["success"])
