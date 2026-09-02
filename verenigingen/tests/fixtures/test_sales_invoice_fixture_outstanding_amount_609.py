"""Regression test for a fixture defect found alongside #609.

`EnhancedTestCase.create_test_sales_invoice` used to `db_set()` `grand_total`
and `outstanding_amount` on a still-draft invoice and only THEN call
`submit()`. Submitting a Sales Invoice posts GL entries, and
`update_outstanding_amt` (erpnext gl_entry.py) recomputes and overwrites
`outstanding_amount` from the ledger -- so the db_set() done before submit()
was silently discarded. A fixture invoice built with
`outstanding_amount=0` (meant to simulate "Paid") therefore actually carried
whatever the ledger computed instead (typically the full grand_total, i.e.
still unpaid) -- 277 test sites depend on this fixture.

The same method already did this correctly for `status` a few lines below,
by `db_set`-ing it AFTER submit -- this test pins the same ordering for
`grand_total`/`outstanding_amount`.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestSalesInvoiceFixtureOutstandingAmountSurvivesSubmit(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="FixtureOutstanding",
            last_name="Test609",
            email=f"fixture.outstanding.609.{frappe.generate_hash(length=6)}@test.invalid",
            birth_date="1990-01-01",
        )
        self.customer = frappe.get_doc("Customer", self.member.customer)

    def test_outstanding_amount_zero_survives_submit(self):
        """TRIGGER: a submitted invoice built with outstanding_amount=0 must
        actually read back as 0 -- not silently reset to grand_total by the
        GL posting that submit() triggers."""
        invoice = self.create_test_sales_invoice(
            self.customer.name,
            grand_total=100.0,
            outstanding_amount=0.0,
        )

        self.assertEqual(invoice.docstatus, 1, "fixture should have submitted (status != Draft by default)")
        self.assertEqual(invoice.outstanding_amount, 0.0)

        # Re-read from the DB directly -- the in-memory object could be stale
        # even if the bug were present, since db_set() does update the
        # in-memory attribute; the actual defect was the GL post overwriting
        # the DB row a step later during submit().
        db_value = frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount")
        self.assertEqual(db_value, 0.0, f"DB outstanding_amount={db_value!r}, expected 0.0")

    def test_partial_outstanding_amount_survives_submit(self):
        """Same defect, non-zero case: a partially-paid fixture invoice must
        keep the exact outstanding_amount it was built with."""
        invoice = self.create_test_sales_invoice(
            self.customer.name,
            grand_total=100.0,
            outstanding_amount=40.0,
        )

        db_value = frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount")
        self.assertEqual(db_value, 40.0, f"DB outstanding_amount={db_value!r}, expected 40.0")

    def test_draft_invoice_still_gets_custom_outstanding_amount(self):
        """CONTROL: a Draft invoice (submit() never called) was never affected
        by this defect -- must keep working identically."""
        invoice = self.create_test_sales_invoice(
            self.customer.name,
            grand_total=75.0,
            outstanding_amount=75.0,
            status="Draft",
        )

        self.assertEqual(invoice.docstatus, 0)
        db_value = frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount")
        self.assertEqual(db_value, 75.0, f"DB outstanding_amount={db_value!r}, expected 75.0")

    def test_overdue_status_still_applied_after_amount_fix(self):
        """The pre-existing Overdue-status db_set (already correctly placed
        after submit()) must keep working next to the reordered amount block."""
        invoice = self.create_test_sales_invoice(
            self.customer.name,
            grand_total=60.0,
            outstanding_amount=60.0,
            status="Overdue",
        )

        self.assertEqual(invoice.docstatus, 1)
        self.assertEqual(
            frappe.db.get_value("Sales Invoice", invoice.name, "status"),
            "Overdue",
        )
        self.assertEqual(
            frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount"),
            60.0,
        )
