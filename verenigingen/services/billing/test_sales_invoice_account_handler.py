# -*- coding: utf-8 -*-
"""
Integration tests for
verenigingen/services/billing/sales_invoice_account_handler.py

This module is wired as a Sales Invoice ``validate`` doc_event
(verenigingen/hooks/doc_events.py:157), so the tests drive it through the REAL
hook pipeline by saving genuine Sales Invoice documents via the factory and
asserting the resulting ``debit_to`` field, rather than calling the handler
with hand-built mock docs (which only exercised the early-return guards and
left the actual account-override body — the bulk of the module — uncovered).

What set_membership_receivable_account does:
  When a Sales Invoice's debit_to equals the Company default receivable account
  AND the invoice looks membership-related (membership item group, membership
  item name, customer linked to a Member, or membership remarks), it overrides
  debit_to with Verenigingen Payments Settings.dues_payments_receivable_account
  — but ONLY when that account belongs to the same company (company-mismatch
  guard added to avoid GL errors in multi-company setups / tests).

ISOLATION:
  Each test mutates the single Verenigingen Payments Settings doc; setUp
  snapshots dues_payments_receivable_account and tearDown restores it. Invoices
  are created as drafts (not submitted) so FrappeTestCase's transaction rollback
  reclaims them; any explicitly committed rows are force-deleted in tearDown.
"""

import frappe
from frappe.utils import nowdate

