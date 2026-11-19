"""#2944: the approval invoice resolves its cost center exactly as a dues invoice does.

Maintainer ruling (2026-11-19): reuse `InvoiceGenerator._get_cost_center` (chapter cost center first, then the
company fallbacks). The dues generator sets the ITEM cost center only and never the header, so approval follows.

Real flow: submit_application -> confirm -> approve_application with create_invoice=True. Expected values come
from the fixture's chapter. The "no chapter cost center" control clears `Chapter.cost_center` with a direct
`db.set_value` (probe shortcut: it stands in for a chapter that never got one), then compares the approval
invoice with a REAL dues invoice built for the same member.
"""

import frappe
from frappe.utils import add_days, add_months, getdate

from verenigingen.tests.integration.test_application_record_approval import ApprovalCase


class TestApprovalInvoiceCostCenter2944(ApprovalCase):
    def _approve_and_load(self):
        name = self._stage_and_confirm()
        result = self._approve_as(name, create_invoice=True)
        self.assertTrue(result["success"], result)
        member = frappe.db.get_value("Membership Application Submission", name, "member")
        invoices = frappe.get_all(
            "Sales Invoice", {"customer": frappe.db.get_value("Member", member, "customer")}, pluck="name"
        )
        self.assertEqual(len(invoices), 1, "premise: approval created exactly one invoice")
        return member, frappe.get_doc("Sales Invoice", invoices[0])

    def _dues_invoice_item_cost_center(self, member_name, approval_invoice):
        from verenigingen.services.billing.invoice_generator import InvoiceGenerator

        schedule_name = frappe.db.get_value(
            "Membership Dues Schedule", {"member": member_name, "status": "Active"}, "name"
        )
        self.assertTrue(schedule_name, "premise: approval left an Active dues schedule")
        schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)
        # the period right after the one the approval invoice discharges, so the anchor check stays quiet
        start = getdate(add_days(approval_invoice.custom_coverage_end_date, 1))
        result = InvoiceGenerator(schedule).generate_invoice(
            start, add_days(add_months(start, 1), -1), frappe.get_doc("Member", member_name)
        )
        self.assertTrue(result.success, result.error_message)
        return result.data.items[0].cost_center

    def test_item_cost_center_is_the_chapters_and_the_header_stays_unset(self):
        chapter_cc = frappe.db.get_value("Chapter", self.chapter.name, "cost_center")
        self.assertTrue(chapter_cc, "premise: the fixture chapter has its own cost center")
        company_default = frappe.db.get_value(
            "Company", frappe.db.get_single_value("Verenigingen Settings", "company"), "cost_center"
        )
        self.assertNotEqual(chapter_cc, company_default, "premise: chapter and company default differ")

        member, invoice = self._approve_and_load()

        self.assertEqual([i.cost_center for i in invoice.items], [chapter_cc])
        self.assertEqual(
            invoice.cost_center,
            None,
            "the dues generator never sets the header cost center, so approval does not either",
        )
        self.assertEqual(self._dues_invoice_item_cost_center(member, invoice), chapter_cc)

    def test_a_chapter_without_a_cost_center_falls_back_exactly_as_a_dues_invoice_does(self):
        frappe.db.set_value("Chapter", self.chapter.name, "cost_center", None)
        company = frappe.db.get_single_value("Verenigingen Settings", "company")
        company_default = frappe.db.get_value("Company", company, "cost_center")

        member, invoice = self._approve_and_load()

        dues_cc = self._dues_invoice_item_cost_center(member, invoice)
        self.assertTrue(dues_cc, "premise: the dues invoice resolves a fallback")
        self.assertEqual([i.cost_center for i in invoice.items], [dues_cc])
        self.assertEqual(dues_cc, company_default)

    def test_the_staff_retry_invoice_carries_the_chapters_cost_center_too(self):
        """Second path to the approval invoice builder: the #1900 staff retry of a failed approval invoice.
        Invoicing is broken the way test_approval_invoice_chapter_attribution_2916 does it (settings name a
        company that does not exist), then repaired and retried."""
        from unittest.mock import patch

        from verenigingen.api.membership_application_review import retry_application_invoice

        chapter_cc = frappe.db.get_value("Chapter", self.chapter.name, "cost_center")
        self.assertTrue(chapter_cc, "premise: the fixture chapter has its own cost center")
        name = self._stage_and_confirm()
        company = frappe.db.get_single_value("Verenigingen Settings", "company")
        frappe.db.set_single_value("Verenigingen Settings", "company", "No Such Company 2944")
        self.addCleanup(frappe.db.set_single_value, "Verenigingen Settings", "company", company)
        self.expectErrorLog(
            "Membership Invoice Creation Failed",
            "Membership Invoice Security",
            "BTW Tax Exemption Error",
            "Secure Operation Failed",
        )
        result = self._approve_as(name, create_invoice=True)
        self.assertTrue(result["invoice_failed"], result)
        frappe.db.set_single_value("Verenigingen Settings", "company", company)

        with self.as_user(self.admin_user.email):
            # Mock justified: External Service - SMTP delivery, not business logic
            with patch("frappe.sendmail"):
                retry = retry_application_invoice(name)

        self.assertTrue(retry["invoice"], retry)
        items = frappe.get_doc("Sales Invoice", retry["invoice"]).items
        self.assertEqual([i.cost_center for i in items], [chapter_cc])
