# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Real-DB integration tests for MemberHistoryUpdateService.

Covers the history orchestration exposed by the Member-form "Rebuild Payment
History" button:

- incremental_update_history_tables: full rebuild against a member with real
  Sales Invoices; returns OperationResult.ok and populates payment_history.
- The payment_history portion now delegates to
  PaymentHistoryService.load_payment_history_batched (the single invoice-row
  builder), so the rebuilt rows carry the Membership reference and SEPA-mandate
  fields, and NO standalone "Membership Dues Payment" rows are produced.
- refresh_fee_change_history: rebuilds fee_change_history from a real dues
  schedule and returns the documented OperationResult shape.
"""

import frappe
from frappe.utils import today

from verenigingen.services.member.history.member_history_update_service import (
    get_member_history_update_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMemberHistoryUpdateServiceRealDB(EnhancedTestCase):
    """Exercise the history orchestration against real documents."""

    def setUp(self):
        super().setUp()
        self.service = get_member_history_update_service()
        self.member = self.create_test_member(first_name="HistUpd", last_name="Svc")
        self.link_member_to_customer(self.member)
        self.member.reload()

    # ---- helpers (privileged setup) ----

    def _make_submitted_invoice(self, **kwargs):
        unique_series = f"THUS-{frappe.generate_hash(length=8).upper()}-.#####"
        invoice = self.create_test_sales_invoice(
            self.member.name, naming_series=unique_series, status="Draft", **kwargs
        )
        invoice.submit()
        self.track_doc("Sales Invoice", invoice.name)
        return invoice

    def _pay_invoice(self, invoice, reference_no="THUS-PAY"):
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        pe = get_payment_entry("Sales Invoice", invoice.name)
        pe.reference_no = reference_no
        pe.reference_date = today()
        pe.save()
        pe.submit()
        self.track_doc("Payment Entry", pe.name)
        return pe

    def _link_membership(self, invoice_name, membership_name):
        """Sales Invoice.membership is a read_only Custom Field; write it via
        frappe.db.set_value (doc.save() silently drops read_only field changes)."""
        frappe.db.set_value(
            "Sales Invoice", invoice_name, "membership", membership_name, update_modified=False
        )

    # ---- singleton / construction ----

    def test_service_singleton_and_name(self):
        self.assertEqual(self.service.service_name, "MemberHistoryUpdateService")

    # ---- incremental_update_history_tables (full orchestration) ----

    def test_incremental_update_returns_ok(self):
        """Full orchestration over a paid invoice succeeds and records the invoice row."""
        invoice = self._make_submitted_invoice()
        self._pay_invoice(invoice)

        result = self.service.incremental_update_history_tables(self.member)
        self.assertTrue(result.success)
        # The invoice row must be present after the rebuild.
        self.member.reload()
        invoice_rows = [r for r in (self.member.payment_history or []) if r.invoice == invoice.name]
        self.assertEqual(len(invoice_rows), 1)
        self.assertEqual(invoice_rows[0].reconciled, 1)
        self.assertEqual(invoice_rows[0].payment_status, "Paid")

    def test_incremental_update_no_invoices_ok_no_changes(self):
        """A member with no financial activity returns ok with 'No changes'."""
        result = self.service.incremental_update_history_tables(self.member)
        self.assertTrue(result.success)
        # dues_payments is retained in the contract but always zero now.
        self.assertEqual(result.data["dues_payments"]["count"], 0)

    def test_rebuild_emits_membership_reference_and_mandate(self):
        """The rebuild flows the unified builder's Membership reference + SEPA-mandate
        fields onto the row — the exact fields the removed hand-rolled invoice-row
        builder never set (it hardcoded reference_doctype=None and omitted all mandate
        fields), so clicking the button used to blank them."""
        membership = self.create_test_membership(member=self.member.name)
        invoice = self._make_submitted_invoice(is_membership_invoice=1)
        self._link_membership(invoice.name, membership.name)
        # A single active, membership-capable mandate.
        mandate = self.create_test_sepa_mandate(
            member_name=self.member.name, used_for_memberships=1, used_for_donations=0
        )
        self.track_doc("SEPA Mandate", mandate.name)
        self.member.reload()

        result = self.service.incremental_update_history_tables(self.member)
        self.assertTrue(result.success)

        self.member.reload()
        row = next(r for r in (self.member.payment_history or []) if r.invoice == invoice.name)
        self.assertEqual(row.transaction_type, "Membership Invoice")
        self.assertEqual(row.reference_doctype, "Membership")
        self.assertEqual(row.reference_name, membership.name)
        self.assertEqual(row.has_mandate, 1)
        self.assertEqual(row.sepa_mandate, mandate.name)

    def test_rebuild_is_invoice_only_no_standalone_dues_row(self):
        """A custom_member Payment Entry NOT reconciled to an invoice must NOT
        produce a standalone 'Membership Dues Payment' row — the rebuild is
        invoice-only, matching every other payment_history writer."""
        # Seed an invoice so we can borrow account fields for a standalone payment.
        seed_invoice = self._make_submitted_invoice()
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        template = get_payment_entry("Sales Invoice", seed_invoice.name)
        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = "Receive"
        pe.party_type = "Customer"
        pe.party = self.member.customer
        pe.company = template.company
        pe.paid_from = template.paid_from
        pe.paid_to = template.paid_to
        pe.paid_from_account_currency = template.paid_from_account_currency
        pe.paid_to_account_currency = template.paid_to_account_currency
        pe.posting_date = today()
        pe.paid_amount = 12.0
        pe.received_amount = 12.0
        pe.source_exchange_rate = 1.0
        pe.target_exchange_rate = 1.0
        pe.reference_no = "DUES-STANDALONE"
        pe.reference_date = today()
        if pe.meta.has_field("custom_member"):
            pe.custom_member = self.member.name
        pe.save()
        pe.submit()
        self.track_doc("Payment Entry", pe.name)

        result = self.service.incremental_update_history_tables(self.member)
        self.assertTrue(result.success)

        self.member.reload()
        dues_rows = [
            r for r in (self.member.payment_history or []) if r.transaction_type == "Membership Dues Payment"
        ]
        self.assertEqual(dues_rows, [], "no standalone dues rows should be produced")
        # The standalone PE must not appear as its own history row either.
        standalone = [
            r for r in (self.member.payment_history or []) if r.payment_entry == pe.name and not r.invoice
        ]
        self.assertEqual(standalone, [])


class TestRefreshFeeChangeHistoryRealDB(EnhancedTestCase):
    """refresh_fee_change_history rebuild from real dues schedules."""

    def setUp(self):
        super().setUp()
        self.service = get_member_history_update_service()

    def test_refresh_with_no_schedules_no_changes(self):
        """A member with no schedules/amendments yields a 'no_changes' ok result."""
        member = self.create_test_member(first_name="FeeRef", last_name="None")
        result = self.service.refresh_fee_change_history(member.name)
        self.assertTrue(result.success)
        self.assertEqual(result.data["dues_schedules_found"], 0)
        self.assertEqual(result.data["amendments_found"], 0)

    def test_refresh_builds_entry_from_schedule(self):
        """A real dues schedule produces a Schedule-Created fee_change_history row."""
        membership_type = self.create_test_membership_type(amount=15.0)
        member, schedule = self.create_test_member_with_schedule(
            first_name="FeeRef",
            last_name="Sched",
            membership_type_name=membership_type.name,
            start_date=today(),
        )

        result = self.service.refresh_fee_change_history(member.name)
        self.assertTrue(result.success)
        self.assertGreaterEqual(result.data["dues_schedules_found"], 1)

        member.reload()
        rows = [r for r in (member.fee_change_history or []) if r.dues_schedule == schedule.name]
        self.assertEqual(len(rows), 1)
        self.assertEqual(float(rows[0].new_dues_rate), float(schedule.dues_rate))

    def test_refresh_unknown_member_returns_fail(self):
        """Refreshing a non-existent member returns a failed OperationResult (HIST_006)."""
        result = self.service.refresh_fee_change_history("MEM-DOES-NOT-EXIST-XYZ")
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "HIST_006")
