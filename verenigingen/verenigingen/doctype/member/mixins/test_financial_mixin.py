"""
Tests for verenigingen/verenigingen/doctype/member/mixins/financial_mixin.py

FinancialMixin is mixed into the Member controller. These tests build REAL
Member / Customer / Sales Invoice / SEPA Mandate documents (no business-logic
mocking) and assert the real behaviour of:

- process_payment()        : the payment-method branch table
- get_financial_summary()  : payment-history aggregation + SEPA mandate enrichment
- refresh_financial_data() : orchestration + error aggregation
- mark_as_paid()           : payment-entry creation against outstanding invoices

The mixin is heavily branch-based with broad try/except wrappers, so the focus
is on pinning each *branch*' s observable result (the returned dict shape and the
specific error / success messages a UI / API caller relies on).
"""

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestFinancialMixin(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.membership_type = self.create_test_membership_type(
            membership_type_name="FinMixin Type",
            amount=50.0,
            contribution_mode="Fixed Amount",
        )

    # ------------------------------------------------------------------
    # Helpers (privileged data creation lives here, not in test bodies)
    # ------------------------------------------------------------------
    def _member_with_customer(self, payment_method=None):
        member = self.create_test_member(first_name="Fin", last_name="Mixin")
        self.link_member_to_customer(member)
        if payment_method is not None:
            member.payment_method = payment_method
            # SEPA Direct Debit save-validation requires IBAN + account holder name.
            if payment_method == "SEPA Direct Debit":
                member.iban = "NL13TEST0123456789"
                member.bank_account_name = "Fin Mixin"
            member.save()
            member.reload()
        return member

    # ------------------------------------------------------------------
    # process_payment - branch table
    # ------------------------------------------------------------------
    def test_process_payment_unsaved_member(self):
        """A member object with no name cannot have a payment processed."""
        member = frappe.new_doc("Member")
        result = member.process_payment()
        self.assertFalse(result["success"])
        self.assertIn("must be saved", result["error"])

    def test_process_payment_sepa_without_mandate(self):
        """SEPA payment method with no active mandate is rejected with a clear error."""
        member = self._member_with_customer(payment_method="SEPA Direct Debit")
        # No SEPA mandate created -> has_active_sepa_mandate() is False.
        result = member.process_payment()
        self.assertFalse(result["success"])
        self.assertIn("No active SEPA mandate", result["error"])

    def test_process_payment_sepa_with_mandate_not_implemented(self):
        """SEPA + active mandate reaches the 'not yet implemented' branch.

        Pins that with a valid mandate the code passes the mandate guard and
        reports the batch-processing-not-implemented message (a different error
        than the no-mandate case), proving the guard is mandate-driven.
        """
        member = self._member_with_customer(payment_method="SEPA Direct Debit")
        self.create_test_sepa_mandate(
            member_name=member.name,
            iban="NL13TEST0123456789",
            mandate_id=f"FINMIX-{member.name}",
            status="Active",
            used_for_memberships=1,
        )
        result = member.process_payment()
        self.assertFalse(result["success"])
        self.assertIn("not yet implemented", result["error"])
        self.assertNotIn("No active SEPA mandate", result["error"])

    def test_process_payment_bank_transfer_not_implemented(self):
        member = self._member_with_customer(payment_method="Bank Transfer")
        result = member.process_payment()
        self.assertFalse(result["success"])
        self.assertIn("Bank transfer processing is not yet implemented", result["error"])

    def test_process_payment_unsupported_method(self):
        """An unrecognised payment method falls through to the 'unsupported' branch."""
        member = self._member_with_customer(payment_method="Cash")
        result = member.process_payment()
        self.assertFalse(result["success"])
        self.assertIn("Unsupported payment method", result["error"])
        self.assertIn("Cash", result["error"])

    # ------------------------------------------------------------------
    # get_financial_summary - aggregation
    # ------------------------------------------------------------------
    def test_financial_summary_empty_history(self):
        """With no payment history all counts are zero and totals are 0."""
        member = self._member_with_customer(payment_method="Bank Transfer")
        # Ensure no payment_history rows.
        member.set("payment_history", [])
        summary = member.get_financial_summary()
        self.assertEqual(summary["total_payments"], 0)
        self.assertEqual(summary["total_amount"], 0)
        self.assertEqual(summary["outstanding_amount"], 0)
        self.assertEqual(summary["paid_invoices"], 0)
        self.assertFalse(summary["has_sepa_mandate"])
        self.assertEqual(summary["payment_method"], "Bank Transfer")

    def test_financial_summary_aggregates_history_rows(self):
        """get_financial_summary sums amounts and buckets rows by status/type.

        Builds in-memory payment_history child rows (the same shape the loader
        produces) and asserts the aggregation arithmetic, which is the real
        value this method provides to the UI summary card.
        """
        member = self._member_with_customer(payment_method="Bank Transfer")
        rows = [
            {
                "amount": 50.0,
                "outstanding_amount": 0,
                "payment_status": "Paid",
                "transaction_type": "Membership Invoice",
            },
            {
                "amount": 30.0,
                "outstanding_amount": 30.0,
                "payment_status": "Unpaid",
                "transaction_type": "Regular Invoice",
            },
            {
                "amount": 20.0,
                "outstanding_amount": 20.0,
                "payment_status": "Overdue",
                "transaction_type": "Donation Payment",
            },
        ]
        member.set("payment_history", [])
        for r in rows:
            member.append("payment_history", r)

        summary = member.get_financial_summary()
        self.assertEqual(summary["total_payments"], 3)
        self.assertEqual(summary["total_amount"], 100.0)
        self.assertEqual(summary["outstanding_amount"], 50.0)
        self.assertEqual(summary["paid_invoices"], 1)
        self.assertEqual(summary["overdue_invoices"], 1)
        self.assertEqual(summary["unpaid_invoices"], 1)
        self.assertEqual(summary["membership_invoices"], 1)
        self.assertEqual(summary["regular_invoices"], 1)
        # payment_history is invoice-only now; the summary no longer breaks
        # out a "donations" (or "unreconciled_payments") counter -- those
        # transaction types are never produced by the loader.
        self.assertNotIn("donations", summary)
        self.assertNotIn("unreconciled_payments", summary)

    def test_financial_summary_includes_sepa_mandate_details(self):
        """When a member has an active mandate the summary embeds its id/status."""
        member = self._member_with_customer(payment_method="SEPA Direct Debit")
        mandate = self.create_test_sepa_mandate(
            member_name=member.name,
            iban="NL13TEST0123456789",
            mandate_id=f"FINSUM-{member.name}",
            status="Active",
            used_for_memberships=1,
        )
        member.set("payment_history", [])
        summary = member.get_financial_summary()
        self.assertTrue(summary["has_sepa_mandate"])
        self.assertEqual(summary["sepa_mandate_id"], mandate.mandate_id)
        self.assertEqual(summary["sepa_mandate_status"], "Active")

    # ------------------------------------------------------------------
    # refresh_financial_data - orchestration
    # ------------------------------------------------------------------
    def test_refresh_financial_data_success_shape(self):
        """refresh_financial_data returns the documented result dict.

        A member with a customer should refresh all three sub-systems cleanly
        (wrapped in assertNoErrorLog so a log-and-swallow failure inside any
        sub-step is surfaced rather than hidden behind the broad try/except).
        """
        member = self._member_with_customer(payment_method="Bank Transfer")
        with self.assertNoErrorLog():
            result = member.refresh_financial_data()

        self.assertIn("success", result)
        self.assertIn("results", result)
        self.assertIn("payment_history", result["results"])
        self.assertIn("dues_schedule_history", result["results"])
        self.assertIn("sepa_mandates", result["results"])
        self.assertIsInstance(result["results"]["errors"], list)

    # ------------------------------------------------------------------
    # mark_as_paid - payment entry creation
    # ------------------------------------------------------------------
    def test_mark_as_paid_no_outstanding_invoices(self):
        """With no outstanding invoices mark_as_paid succeeds and processes zero."""
        member = self._member_with_customer(payment_method="Bank Transfer")
        result = member.mark_as_paid()
        self.assertTrue(result["success"])
        self.assertIn("0 invoices", result["message"])

    def test_mark_as_paid_creates_balanced_payment_entry(self):
        """mark_as_paid() pays down a real outstanding invoice via a correctly
        accounted, submitted Payment Entry (#1200).

        No live production caller of mark_as_paid was found while tracing
        #1200 (only this test and a Jest mock stub reference it) - reachability
        is NOT established, but it shares #906's exact construction-site defect
        (Payment Entry built with no paid_from/paid_to/company), so it is fixed
        alongside the two reachable sites. Before the fix, insert() failed the
        same way #906 did, the whole method body is wrapped in one try/except,
        and the failure was silently swallowed into `result["success"] = False`
        with no invoice ever paid - assertNoErrorLog would not have caught that
        specific shape (log_error IS called), so this asserts the real
        observable outcome (success, GL rows, outstanding paid to zero) instead.
        """
        from verenigingen.tests.support.invoice_payments import build_eur_membership_invoice
        from verenigingen.tests.support.sepa_test_company import get_eur_test_company

        member = self._member_with_customer(payment_method="Bank Transfer")
        invoice = build_eur_membership_invoice(self, member.customer, rate=45.0)
        # Priority 6, matching DRAIN_PRIORITY_BY_DOCTYPE's "Sales Invoice" tier:
        # both this invoice and the Payment Entry below reference the member's
        # Customer as party, so they must drain before it or cleanup hits
        # "Could not find Party" (the same ordering bug #1200's Ponto test hit).
        self.factory.track_document("Sales Invoice", invoice.name, priority=6)

        result = member.mark_as_paid()
        self.assertTrue(result["success"], result.get("error") or result.get("message"))
        self.assertIn("1 invoices", result["message"])

        invoice.reload()
        self.assertEqual(invoice.outstanding_amount, 0)

        company = get_eur_test_company()
        payment_entries = frappe.get_all(
            "Payment Entry Reference",
            filters={"reference_doctype": "Sales Invoice", "reference_name": invoice.name},
            fields=["parent"],
        )
        self.assertEqual(len(payment_entries), 1)
        pe = frappe.get_doc("Payment Entry", payment_entries[0].parent)
        self.factory.track_document("Payment Entry", pe.name, priority=6)

        self.assertEqual(pe.docstatus, 1)
        self.assertEqual(pe.payment_type, "Receive")
        self.assertEqual(pe.company, company)
        self.assertEqual(pe.paid_from, invoice.debit_to)

        gl_rows = frappe.get_all(
            "GL Entry",
            filters={"voucher_type": "Payment Entry", "voucher_no": pe.name},
            fields=["account", "debit", "credit"],
        )
        total_debit = sum(r.debit for r in gl_rows)
        total_credit = sum(r.credit for r in gl_rows)
        self.assertEqual(total_debit, total_credit, "GL rows must balance")
        self.assertEqual(total_debit, invoice.grand_total)