from verenigingen.services.billing.sales_invoice_account_handler import (
    set_membership_receivable_account,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestSalesInvoiceAccountHandler(EnhancedTestCase):
    COMPANY = "_Test Company"
    COMPANY_DEFAULT_RECEIVABLE = "Debtors - _TC"
    DUES_RECEIVABLE = "_Test Receivable - _TC"
    INCOME_ACCOUNT = "Test Sales Income - _TC"

    def setUp(self):
        super().setUp()
        self._tracked = []  # (doctype, name) force-deleted in tearDown
        # Snapshot the one Settings field the handler reads.
        self._orig_dues_acct = frappe.db.get_single_value(
            "Verenigingen Payments Settings", "dues_payments_receivable_account"
        )

    def tearDown(self):
        # Restore Settings.
        frappe.db.set_value(
            "Verenigingen Payments Settings",
            "Verenigingen Payments Settings",
            "dues_payments_receivable_account",
            self._orig_dues_acct,
        )
        frappe.clear_document_cache("Verenigingen Payments Settings", "Verenigingen Payments Settings")
        for doctype, name in reversed(self._tracked):
            if frappe.db.exists(doctype, name):
                try:
                    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
                except Exception:
                    pass
        frappe.db.commit()
        super().tearDown()

    # ------------------------------------------------------------------
    # Fixture helpers
    # ------------------------------------------------------------------
    def _insert_doc(self, doc):
        """Insert a fixture/test doc through the real save pipeline (runs hooks)."""
        doc.insert(ignore_permissions=True)
        return doc

    def _ensure_item_group(self, name):
        """Get-or-create an Item Group the test depends on.

        CI seeds a fresh site that lacks the membership Item Groups the handler
        keys on (``set_membership_receivable_account`` matches item_group against
        ["Membership", "Contributie", "Lidmaatschap"]), so the test must create
        them rather than assume dev-site data exists. Created (not committed) so
        FrappeTestCase's transaction rollback reclaims it.
        """
        if not frappe.db.exists("Item Group", name):
            ig = frappe.new_doc("Item Group")
            ig.item_group_name = name
            ig.parent_item_group = "All Item Groups"
            ig.is_group = 0
            ig.insert(ignore_permissions=True)
            self._tracked.append(("Item Group", name))
        return name

    def _set_dues_account(self, account):
        frappe.db.set_value(
            "Verenigingen Payments Settings",
            "Verenigingen Payments Settings",
            "dues_payments_receivable_account",
            account,
        )
        frappe.clear_document_cache("Verenigingen Payments Settings", "Verenigingen Payments Settings")

    def _make_customer(self, with_member=False):
        cust = frappe.new_doc("Customer")
        cust.customer_name = f"SIAH Cust {frappe.generate_hash(length=8)}"
        cust.customer_type = "Individual"
        cust.customer_group = "Individual"
        cust.territory = "Netherlands"
        cust.insert(ignore_permissions=True)
        self._tracked.append(("Customer", cust.name))

        if with_member:
            member = frappe.new_doc("Member")
            member.first_name = "SIAH"
            member.last_name = f"M{frappe.generate_hash(length=6)}"
            member.email = f"siah.{frappe.generate_hash(length=8)}@example.com"
            member.member_since = nowdate()
            member.customer = cust.name
            member.save()
            self._tracked.append(("Member", member.name))
        return cust

    def _build_invoice(
        self,
        customer,
        item_name="Generic Service",
        item_group="Services",
        remarks=None,
        debit_to=None,
    ):
        """Build (not insert) a Sales Invoice draft for _Test Company.

        Currency is taken from the company default so it matches the receivable
        account currency (ERPNext rejects a party-account currency mismatch).
        """
        currency = frappe.db.get_value("Company", self.COMPANY, "default_currency")
        cost_center = frappe.db.get_value("Company", self.COMPANY, "cost_center")
        # Ensure the linked Item Group exists (CI seeds a bare site).
        self._ensure_item_group(item_group)
        doc = frappe.get_doc(
            {
                "doctype": "Sales Invoice",
                "company": self.COMPANY,
                "currency": currency,
                "conversion_rate": 1.0,
                "debit_to": debit_to if debit_to is not None else self.COMPANY_DEFAULT_RECEIVABLE,
                "customer": customer,
                "posting_date": nowdate(),
                "due_date": nowdate(),
                "remarks": remarks,
                "items": [
                    {
                        "item_name": item_name,
                        "item_group": item_group,
                        "qty": 1,
                        "rate": 10,
                        "uom": "Nos",
                        "income_account": self.INCOME_ACCOUNT,
                        "cost_center": cost_center,
                    }
                ],
            }
        )
        return doc

    # ==================================================================
    # Positive override paths (the previously-uncovered module body)
    # ==================================================================
    def test_override_applied_for_membership_item_group(self):
        """A non-default-debtors membership invoice gets its debit_to flipped to
        the dues receivable account when item_group is a membership group."""
        self._set_dues_account(self.DUES_RECEIVABLE)
        cust = self._make_customer()
        doc = self._build_invoice(cust.name, item_name="Annual Fee", item_group="Membership")
        self._insert_doc(doc)  # runs the validate hook
        self._tracked.append(("Sales Invoice", doc.name))
        self.assertEqual(doc.debit_to, self.DUES_RECEIVABLE)

    def test_override_applied_for_membership_item_name_keyword(self):
        """Item NAME containing a membership keyword (e.g. 'dues') triggers the
        override even when item_group is generic."""
        self._set_dues_account(self.DUES_RECEIVABLE)
        cust = self._make_customer()
        doc = self._build_invoice(cust.name, item_name="Membership Dues Q1", item_group="Services")
        self._insert_doc(doc)
        self._tracked.append(("Sales Invoice", doc.name))
        self.assertEqual(doc.debit_to, self.DUES_RECEIVABLE)

    def test_override_applied_when_customer_linked_to_member(self):
        """A plain (non-membership) item still triggers the override when the
        customer is linked to a Member record (detection Method 2)."""
        self._set_dues_account(self.DUES_RECEIVABLE)
        cust = self._make_customer(with_member=True)
        doc = self._build_invoice(cust.name, item_name="Generic Service", item_group="Services")
        self._insert_doc(doc)
        self._tracked.append(("Sales Invoice", doc.name))
        self.assertEqual(doc.debit_to, self.DUES_RECEIVABLE)

    def test_override_applied_via_remarks_keyword(self):
        """Remarks mentioning membership trigger the override (detection Method 3)
        when neither items nor customer match."""
        self._set_dues_account(self.DUES_RECEIVABLE)
        cust = self._make_customer()
        doc = self._build_invoice(
            cust.name,
            item_name="Generic Service",
            item_group="Services",
            remarks="Payment for lidmaatschap 2026",
        )
        self._insert_doc(doc)
        self._tracked.append(("Sales Invoice", doc.name))
        self.assertEqual(doc.debit_to, self.DUES_RECEIVABLE)

    # ==================================================================
    # Negative paths — override must NOT happen
    # ==================================================================
    def test_no_override_for_non_membership_invoice(self):
        """A purely generic invoice (no membership signal anywhere) keeps the
        company default receivable account."""
        self._set_dues_account(self.DUES_RECEIVABLE)
        cust = self._make_customer()
        doc = self._build_invoice(
            cust.name, item_name="Consulting Service", item_group="Services", remarks="Project work"
        )
        self._insert_doc(doc)
        self._tracked.append(("Sales Invoice", doc.name))
        self.assertEqual(doc.debit_to, self.COMPANY_DEFAULT_RECEIVABLE)

    def test_no_override_when_debit_to_not_company_default(self):
        """If debit_to is already a non-default receivable account, the handler
        leaves it alone (the 'only override the company default' guard)."""
        self._set_dues_account(self.DUES_RECEIVABLE)
        cust = self._make_customer()
        # Use a different receivable that is NOT the company default.
        doc = self._build_invoice(
            cust.name,
            item_name="Annual Fee",
            item_group="Membership",
            debit_to="Advance Received - _TC",
        )
        self._insert_doc(doc)
        self._tracked.append(("Sales Invoice", doc.name))
        self.assertEqual(doc.debit_to, "Advance Received - _TC")

    def test_no_override_when_settings_account_empty(self):
        """With no dues_payments_receivable_account configured, even a clear
        membership invoice keeps the company default (early-return guard)."""
        self._set_dues_account(None)
        cust = self._make_customer()
        doc = self._build_invoice(cust.name, item_name="Annual Fee", item_group="Membership")
        self._insert_doc(doc)
        self._tracked.append(("Sales Invoice", doc.name))
        self.assertEqual(doc.debit_to, self.COMPANY_DEFAULT_RECEIVABLE)

    def test_no_override_when_dues_account_belongs_to_other_company(self):
        """Company-mismatch guard: a dues account in a DIFFERENT company must not
        be applied (would otherwise produce a GL company-mismatch error). The
        invoice keeps the company default and the handler returns cleanly."""
        # Pick a receivable account that belongs to a different company.
        other_acct = frappe.db.get_value(
            "Account",
            {"account_type": "Receivable", "is_group": 0, "company": ["!=", self.COMPANY]},
            "name",
        )
        self.assertTrue(other_acct, "need a receivable account in another company for this test")
        self._set_dues_account(other_acct)
        cust = self._make_customer()
        doc = self._build_invoice(cust.name, item_name="Annual Fee", item_group="Membership")
        self._insert_doc(doc)
        self._tracked.append(("Sales Invoice", doc.name))
        # Override skipped -> still the company default.
        self.assertEqual(doc.debit_to, self.COMPANY_DEFAULT_RECEIVABLE)

    # ==================================================================
    # Direct early-return guard (debit_to unset) — no DB needed
    # ==================================================================
    def test_handler_returns_early_when_no_debit_to(self):
        """Direct call: when debit_to is falsy the handler returns immediately
        and does not touch the doc. Verified by leaving debit_to None."""
        doc = self._build_invoice("nonexistent", debit_to=None)
        doc.debit_to = None
        set_membership_receivable_account(doc)
        self.assertIsNone(doc.debit_to)

    def test_handler_skips_when_company_not_found(self):
        """Defensive guard: when the invoice's company does not exist the handler
        logs and returns without mutating debit_to. This branch is unreachable via
        a saved invoice (you cannot save one for a missing company), so it is
        exercised by a direct call on a real-attribute draft whose company was
        overwritten to a non-existent value. Settings have a valid dues account,
        so reaching the (failing) company lookup is the only way to bail out.
        """
        self._set_dues_account(self.DUES_RECEIVABLE)
        # frappe.new_doc gives a real Document we set the minimal attrs on; we do
        # NOT save it (the company doesn't exist), we only drive the handler.
        doc = frappe.new_doc("Sales Invoice")
        doc.debit_to = self.DUES_RECEIVABLE
        doc.company = "NONEXISTENT-COMPANY-ZZZ"
        doc.customer = None
        doc.remarks = "membership dues"  # would trigger detection if it got that far
        self.expectErrorLog()
        set_membership_receivable_account(doc)
        # Untouched — bailed out at the company lookup.
        self.assertEqual(doc.debit_to, self.DUES_RECEIVABLE)
