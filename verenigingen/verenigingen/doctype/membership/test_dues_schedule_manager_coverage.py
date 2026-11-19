"""
Additional coverage for membership/dues_schedule_manager.py.

test_dues_schedule_manager.py already covers the Paid path, the early-return
guards, the placeholder bank-details helper and the SEPA selector guards. These
tests target the *uncovered* status branches of sync_membership_with_dues_schedule
and the Payment-Entry aggregation loop in get_membership_payment_history:

- sync: Overdue invoice -> membership.unpaid_amount = outstanding_amount.
- sync: ordinary Unpaid invoice (else branch) -> unpaid_amount = outstanding.
- sync: Paid invoice -> unpaid_amount cleared to 0 and last_payment_date set.
- payment history: a linked, submitted Payment Entry shows up in the entry's
  `payments` list with the real paid amount.

All documents are real; no business logic is mocked.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.membership.dues_schedule_manager import (
    get_membership_payment_history,
    sync_membership_with_dues_schedule,
)


class TestDuesScheduleManagerCoverage(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.membership_type = self.create_test_membership_type(
            membership_type_name="DSMCov Type",
            amount=50.0,
            contribution_mode="Fixed Amount",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _member_with_membership(self):
        member, schedule = self.create_test_member_with_schedule(
            first_name="DsmCov",
            last_name="Member",
            membership_type_name=self.membership_type.name,
            start_date=today(),
        )
        membership_name = frappe.db.get_value(
            "Membership", {"member": member.name, "status": "Active"}, "name"
        )
        membership = frappe.get_doc("Membership", membership_name)
        return member, membership, schedule

    def _force_invoice_status(self, invoice, status, outstanding):
        invoice.reload()
        invoice.db_set("outstanding_amount", outstanding)
        invoice.db_set("status", status)
        invoice.reload()

    def _pay_invoice(self, invoice):
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        pe = get_payment_entry("Sales Invoice", invoice.name)
        pe.reference_no = f"REF-{frappe.generate_hash(length=6)}"
        pe.reference_date = today()
        pe.insert()
        pe.submit()
        return pe

    # ------------------------------------------------------------------
    # sync_membership_with_dues_schedule status branches
    # ------------------------------------------------------------------
    def test_sync_overdue_sets_unpaid_amount(self):
        """An Overdue latest invoice sets membership.unpaid_amount to its outstanding."""
        member, membership, _schedule = self._member_with_membership()
        invoice = self.create_test_sales_invoice(member.customer, grand_total=50.0)
        self._force_invoice_status(invoice, "Overdue", outstanding=50.0)

        result = sync_membership_with_dues_schedule(membership)

        self.assertIsNotNone(result)
        membership.reload()
        self.assertEqual(membership.unpaid_amount, 50.0)

    def test_sync_unpaid_else_branch_sets_outstanding(self):
        """A plain Unpaid invoice (else branch) sets unpaid_amount to its outstanding."""
        member, membership, _schedule = self._member_with_membership()
        invoice = self.create_test_sales_invoice(member.customer, grand_total=50.0)
        # Freshly submitted invoices are already "Unpaid" with full outstanding.
        invoice.reload()
        self.assertEqual(invoice.status, "Unpaid")

        sync_membership_with_dues_schedule(membership)

        membership.reload()
        self.assertEqual(membership.unpaid_amount, invoice.outstanding_amount)
        self.assertGreater(membership.unpaid_amount, 0)

    def test_sync_paid_clears_unpaid_and_sets_payment_date(self):
        """A Paid latest invoice clears unpaid_amount and records last_payment_date."""
        member, membership, _schedule = self._member_with_membership()
        invoice = self.create_test_sales_invoice(member.customer, grand_total=50.0)
        self._force_invoice_status(invoice, "Paid", outstanding=0)

        sync_membership_with_dues_schedule(membership)

        membership.reload()
        self.assertEqual(membership.unpaid_amount, 0)
        self.assertEqual(frappe.utils.getdate(membership.last_payment_date), frappe.utils.getdate(today()))

    # ------------------------------------------------------------------
    # get_membership_payment_history with a linked Payment Entry
    # ------------------------------------------------------------------
    def test_payment_history_includes_linked_payment_entry(self):
        """A submitted Payment Entry against the invoice surfaces in the payments list."""
        member, membership, _schedule = self._member_with_membership()
        invoice = self.create_test_sales_invoice(member.customer, grand_total=50.0)
        pe = self._pay_invoice(invoice)

        history = get_membership_payment_history(membership)

        self.assertEqual(len(history), 1)
        entry = history[0]
        self.assertEqual(entry["invoice"], invoice.name)
        # The Payment Entry loop populated the payments list with the real PE.
        self.assertEqual(len(entry["payments"]), 1)
        payment = entry["payments"][0]
        self.assertEqual(payment["payment_entry"], pe.name)
        self.assertEqual(payment["amount"], pe.paid_amount)
        self.assertEqual(payment["amount"], 50.0)

    # ------------------------------------------------------------------
    # #1166: get_membership_payment_history() per-row get_doc N+1
    # ------------------------------------------------------------------
    def _paid_invoice_for_1166(self, member, posting_offset_days, grand_total):
        """Submitted invoice (dated `posting_offset_days` AHEAD) plus a submitted PE.

        Future-dated, because the history only lists invoices posted on or after the
        membership start date (today)."""
        invoice = self.create_test_sales_invoice(
            member.customer,
            grand_total=grand_total,
            posting_date=frappe.utils.add_days(today(), posting_offset_days),
        )
        return invoice, self._pay_invoice(invoice)

    def _count_sql_calls_for_1166(self, fn):
        queries = []
        orig_sql = frappe.db.__class__.sql

        def counting_sql(db, *args, **kwargs):
            queries.append(args[0] if args else kwargs.get("query"))
            return orig_sql(db, *args, **kwargs)

        frappe.db.__class__.sql = counting_sql
        try:
            result = fn()
        finally:
            frappe.db.__class__.sql = orig_sql
        return result, len(queries)

    def test_payment_history_matches_full_documents_for_real_rows(self):
        """Output equality (#1166): each history row equals what the full Sales
        Invoice / Payment Entry documents say -- same values, same Python types,
        same newest-first order -- so reading them off bulk get_all rows is lossless."""
        member, membership, _schedule = self._member_with_membership()
        invoices = []
        for offset, amount in ((0, 50.0), (1, 60.0), (2, 70.0)):
            invoice, pe = self._paid_invoice_for_1166(member, offset, amount)
            invoices.append((invoice, pe))

        history = get_membership_payment_history(membership)

        expected = []
        for invoice, pe in invoices:
            inv_doc = frappe.get_doc("Sales Invoice", invoice.name)
            pe_doc = frappe.get_doc("Payment Entry", pe.name)
            expected.append(
                {
                    "invoice": inv_doc.name,
                    "date": inv_doc.posting_date,
                    "amount": inv_doc.grand_total,
                    "status": inv_doc.status,
                    "payments": [
                        {
                            "payment_entry": pe_doc.name,
                            "amount": pe_doc.paid_amount,
                            "date": pe_doc.posting_date,
                            "mode": pe_doc.mode_of_payment,
                            "status": pe_doc.status,
                        }
                    ],
                }
            )
        # posting_date desc: the latest-dated invoice comes first. Distinct dates
        # make the order assertion discriminating.
        expected.reverse()
        self.assertEqual([h["invoice"] for h in history], [i.name for i, _ in reversed(invoices)])
        self.assertEqual(history, expected)
        for got, want in zip(history, expected):
            self.assertIs(type(got["date"]), type(want["date"]))
            self.assertIs(type(got["amount"]), type(want["amount"]))
            self.assertIs(type(got["payments"][0]["amount"]), type(want["payments"][0]["amount"]))
            self.assertIs(type(got["payments"][0]["date"]), type(want["payments"][0]["date"]))
        # Control: the rows are not all identical, so a dropped or swapped field shows.
        self.assertEqual(len({h["amount"] for h in history}), 3)
        self.assertEqual(len({h["date"] for h in history}), 3)

    def test_payment_history_query_count_does_not_scale_with_invoices(self):
        """#1166: one get_doc per invoice and one per Payment Entry made the query
        count grow with the member's invoices. It must now stay flat."""
        member, membership, _schedule = self._member_with_membership()
        self._paid_invoice_for_1166(member, 0, 50.0)

        # Warm meta / table-column caches so a cold information_schema read is
        # not mistaken for part of the N+1.
        for doctype in ("Sales Invoice", "Payment Entry", "Payment Entry Reference"):
            frappe.get_meta(doctype)
            frappe.db.get_table_columns(doctype)
        get_membership_payment_history(membership)

        one_result, one_invoice_queries = self._count_sql_calls_for_1166(
            lambda: get_membership_payment_history(membership)
        )
        self.assertEqual(len(one_result), 1)

        self._paid_invoice_for_1166(member, 1, 60.0)
        self._paid_invoice_for_1166(member, 2, 70.0)
        three_result, three_invoice_queries = self._count_sql_calls_for_1166(
            lambda: get_membership_payment_history(membership)
        )
        self.assertEqual(len(three_result), 3)
        self.assertEqual(three_result[0]["payments"][0]["amount"], 70.0)

        self.assertLessEqual(
            three_invoice_queries,
            one_invoice_queries,
            f"query count grew with invoices: 1 invoice={one_invoice_queries}, "
            f"3 invoices={three_invoice_queries}",
        )

    def test_payment_history_cancelled_and_shared_payment_entries_match_full_documents(self):
        """#1166 review: one invoice with two Payment Entries (one cancelled -- the history
        shows cancelled PEs with their status) and one PE paying two invoices. The exact
        `payments` lists and their order must equal what the full documents say, which
        pins "no docstatus filter on Payment Entry" and "references keep their order"."""
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        member, membership, _schedule = self._member_with_membership()
        invoice_a, pe_cancelled = self._paid_invoice_for_1166(member, 2, 70.0)
        invoice_b = self.create_test_sales_invoice(
            member.customer, grand_total=60.0, posting_date=frappe.utils.add_days(today(), 1)
        )
        invoice_c = self.create_test_sales_invoice(
            member.customer, grand_total=50.0, posting_date=frappe.utils.add_days(today(), 0)
        )
        # invoice_a gets a second, live PE after the first is cancelled (Payment Entry
        # cancel reopens the outstanding, so a new PE can be raised).
        pe_cancelled.reload()
        pe_cancelled.cancel()
        pe_second = self._pay_invoice(frappe.get_doc("Sales Invoice", invoice_a.name))
        # One PE paying invoice_b AND invoice_c.
        pe_shared = get_payment_entry("Sales Invoice", invoice_b.name)
        pe_shared.reference_no = f"REF-{frappe.generate_hash(length=6)}"
        pe_shared.reference_date = today()
        pe_shared.append(
            "references",
            {
                "reference_doctype": "Sales Invoice",
                "reference_name": invoice_c.name,
                "total_amount": 50.0,
                "outstanding_amount": 50.0,
                "allocated_amount": 50.0,
            },
        )
        pe_shared.paid_amount = 110.0
        pe_shared.received_amount = 110.0
        pe_shared.insert()
        pe_shared.submit()

        history = {h["invoice"]: h["payments"] for h in get_membership_payment_history(membership)}

        def summary(name):
            doc = frappe.get_doc("Payment Entry", name)
            return {
                "payment_entry": doc.name,
                "amount": doc.paid_amount,
                "date": doc.posting_date,
                "mode": doc.mode_of_payment,
                "status": doc.status,
            }

        # Control: the cancelled PE really is cancelled and really is listed.
        self.assertEqual(summary(pe_cancelled.name)["status"], "Cancelled")
        got_a = history[invoice_a.name]
        self.assertEqual(
            sorted(p["payment_entry"] for p in got_a), sorted([pe_cancelled.name, pe_second.name])
        )
        # Order: exactly what the per-invoice reference query returns (default get_all order).
        ref_order = [
            r.parent
            for r in frappe.get_all(
                "Payment Entry Reference", filters={"reference_name": invoice_a.name}, fields=["parent"]
            )
        ]
        self.assertEqual([p["payment_entry"] for p in got_a], ref_order)
        self.assertEqual(got_a, [summary(n) for n in ref_order])
        self.assertEqual(history[invoice_b.name], [summary(pe_shared.name)])
        self.assertEqual(history[invoice_c.name], [summary(pe_shared.name)])
