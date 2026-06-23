# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""
Supplemental coverage tests for the payment success / return page controller
(``verenigingen/templates/pages/payment_success.py``).

The sibling file ``test_page_payment_success.py`` already covers the IDOR guard
(``validate_payment_document_access``) happy/sad paths, the Mollie-style
``get_context`` flow, and a handful of ``get_next_steps`` branches. This file
fills the remaining gaps with REAL ORM fixtures:

* ``handle_ponto_payment_link_return`` driven by a real (draft) Ponto Payment
  Link record across every status mapping, including the Sales-Invoice branch.
* ``handle_ing_checkout_return`` across the remaining Pay.nl status codes and the
  "linked transaction record" branch (document_info / next_steps), driven by a
  real ING Checkout Transaction row. The Pay.nl *HTTP* status call is stubbed at
  the import seam only - never the page's own mapping logic.
* ``get_context`` routing into the orderId and payment_link branches.
* ``get_next_steps`` branches not exercised elsewhere (completed non-Donation,
  cancelled/expired, the catch-all fallback).
* ``check_payment_status`` Mollie branch (no live creds -> error dict) and the
  ``refresh_payment_status`` API wrapper.

The only external boundary stubbed is the Pay.nl *HTTP* status fetch (no live
creds on CI); the Mollie gateway is intentionally NOT stubbed so the real
"no credentials" error path is exercised end to end.
"""

from unittest.mock import patch

import frappe

from verenigingen.templates.pages import payment_success
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPagePaymentSuccessCoverage(EnhancedTestCase):
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

    # ------------------------------------------------------------------
    # fixtures
    # ------------------------------------------------------------------

    def _make_donation(self, **kwargs):
        donation = self.create_test_donation(**kwargs)
        self.track_doc("Donation", donation.name)
        return donation

    def _make_ponto_link(self, status="Draft", **kwargs):
        """Create a *draft* Ponto Payment Link (no submit -> no Ponto API call)."""
        data = {
            "doctype": "Ponto Payment Link",
            "payment_type": "One-Time",
            "amount": kwargs.get("amount", 25.0),
            "currency": "EUR",
            "description": kwargs.get("description", "Test Ponto payment"),
            "creditor_name": "Test Creditor",
            "creditor_iban": "NL39RABO0300065264",
            "status": status,
        }
        for k in ("reference_doctype", "reference_name", "sales_invoice", "member"):
            if k in kwargs:
                data[k] = kwargs[k]
        link = frappe.get_doc(data)
        link.insert(ignore_permissions=True)
        # validate() does not force a default, but insert may leave status as set.
        if link.status != status:
            frappe.db.set_value("Ponto Payment Link", link.name, "status", status)
        self.track_doc("Ponto Payment Link", link.name)
        return link

    def _make_ing_transaction(self, transaction_id, **kwargs):
        """Create a real ING Checkout Transaction row keyed by transaction_id."""
        data = {
            "doctype": "ING Checkout Transaction",
            "transaction_id": transaction_id,
            "status": kwargs.get("status", "Pending"),
            "amount": kwargs.get("amount", 42.0),
            "currency": "EUR",
        }
        for k in ("reference_doctype", "reference_name"):
            if k in kwargs:
                data[k] = kwargs[k]
        txn = frappe.get_doc(data)
        txn.insert(ignore_permissions=True)
        self.track_doc("ING Checkout Transaction", txn.name)
        return txn

    # ==================================================================
    # validate_payment_document_access - remaining branches
    # ==================================================================

    def test_validate_member_application_missing_doc_not_found(self):
        """A second allowed doctype ('Sales Invoice') with a missing doc -> not found.

        Exercises the whitelist-accepted-but-absent branch for a doctype other
        than Donation (no Error Log: this is the 'document not found' path, not a
        security-rejection path).
        """
        with self.assertNoErrorLog():
            is_valid, result = payment_success.validate_payment_document_access(
                "Sales Invoice", "ACC-SINV-DOES-NOT-EXIST-XYZ", None
            )
        self.assertFalse(is_valid)
        self.assertIsInstance(result, str)

    def test_validate_disallowed_doctype_logs_security_event(self):
        """A disallowed doctype is rejected AND writes a security Error Log."""
        self.expectErrorLog("Payment Status Security")
        is_valid, result = payment_success.validate_payment_document_access("ToDo", "anything", "tr_x")
        self.assertFalse(is_valid)
        self.assertIsInstance(result, str)

    def test_validate_payment_id_mismatch_logs_security_event(self):
        """A forged payment_id is rejected AND writes a security Error Log."""
        donation = self._make_donation(payment_id="tr_real_id")
        self.expectErrorLog("Payment Status Security")
        is_valid, result = payment_success.validate_payment_document_access(
            "Donation", donation.name, "tr_forged_id"
        )
        self.assertFalse(is_valid)
        self.assertIsInstance(result, str)

    def test_validate_matching_payment_id_returns_doc(self):
        """A matching payment_id resolves to the real document object."""
        donation = self._make_donation(payment_id="tr_exact")
        with self.assertNoErrorLog():
            is_valid, result = payment_success.validate_payment_document_access(
                "Donation", donation.name, "tr_exact"
            )
        self.assertTrue(is_valid)
        self.assertEqual(result.name, donation.name)

    # ==================================================================
    # handle_ponto_payment_link_return - real records, all status mappings
    # ==================================================================

    def test_ponto_executed_is_completed(self):
        link = self._make_ponto_link(status="Executed")
        context = frappe._dict()
        with self.assertNoErrorLog():
            payment_success.handle_ponto_payment_link_return(context, link.name)
        self.assertEqual(context.payment_status, "completed")
        self.assertTrue(context.document_info["paid"])
        self.assertEqual(context.document_info["docname"], link.name)

    def test_ponto_pending_authorization_is_pending(self):
        link = self._make_ponto_link(status="Pending Authorization")
        context = frappe._dict()
        with self.assertNoErrorLog():
            payment_success.handle_ponto_payment_link_return(context, link.name)
        self.assertEqual(context.payment_status, "pending")
        self.assertFalse(context.document_info["paid"])

    def test_ponto_authorized_is_pending(self):
        link = self._make_ponto_link(status="Authorized")
        context = frappe._dict()
        with self.assertNoErrorLog():
            payment_success.handle_ponto_payment_link_return(context, link.name)
        self.assertEqual(context.payment_status, "pending")

    def test_ponto_cancelled_is_cancelled(self):
        link = self._make_ponto_link(status="Cancelled")
        context = frappe._dict()
        with self.assertNoErrorLog():
            payment_success.handle_ponto_payment_link_return(context, link.name)
        self.assertEqual(context.payment_status, "cancelled")

    def test_ponto_rejected_is_failed(self):
        link = self._make_ponto_link(status="Rejected")
        context = frappe._dict()
        with self.assertNoErrorLog():
            payment_success.handle_ponto_payment_link_return(context, link.name)
        self.assertEqual(context.payment_status, "failed")

    def test_ponto_expired_is_expired(self):
        link = self._make_ponto_link(status="Expired")
        context = frappe._dict()
        with self.assertNoErrorLog():
            payment_success.handle_ponto_payment_link_return(context, link.name)
        self.assertEqual(context.payment_status, "expired")

    def test_ponto_failed_is_failed(self):
        link = self._make_ponto_link(status="Failed")
        context = frappe._dict()
        with self.assertNoErrorLog():
            payment_success.handle_ponto_payment_link_return(context, link.name)
        self.assertEqual(context.payment_status, "failed")

    def test_ponto_draft_fallback_is_pending(self):
        """The Draft status falls into the catch-all 'pending' bucket."""
        link = self._make_ponto_link(status="Draft")
        context = frappe._dict()
        with self.assertNoErrorLog():
            payment_success.handle_ponto_payment_link_return(context, link.name)
        self.assertEqual(context.payment_status, "pending")

    def test_ponto_uses_description_as_title(self):
        link = self._make_ponto_link(status="Pending Authorization", description="Membership dues 2026")
        context = frappe._dict()
        with self.assertNoErrorLog():
            payment_success.handle_ponto_payment_link_return(context, link.name)
        self.assertEqual(context.document_info["title"], "Membership dues 2026")

    def test_ponto_linked_sales_invoice_overrides_document_info(self):
        """When the link references a Sales Invoice, document_info points at it."""
        member = self.create_test_member(first_name="Ponto", last_name="Invoicee", birth_date="1990-01-01")
        invoice = self.create_test_sales_invoice(customer=member.name)
        self.track_doc("Sales Invoice", invoice.name)
        link = self._make_ponto_link(status="Executed", sales_invoice=invoice.name)
        context = frappe._dict()
        with self.assertNoErrorLog():
            payment_success.handle_ponto_payment_link_return(context, link.name)
        self.assertEqual(context.document_info["doctype"], "Sales Invoice")
        self.assertEqual(context.document_info["docname"], invoice.name)
        # next_steps were computed for the linked reference, not an empty doc.
        self.assertTrue(len(context.next_steps) > 0)

    def test_ponto_not_found_is_error(self):
        context = frappe._dict()
        with self.assertNoErrorLog():
            payment_success.handle_ponto_payment_link_return(context, "PONTO-LINK-9999-NOPE")
        self.assertEqual(context.payment_status, "error")
        self.assertEqual(context.document_info, {})

    # ==================================================================
    # handle_ing_checkout_return - remaining status codes + linked record
    # ==================================================================

    def _ing(self, order_id, status_code):
        context = frappe._dict()
        with patch(
            "verenigingen.verenigingen_payments.ing_checkout.api.payment.get_payment_status",
            return_value={"success": True, "status_code": status_code},
        ):
            payment_success.handle_ing_checkout_return(context, order_id)
        return context

    def test_ing_pending_status_codes(self):
        for code in (20, 25):
            with self.subTest(code=code), self.assertNoErrorLog():
                context = self._ing("EX-pending", code)
            self.assertEqual(context.payment_status, "pending")

    def test_ing_denied_is_failed(self):
        with self.assertNoErrorLog():
            context = self._ing("EX-denied", -63)
        self.assertEqual(context.payment_status, "failed")

    def test_ing_expired_status(self):
        with self.assertNoErrorLog():
            context = self._ing("EX-expired", -64)
        self.assertEqual(context.payment_status, "expired")

    def test_ing_refunded_is_completed(self):
        """Refunded (-81) is still 'completed' from the user's perspective."""
        with self.assertNoErrorLog():
            context = self._ing("EX-refunded", -81)
        self.assertEqual(context.payment_status, "completed")

    def test_ing_unknown_status_code_is_pending(self):
        with self.assertNoErrorLog():
            context = self._ing("EX-weird", 999)
        self.assertEqual(context.payment_status, "pending")

    def test_ing_no_linked_transaction_uses_generic_info(self):
        """No matching ING Checkout Transaction -> generic 'Payment' document_info."""
        with self.assertNoErrorLog():
            context = self._ing("EX-no-record", 100)
        self.assertEqual(context.payment_status, "completed")
        self.assertEqual(context.document_info["doctype"], "Payment")
        self.assertTrue(context.document_info["paid"])
        self.assertTrue(len(context.next_steps) > 0)

    def test_ing_linked_transaction_exposes_reference(self):
        """A real ING Checkout Transaction surfaces its linked reference + next steps."""
        donation = self._make_donation()
        order_id = "EX-linked-ing"
        self._make_ing_transaction(
            order_id,
            status="Paid",
            amount=33.0,
            reference_doctype="Donation",
            reference_name=donation.name,
        )
        context = frappe._dict()
        with (
            patch(
                "verenigingen.verenigingen_payments.ing_checkout.api.payment.get_payment_status",
                return_value={"success": True, "status_code": 100},
            ),
            self.assertNoErrorLog(),
        ):
            payment_success.handle_ing_checkout_return(context, order_id)

        self.assertEqual(context.payment_status, "completed")
        self.assertEqual(context.document_info["doctype"], "Donation")
        self.assertEqual(context.document_info["docname"], donation.name)
        self.assertTrue(context.document_info["paid"])
        # Donation completed -> next steps include the receipt entry.
        titles = [s["title"] for s in context.next_steps]
        self.assertIn("Receipt", titles)

    def test_ing_api_exception_is_error(self):
        """An exception inside the Pay.nl fetch is caught and surfaced as 'error'."""
        context = frappe._dict()
        self.expectErrorLog("Payment", "network down")
        with patch(
            "verenigingen.verenigingen_payments.ing_checkout.api.payment.get_payment_status",
            side_effect=RuntimeError("network down"),
        ):
            payment_success.handle_ing_checkout_return(context, "EX-boom")
        self.assertEqual(context.payment_status, "error")

    # ==================================================================
    # get_context - routing into the orderId / payment_link branches
    # ==================================================================

    def test_get_context_routes_to_ing_branch(self):
        """An ?orderId param routes get_context into the ING handler."""
        frappe.local.form_dict = frappe._dict({"orderId": "EX-route-ing"})
        context = frappe._dict()
        with (
            patch(
                "verenigingen.verenigingen_payments.ing_checkout.api.payment.get_payment_status",
                return_value={"success": True, "status_code": 100},
            ),
            self.assertNoErrorLog(),
        ):
            payment_success.get_context(context)
        self.assertEqual(context.payment_status, "completed")

    def test_get_context_routes_to_ponto_branch(self):
        """A ?payment_link param routes get_context into the Ponto handler."""
        link = self._make_ponto_link(status="Executed")
        frappe.local.form_dict = frappe._dict({"payment_link": link.name})
        context = frappe._dict()
        with self.assertNoErrorLog():
            payment_success.get_context(context)
        self.assertEqual(context.payment_status, "completed")
        self.assertEqual(context.document_info["docname"], link.name)

    def test_get_context_pending_unpaid_document(self):
        """An unpaid document with no payment_id reports 'pending' with next steps."""
        donation = self._make_donation(paid=0)
        frappe.local.form_dict = frappe._dict({"doctype": "Donation", "docname": donation.name})
        context = frappe._dict()
        with self.assertNoErrorLog():
            payment_success.get_context(context)
        self.assertEqual(context.payment_status, "pending")
        self.assertTrue(len(context.next_steps) > 0)

    # ==================================================================
    # check_payment_status - Mollie branch (no creds -> error dict)
    # ==================================================================

    def test_check_payment_status_mollie_branch_without_credentials(self):
        """A doc flagged Mollie drives the gateway branch and yields an error dict.

        Donation has no payment_method field, so we set it in memory only. This is
        site-coupled: on a Mollie-less site the gateway factory raises and the
        handler's own try/except logs "Payment Status Check"; on a Mollie-configured
        site (e.g. veg11) the gateway resolves but the unknown token "tr_mollie"
        makes Mollie return its own error, logged as "Mollie Status Check". Either
        way the result is a structured error dict (status is "Error"/"error",
        case-insensitive) and the call never raises.
        """
        donation = self._make_donation(payment_id="tr_mollie")
        donation.payment_method = "Mollie"  # in-memory attribute only
        self.expectErrorLog("Mollie Status Check", "Payment Status Check", "Payment Status")
        result = payment_success.check_payment_status(donation, "tr_mollie")
        self.assertEqual(str(result["status"]).lower(), "error")
        self.assertIn("message", result)

    # ==================================================================
    # get_next_steps - branches not covered by the sibling file
    # ==================================================================

    def test_next_steps_completed_non_donation_has_no_receipt(self):
        steps = payment_success.get_next_steps("completed", "Sales Invoice", "X")
        titles = [s["title"] for s in steps]
        self.assertNotIn("Receipt", titles)
        self.assertIn("Thank you!", titles)

    def test_next_steps_cancelled_offers_retry_and_support(self):
        steps = payment_success.get_next_steps("cancelled", "Donation", "X")
        actions = [s.get("action") for s in steps]
        self.assertIn("/donate", actions)
        self.assertTrue(any(str(a).startswith("mailto:") for a in actions))

    def test_next_steps_expired_offers_retry(self):
        steps = payment_success.get_next_steps("expired", "Donation", "X")
        self.assertIn("/donate", [s.get("action") for s in steps])

    def test_next_steps_unknown_status_falls_back_to_support(self):
        steps = payment_success.get_next_steps("unknown", None, None)
        self.assertEqual(len(steps), 1)
        self.assertTrue(str(steps[0]["action"]).startswith("mailto:"))

    # ==================================================================
    # refresh_payment_status - API wrapper
    # ==================================================================

    def test_refresh_status_no_payment_id_succeeds(self):
        """No payment_id required -> the endpoint succeeds and reports paid flag."""
        donation = self._make_donation(paid=1)
        with self.assertNoErrorLog():
            result = payment_success.refresh_payment_status("Donation", donation.name, None)
        self.assertTrue(result["success"])
        self.assertEqual(result["is_paid"], 1)

    def test_refresh_status_disallowed_doctype_logs_and_fails(self):
        """A disallowed doctype is rejected by the API wrapper (and logs)."""
        self.expectErrorLog("Payment Status")
        result = payment_success.refresh_payment_status("ToDo", "anything", "tr_x")
        self.assertFalse(result["success"])
