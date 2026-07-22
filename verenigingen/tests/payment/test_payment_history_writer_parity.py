# Copyright (c) 2026, Veganisme.org and contributors
"""Guard against the incremental writer and the full rebuild diverging."""

import frappe

from verenigingen.services.member.payment.payment_history_service import get_payment_history_service
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

# Fields compared for parity (exclude volatile/reference-metadata-only fields).
PARITY_FIELDS = [
    "invoice",
    "transaction_type",
    "reference_doctype",
    "reference_name",
    "amount",
    "outstanding_amount",
    "status",
    "payment_status",
    "payment_entry",
    "payment_method",
    "paid_amount",
    "reconciled",
    "coverage_start_date",
    "coverage_end_date",
    "has_mandate",
    "sepa_mandate",
    "mandate_status",
    "mandate_reference",
]


class TestPaymentHistoryWriterParity(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="Par", last_name="Ity")
        self.link_member_to_customer(self.member)
        self.member.reload()
        self.service = get_payment_history_service()

    def _make_submitted_invoice(self, **kwargs):
        """Create and submit a test Sales Invoice exactly once.

        create_test_sales_invoice() auto-submits any invoice whose `status`
        kwarg isn't explicitly "Draft" (see its `if kwargs.get("status") !=
        "Draft": invoice.submit()`). The previous version of this helper let
        that auto-submit happen and THEN separately set fields and called
        .save() + .submit() again, double-submitting a doc that was already
        submitted. Explicitly requesting "Draft" here means we control the
        one-and-only submit ourselves, after any field tweaks (e.g. custom
        coverage dates below) have been set.
        """
        unique = f"PAR-{frappe.generate_hash(length=8).upper()}-.#####"
        inv = self.create_test_sales_invoice(self.member.name, naming_series=unique, status="Draft", **kwargs)
        inv.submit()
        self.track_doc("Sales Invoice", inv.name)
        return inv

    def _set_coverage_dates(self, invoice_name, start_date, end_date):
        """Set the coverage custom fields directly.

        get_coverage_for_invoice() falls back to reading
        custom_coverage_start_date/custom_coverage_end_date straight off the
        invoice when there's no Membership Dues Schedule row for it, so a
        direct frappe.db.set_value is sufficient to exercise both writers'
        coverage-date handling without needing a full dues-schedule fixture.
        """
        frappe.db.set_value(
            "Sales Invoice",
            invoice_name,
            {
                "custom_coverage_start_date": start_date,
                "custom_coverage_end_date": end_date,
            },
            update_modified=False,
        )

    def _link_membership(self, invoice_name, membership_name):
        """Sales Invoice.membership is a read_only Custom Field; it must be
        written via frappe.db.set_value (doc.save() silently drops read_only
        field changes), exactly as
        test_payment_history_service_realdb.py::test_membership_reference_persists_and_flows_to_history
        does."""
        frappe.db.set_value(
            "Sales Invoice", invoice_name, "membership", membership_name, update_modified=False
        )

    def test_incremental_row_matches_rebuild_row(self):
        membership = self.create_test_membership(member=self.member.name)
        inv = self._make_submitted_invoice(is_membership_invoice=1)
        self._set_coverage_dates(inv.name, "2026-01-01", "2026-01-31")
        self._link_membership(inv.name, membership.name)

        # A single active, membership-capable mandate: exercises has_mandate/
        # sepa_mandate/mandate_status/mandate_reference on both writers.
        mandate = self.create_test_sepa_mandate(
            member_name=self.member.name, used_for_memberships=1, used_for_donations=0
        )
        self.track_doc("SEPA Mandate", mandate.name)

        self.member.reload()

        # Rebuild path
        self.service.load_payment_history_batched(self.member)
        rebuild_row = next(r for r in self.member.payment_history if r.invoice == inv.name)

        # Incremental path
        incremental_entry = self.member._build_payment_history_entry(
            frappe.get_doc("Sales Invoice", inv.name)
        )

        for field in PARITY_FIELDS:
            self.assertEqual(
                incremental_entry.get(field),
                rebuild_row.get(field),
                f"Divergence on '{field}': incremental={incremental_entry.get(field)!r} "
                f"rebuild={rebuild_row.get(field)!r}",
            )

        # Sanity: the fixtures actually exercised the risky fields (not None==None).
        self.assertEqual(incremental_entry["reference_doctype"], "Membership")
        self.assertEqual(incremental_entry["reference_name"], membership.name)
        self.assertIsNotNone(incremental_entry["coverage_start_date"])
        self.assertIsNotNone(incremental_entry["coverage_end_date"])
        self.assertEqual(incremental_entry["has_mandate"], 1)
        self.assertEqual(incremental_entry["sepa_mandate"], mandate.name)

    def test_mandate_resolution_matches_with_newer_donation_only_mandate(self):
        """Regression test for a genuine divergence found while strengthening
        this suite: PaymentHistoryService._get_default_mandate() used to
        delegate to member_doc.get_default_sepa_mandate() /
        SEPAMandateManager.get_default_mandate(), which picks the single
        most-recently-created ACTIVE mandate with no purpose filter at all.
        The incremental writer (PaymentHistoryEntryBuilder.build_from_invoice_doc)
        has always filtered on used_for_memberships=1. Those two mechanisms
        pick DIFFERENT mandates when a member has an active donation-only
        mandate that is newer than their active membership mandate. Fixed by
        making the rebuild path's _get_default_mandate() filter on
        used_for_memberships=1 too, so both writers converge on the
        membership-capable mandate. This test guards that convergence.
        """
        membership_mandate = self.create_test_sepa_mandate(
            member_name=self.member.name, used_for_memberships=1, used_for_donations=0
        )
        self.track_doc("SEPA Mandate", membership_mandate.name)
        # Created after (so newer by `creation`), but donation-only -- must NOT
        # be picked as the mandate for a membership invoice's payment history row.
        donation_mandate = self.create_test_sepa_mandate(
            member_name=self.member.name, used_for_memberships=0, used_for_donations=1
        )
        self.track_doc("SEPA Mandate", donation_mandate.name)

        inv = self._make_submitted_invoice(is_membership_invoice=1)
        self.member.reload()

        self.service.load_payment_history_batched(self.member)
        rebuild_row = next(r for r in self.member.payment_history if r.invoice == inv.name)
        incremental_entry = self.member._build_payment_history_entry(
            frappe.get_doc("Sales Invoice", inv.name)
        )

        for field in ("has_mandate", "sepa_mandate", "mandate_status", "mandate_reference"):
            self.assertEqual(
                incremental_entry.get(field),
                rebuild_row.get(field),
                f"Divergence on '{field}': incremental={incremental_entry.get(field)!r} "
                f"rebuild={rebuild_row.get(field)!r}",
            )

        # Both writers must resolve the membership-capable mandate, not the
        # newer donation-only one.
        self.assertEqual(incremental_entry["sepa_mandate"], membership_mandate.name)
        self.assertEqual(rebuild_row.get("sepa_mandate"), membership_mandate.name)

    def test_reconciling_pe_flips_invoice_row_to_paid(self):
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        inv = self._make_submitted_invoice(is_membership_invoice=1)
        pe = get_payment_entry("Sales Invoice", inv.name)
        pe.reference_no = "PARITY-PE"
        pe.reference_date = frappe.utils.today()
        pe.save()
        pe.submit()
        self.track_doc("Payment Entry", pe.name)

        self.member.reload()
        entry = self.member._build_payment_history_entry(frappe.get_doc("Sales Invoice", inv.name))
        self.assertEqual(entry["payment_status"], "Paid")
        self.assertEqual(entry["reconciled"], 1)
        self.assertEqual(entry["transaction_type"], "Membership Invoice")

        # Also check the rebuild path agrees with the incremental path in the
        # reconciled state -- the previous version of this test only checked
        # three fields on the incremental side and never ran the rebuild path
        # at all, so a divergence in payment_entry/payment_method/paid_amount/
        # reconciled/payment_status after reconciliation would have gone
        # completely unnoticed.
        self.member.reload()
        self.service.load_payment_history_batched(self.member)
        rebuild_row = next(r for r in self.member.payment_history if r.invoice == inv.name)

        for field in PARITY_FIELDS:
            self.assertEqual(
                entry.get(field),
                rebuild_row.get(field),
                f"Divergence on '{field}' after reconciliation: incremental={entry.get(field)!r} "
                f"rebuild={rebuild_row.get(field)!r}",
            )
