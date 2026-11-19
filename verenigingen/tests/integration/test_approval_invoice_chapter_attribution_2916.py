"""#2916: the approval invoice is created AFTER the applicant's Pending chapter row is Active.

Every attribution reader (sales_invoice_hooks, invoice_generator, dues_payment_processor and the
`custom_member_chapter` hook) resolves the chapter through `get_member_primary_chapter`, which counts only an
Active Chapter Member row. Approval used to create the first invoice and activate the row afterwards, so the
first invoice carried `custom_member_chapter=None` and `cost_center=None`.

Real flow throughout: submit_application -> confirm -> approve_application with create_invoice=True. The
expected chapter is the fixture's. Cost center: the approval invoice builder never sets one from the chapter
(item cost center comes from ERPNext's default and the header is never set), so it is NOT asserted here; see
the issue thread. The failing-invoice test breaks invoicing the way test_approval_without_invoice does
(Verenigingen Settings names a company that does not exist).
"""

from unittest.mock import patch

import frappe

from verenigingen.tests.integration.test_application_record_approval import ApprovalCase


class TestApprovalInvoiceChapterAttribution(ApprovalCase):
    def _first_invoice(self, member_name):
        invoices = frappe.get_all(
            "Sales Invoice",
            {"customer": frappe.db.get_value("Member", member_name, "customer")},
            ["name", "custom_member_chapter"],
        )
        self.assertEqual(len(invoices), 1, "premise: approval created exactly one invoice")
        return invoices[0]

    def _assert_first_invoice_attributed(self, name, result):
        self.assertTrue(result["success"], result)
        member = frappe.db.get_value("Membership Application Submission", name, "member")
        invoice = self._first_invoice(member)
        self.assertEqual(invoice.custom_member_chapter, self.chapter.name)
        return member, invoice

    def test_first_invoice_carries_the_applied_chapter_as_administrator(self):
        name = self._stage_and_confirm()

        result = self._approve_as(name, create_invoice=True)

        self._assert_first_invoice_attributed(name, result)

    def test_first_invoice_carries_the_applied_chapter_as_a_board_approver(self):
        board = self.create_test_board_member(self.chapter.name, permissions_level="Admin")
        name = self._stage_and_confirm()

        result = self._approve_as(name, user=board.user, create_invoice=True)

        self._assert_first_invoice_attributed(name, result)

    def _row_status(self, member_name):
        return frappe.db.get_value(
            "Chapter Member", {"parent": self.chapter.name, "member": member_name}, "status"
        )

    def test_approval_without_an_invoice_still_activates_the_row(self):
        name = self._stage_and_confirm()

        result = self._approve_as(name, create_invoice=False)

        self.assertTrue(result["success"], result)
        self.assertEqual(self._row_status(result["member"]), "Active")

    def test_a_failed_core_leaves_the_row_pending(self):
        """The row is now activated BEFORE the core; a core that raises must roll that back."""
        from verenigingen.services.member.approval.membership_creation_service import MembershipCreationService

        name = self._stage_and_confirm()
        # Mock justified: failure injection at the core boundary; everything before it is real.
        with patch.object(
            MembershipCreationService, "create_membership_on_approval", side_effect=frappe.ValidationError("boom")
        ):
            with self.assertRaises(frappe.ValidationError):
                self._approve_as(name, create_invoice=True)

        member = frappe.db.get_value("Member", {"email": self.email}, "name")
        self.assertFalse(
            member and frappe.db.exists("Chapter Member", {"member": member, "status": "Active"}),
            "no Active chapter row survives a failed approval",
        )

    def test_a_failed_invoice_keeps_the_row_active_and_the_retry_invoice_carries_the_chapter(self):
        from verenigingen.api.membership_application_review import retry_application_invoice

        name = self._stage_and_confirm()
        company = frappe.db.get_single_value("Verenigingen Settings", "company")
        frappe.db.set_single_value("Verenigingen Settings", "company", "No Such Company 2916")
        self.addCleanup(frappe.db.set_single_value, "Verenigingen Settings", "company", company)
        self.expectErrorLog(
            "Membership Invoice Creation Failed",
            "Membership Invoice Security",
            "BTW Tax Exemption Error",
            "Secure Operation Failed",
        )
        result = self._approve_as(name, create_invoice=True)
        self.assertTrue(result["invoice_failed"], result)
        self.assertEqual(self._row_status(result["member"]), "Active")
        frappe.db.set_single_value("Verenigingen Settings", "company", company)

        with self.as_user(self.admin_user.email):
            # Mock justified: External Service - SMTP delivery, not business logic
            with patch("frappe.sendmail"):
                retry = retry_application_invoice(name)

        self.assertTrue(retry["invoice"], retry)
        self.assertEqual(
            frappe.db.get_value("Sales Invoice", retry["invoice"], "custom_member_chapter"), self.chapter.name
        )

    def test_the_applied_chapter_row_is_already_active_when_the_core_runs(self):
        """Pins the ORDER the maintainer ruled (#2916): activate first. The attribution outcome alone is also
        met by the ruled-out fix (widening get_member_primary_chapter to count Pending rows), so the row's
        state at the core's entry is what tells the two apart."""
        from verenigingen.services.member.approval.membership_creation_service import MembershipCreationService

        seen = []
        real = MembershipCreationService.create_membership_on_approval

        def wrapper(service, member_doc, *args, **kwargs):
            seen.append(self._row_status(member_doc.name))
            return real(service, member_doc, *args, **kwargs)

        name = self._stage_and_confirm()
        # Mock justified: pass-through spy on the core's entry; the real function still runs.
        with patch.object(
            MembershipCreationService, "create_membership_on_approval", autospec=True, side_effect=wrapper
        ):
            result = self._approve_as(name, create_invoice=True)

        self.assertTrue(result["success"], result)
        self.assertEqual(seen, ["Active"], "the Pending row is Active before the first invoice is created")
