# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Tests for #906: `process_application_refund` builds a Payment Entry with no
`paid_from` (and no `company`), so `insert()` fails deterministically with
"Source Exchange Rate is mandatory" - and a second, independent defect found by
the #856 sweep (PR #907): the "already paid" guard reads only
`outstanding_amount`, with no `docstatus` check, so a CANCELLED invoice
(outstanding_amount == 0, same as a paid one) slips past it and reaches Payment
Entry creation.

These tests exercise `_create_and_submit_application_refund`, the helper
`process_application_refund` was split into for exactly this reason:
`verenigingen.verenigingen.doctype.member.member.Member` has NO
`application_invoice` field (confirmed against `frappe.get_meta("Member")` and
`DESCRIBE tabMember` on a real site: only `next_invoice_date` /
`mollie_subscription_next_invoice_date` exist). `membership_creation_service.py`
sets `member_doc.application_invoice = invoice.name` as a plain Python attribute,
which Frappe drops silently on `save()` because it is not a declared column - so it
is NEVER persisted, and `process_application_refund`'s own
`getattr(member, "application_invoice", None)` is `None` for every Member loaded
fresh from the DB, which is exactly how `process_application_refund` loads it (and
how its one real caller, `membership_application_review.py`, loads its own copy
too). That makes `process_application_refund` unreachable from its real call site
today - a separate bug (see the #661 comment this investigation added) rather than
something to fix here. Testing `_create_and_submit_application_refund` directly
exercises the real, unmocked guard checks, Payment Entry construction, insert, and
submit - the code #906 is actually about - without needing a mock to route around
the unrelated dead-field bug.
"""

import frappe
from frappe.utils import flt

from verenigingen.api.payment_processing import _create_and_submit_application_refund
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.invoice_payments import member_with_customer


class TestApplicationRefundCreation(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.company = self._get_test_company()
        self.member = member_with_customer(self, first_name="AppRefund")

    def _paid_invoice(self, amount=55.0):
        """A submitted Sales Invoice fully paid (outstanding_amount == 0)."""
        invoice = self.create_test_sales_invoice(
            customer=self.member.customer,
            company=self.company,
            grand_total=amount,
            outstanding_amount=0,
        )
        self.assertEqual(invoice.docstatus, 1, "premise: invoice must be submitted")
        self.assertEqual(flt(invoice.outstanding_amount), 0, "premise: invoice must be fully paid")
        return invoice

    def test_refund_creates_and_submits_payment_entry(self):
        """The #906 premise: a fully-paid, submitted invoice must produce a real,
        submitted refund Payment Entry - not an insert() crash."""
        invoice = self._paid_invoice(amount=55.0)

        result = _create_and_submit_application_refund(
            self.member, invoice.name, "Application Rejected: test"
        )

        self.assertTrue(result["success"], result)
        pe_name = result["payment_entry"]
        self.track_doc("Payment Entry", pe_name)
        pe = frappe.get_doc("Payment Entry", pe_name)
        self.assertEqual(pe.docstatus, 1, "refund Payment Entry must be submitted")
        self.assertEqual(pe.payment_type, "Pay")
        self.assertEqual(pe.company, invoice.company)
        self.assertEqual(pe.paid_to, invoice.debit_to)
        self.assertTrue(pe.paid_from, "paid_from must be populated")
        self.assertEqual(flt(pe.paid_amount), flt(invoice.grand_total))

    def test_cancelled_invoice_is_refused_not_processed(self):
        """The second #906 defect: a CANCELLED invoice carries
        outstanding_amount == 0, the same as a paid one, so it must be refused
        explicitly by a docstatus guard rather than falling through to Payment
        Entry creation.

        Measured while writing this test: without the guard, ERPNext's OWN
        generic "cannot link a cancelled document" check (a safeguard on every
        doctype with a Link field, not something specific to this function)
        already refuses the insert() once paid_from/company are fixed AND the
        invoice is referenced via the Payment Entry's "references" child table -
        but that reference row was itself invalid (see the linked #1199 fix, which
        removed it) and once removed, that side-channel protection disappears too:
        without the docstatus guard, a cancelled invoice's refund actually
        SUCCEEDS (verified via mutation below). The assertion below is on the
        exact, purpose-written guard message, not merely on `success is False`.
        """
        invoice = self._paid_invoice(amount=40.0)
        invoice.cancel()
        invoice.reload()
        self.assertEqual(invoice.docstatus, 2, "premise: invoice must be cancelled")
        self.assertEqual(
            flt(invoice.outstanding_amount),
            0,
            "premise: a cancelled invoice's outstanding_amount is 0, same as paid",
        )

        result = _create_and_submit_application_refund(
            self.member, invoice.name, "Application Rejected: test"
        )

        self.assertFalse(result["success"], result)
        self.assertEqual(
            result["message"],
            "Invoice is not submitted",
            "must be refused by the explicit docstatus guard with its own message, "
            f"got: {result['message']!r}",
        )
        self.assertFalse(
            frappe.db.exists("Payment Entry", {"reference_no": f"REFUND-{invoice.name}"}),
            "no Payment Entry may be created for a cancelled invoice",
        )
