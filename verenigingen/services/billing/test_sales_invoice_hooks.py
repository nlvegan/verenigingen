# -*- coding: utf-8 -*-
"""
Integration tests for
verenigingen/services/billing/sales_invoice_hooks.py

These exercise the two Sales Invoice hooks NOT already covered by
tests/backend/components/test_sales_invoice_chapter_population.py (which covers
populate_member_chapter):

  - set_member_from_customer (before_validate): copies Customer.member onto the
    invoice when the invoice has no member yet.
  - on_trash: clears dangling references to a Sales Invoice from Membership Dues
    Schedule.last_generated_invoice and Member Payment History child rows before
    the invoice is deleted, so link validation does not block deletion.

Both are driven through real documents. set_member_from_customer runs via the
genuine before_validate hook (we insert an invoice and assert the side effect).
on_trash's reference-clearing is driven by deleting a real invoice that is
referenced from a real schedule and a real Member Payment History row.

ISOLATION: invoices are drafts (rolled back); explicitly-committed master rows
are tracked and force-deleted in tearDown.
"""

import frappe
from frappe.utils import nowdate

from verenigingen.services.billing.sales_invoice_hooks import set_member_from_customer
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestSalesInvoiceHooks(EnhancedTestCase):
    COMPANY = "_Test Company"
    INCOME_ACCOUNT = "Test Sales Income - _TC"

    def setUp(self):
        super().setUp()
        self._tracked = []

    def tearDown(self):
        for doctype, name in reversed(self._tracked):
            if frappe.db.exists(doctype, name):
                try:
                    doc = frappe.get_doc(doctype, name)
                    if getattr(doc, "docstatus", 0) == 1:
                        doc.cancel()
                    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
                except Exception:
                    pass
        frappe.db.commit()
        super().tearDown()

    # ------------------------------------------------------------------
    # Fixture helpers
    # ------------------------------------------------------------------
    def _make_member_with_customer(self):
        """Create a Member; Member.save() auto-provisions a linked Customer
        (Customer.member is a unique link), so we reuse that customer rather than
        creating a second one (which would collide on the unique member key)."""
        member = self.create_test_member(member_since=nowdate())
        self._tracked.append(("Member", member.name))

        cust_name = frappe.db.get_value("Member", member.name, "customer") or frappe.db.get_value(
            "Customer", {"member": member.name}, "name"
        )
        if not cust_name:
            cust = frappe.new_doc("Customer")
            cust.customer_name = f"Hooks Cust {frappe.generate_hash(length=8)}"
            cust.customer_type = "Individual"
            cust.customer_group = "Individual"
            cust.territory = "Netherlands"
            cust.member = member.name
            cust.insert(ignore_permissions=True)
            self._tracked.append(("Customer", cust.name))
            cust_name = cust.name
            frappe.db.set_value("Member", member.name, "customer", cust.name)
        cust = frappe.get_doc("Customer", cust_name)
        return member, cust

    def _make_plain_customer(self):
        cust = frappe.new_doc("Customer")
        cust.customer_name = f"Plain Cust {frappe.generate_hash(length=8)}"
        cust.customer_type = "Individual"
        cust.customer_group = "Individual"
        cust.territory = "Netherlands"
        cust.insert(ignore_permissions=True)
        self._tracked.append(("Customer", cust.name))
        return cust

    def _build_invoice(self, customer):
        currency = frappe.db.get_value("Company", self.COMPANY, "default_currency")
        cost_center = frappe.db.get_value("Company", self.COMPANY, "cost_center")
        debit_to = frappe.db.get_value("Company", self.COMPANY, "default_receivable_account")
        return frappe.get_doc(
            {
                "doctype": "Sales Invoice",
                "company": self.COMPANY,
                "currency": currency,
                "conversion_rate": 1.0,
                "debit_to": debit_to,
                "customer": customer,
                "posting_date": nowdate(),
                "due_date": nowdate(),
                "items": [
                    {
                        "item_name": "Hook Test Item",
                        "item_group": "Services",
                        "qty": 1,
                        "rate": 10,
                        "uom": "Nos",
                        "income_account": self.INCOME_ACCOUNT,
                        "cost_center": cost_center,
                    }
                ],
            }
        )

    def _insert_doc(self, doc):
        """Insert a test doc through the real save pipeline (runs the hooks)."""
        doc.insert(ignore_permissions=True)
        return doc

    def _persist_doc(self, doc):
        """Save a test doc through the real save pipeline (runs the hooks)."""
        doc.save(ignore_permissions=True)
        return doc

    # ==================================================================
    # set_member_from_customer
    # ==================================================================
    def test_member_populated_from_customer_via_hook(self):
        """Inserting an invoice for a member-linked customer auto-populates the
        Sales Invoice.member field through the before_validate hook."""
        member, cust = self._make_member_with_customer()
        doc = self._build_invoice(cust.name)
        self.assertFalse(doc.get("member"))
        self._insert_doc(doc)  # runs before_validate hook
        self._tracked.append(("Sales Invoice", doc.name))
        self.assertEqual(doc.member, member.name)

    def test_member_not_overwritten_when_already_set(self):
        """Direct call: an invoice that already has member set is left untouched
        even if the customer maps to a different member."""
        _, cust = self._make_member_with_customer()
        doc = self._build_invoice(cust.name)
        doc.member = "PRESET-MEMBER-XYZ"
        set_member_from_customer(doc, "before_validate")
        self.assertEqual(doc.member, "PRESET-MEMBER-XYZ")

    def test_member_left_blank_for_non_member_customer(self):
        """A customer with no linked member leaves invoice.member blank."""
        cust = self._make_plain_customer()
        doc = self._build_invoice(cust.name)
        self._insert_doc(doc)
        self._tracked.append(("Sales Invoice", doc.name))
        self.assertFalse(doc.get("member"))

    # ==================================================================
    # on_trash — reference clearing
    # ==================================================================
    def test_on_trash_clears_dues_schedule_reference(self):
        """Deleting a Sales Invoice referenced by a Membership Dues Schedule's
        last_generated_invoice clears that reference (on_trash hook)."""
        member, cust = self._make_member_with_customer()
        doc = self._build_invoice(cust.name)
        self._insert_doc(doc)
        invoice_name = doc.name

        # Create a schedule referencing this invoice.
        sched_name = f"HOOK-SCHED-{frappe.generate_hash(length=8)}"
        frappe.db.sql(
            """
            INSERT INTO `tabMembership Dues Schedule`
              (name, member, last_generated_invoice, creation, modified, owner, modified_by, docstatus)
            VALUES (%s, %s, %s, NOW(), NOW(), 'Administrator', 'Administrator', 0)
            """,
            (sched_name, member.name, invoice_name),
        )
        self._tracked.append(("Membership Dues Schedule", sched_name))
        frappe.db.commit()

        # Delete the invoice -> on_trash should NULL the reference.
        frappe.delete_doc("Sales Invoice", invoice_name, force=True, ignore_permissions=True)
        frappe.db.commit()

        self.assertIsNone(
            frappe.db.get_value("Membership Dues Schedule", sched_name, "last_generated_invoice")
        )

    def test_on_trash_clears_payment_history_reference(self):
        """Deleting a Sales Invoice referenced in a Member Payment History child
        row clears the row's invoice + invoice_doctype (on_trash hook)."""
        member, cust = self._make_member_with_customer()
        doc = self._build_invoice(cust.name)
        self._insert_doc(doc)
        invoice_name = doc.name

        # Add a Member Payment History child row pointing at the invoice.
        member_doc = frappe.get_doc("Member", member.name)
        member_doc.append(
            "payment_history",
            {
                "invoice": invoice_name,
                "invoice_doctype": "Sales Invoice",
                "amount": 10,
                "transaction_date": nowdate(),
            },
        )
        self._persist_doc(member_doc)
        frappe.db.commit()

        # Sanity: the row exists with the reference.
        rows = frappe.db.sql(
            "SELECT name FROM `tabMember Payment History` WHERE invoice=%s AND invoice_doctype='Sales Invoice'",
            (invoice_name,),
        )
        self.assertTrue(rows, "precondition: payment history row should reference the invoice")

        frappe.delete_doc("Sales Invoice", invoice_name, force=True, ignore_permissions=True)
        frappe.db.commit()

        cleared = frappe.db.sql(
            "SELECT invoice, invoice_doctype FROM `tabMember Payment History` WHERE invoice=%s",
            (invoice_name,),
        )
        self.assertEqual(cleared, (), "invoice reference in payment history must be cleared")
