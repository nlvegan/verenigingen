"""#3281: approving a disciplinary termination records an Expulsion Report Entry.

The entry is created as a system operation AFTER the approval itself, so an approver who
cannot create the doctype still produces it. Real flow: submit_for_approval, then
approve_request as a real user. Probe shortcuts: none for state; the approver's create
permission is removed with real Custom DocPerm rows (the only way to model "approver
without create" for a role that can otherwise complete an approval); the failure test
injects a fault at Expulsion Report Entry.validate and says so.
"""

from unittest.mock import patch

import frappe
from frappe.utils import today

from verenigingen.services.approval import TerminationApprovalService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.constants import Roles

APPROVER = "approver3281.noentrycreate@verenigingen.test"
OUTSIDER = "outsider3281.member@verenigingen.test"
ERROR_TITLE = "Expulsion report entry not created"


class TestTerminationExpulsionEntry3281(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="Expel",
            last_name="Three",
            email="expel3281@verenigingen.test",
            birth_date="1990-01-01",
        )
        self._strip_entry_create_3281()
        self.approver = self._create_user_3281(APPROVER, [Roles.VERENIGINGEN_ADMIN])
        self.addCleanup(frappe.set_user, "Administrator")

    def _strip_entry_create_3281(self):
        """Real Custom DocPerm rows: Verenigingen Administrator loses create on the entry."""
        from frappe.permissions import update_permission_property

        update_permission_property("Expulsion Report Entry", Roles.VERENIGINGEN_ADMIN, 0, "create", 0)
        frappe.clear_cache(doctype="Expulsion Report Entry")
        self.addCleanup(self._restore_entry_perms_3281)

    def _restore_entry_perms_3281(self):
        frappe.db.delete("Custom DocPerm", {"parent": "Expulsion Report Entry"})
        frappe.clear_cache(doctype="Expulsion Report Entry")

    def _create_user_3281(self, email, roles):
        if frappe.db.exists("User", email):
            frappe.delete_doc("User", email, force=True)
        user = frappe.get_doc(
            {"doctype": "User", "email": email, "first_name": "T", "send_welcome_email": 0}
        ).insert(ignore_permissions=True)
        for role in roles:
            user.add_roles(role)
        return user

    def _pending_request_3281(self, termination_type="Expulsion"):
        request = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": self.member.name,
                "termination_type": termination_type,
                "termination_reason": "Test reason",
                "requested_by": "Administrator",
                "request_date": today(),
                "disciplinary_documentation": "Board resolution",
                "secondary_approver": APPROVER,
            }
        ).insert()
        TerminationApprovalService(request).submit_for_approval()
        return request

    def _entries_3281(self):
        return frappe.get_all(
            "Expulsion Report Entry",
            filters={"member_id": self.member.name},
            fields=["name", "member_name", "chapter_involved", "approved_by", "owner", "expulsion_type"],
        )

    def _approve_as_3281(self, user, request):
        frappe.set_user(user)
        try:
            doc = frappe.get_doc("Membership Termination Request", request.name)
            return TerminationApprovalService(doc).approve_request("approved", "ok")
        finally:
            frappe.set_user("Administrator")

    def test_approver_without_create_permission_still_produces_one_entry(self):
        request = self._pending_request_3281()
        frappe.set_user(APPROVER)
        self.assertFalse(frappe.has_permission("Expulsion Report Entry", "create"))
        frappe.set_user("Administrator")

        self._approve_as_3281(APPROVER, request)

        entries = self._entries_3281()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].member_name, self.member.full_name)
        self.assertEqual(entries[0].expulsion_type, "Expulsion")
        self.assertEqual(entries[0].approved_by, APPROVER)
        self.assertEqual(entries[0].owner, APPROVER)
        expected_chapter = frappe.db.get_value(
            "Chapter Member", {"member": self.member.name, "enabled": 1}, "parent"
        )
        self.assertEqual(entries[0].chapter_involved, expected_chapter)

    def test_repeat_creation_for_same_request_adds_no_duplicate(self):
        request = self._pending_request_3281()
        self._approve_as_3281(APPROVER, request)
        request.reload()

        # The dead handle_approved_status path and a retried approval both reach the helper.
        TerminationApprovalService(request).handle_approved_status()
        TerminationApprovalService(request)._add_to_expulsion_report()
        with self.assertRaises(frappe.ValidationError):
            self._approve_as_3281(APPROVER, request)

        self.assertEqual(len(self._entries_3281()), 1)

    def test_a_different_request_for_the_same_member_gets_its_own_entry(self):
        first = self._pending_request_3281()
        self._approve_as_3281(APPROVER, first)
        second = self._pending_request_3281("Policy Violation")
        self._approve_as_3281(APPROVER, second)

        self.assertEqual(len(self._entries_3281()), 2)

    def test_insert_failure_is_logged_and_the_approval_stands(self):
        request = self._pending_request_3281()
        from verenigingen.verenigingen.doctype.expulsion_report_entry.expulsion_report_entry import (
            ExpulsionReportEntry,
        )

        self.expectErrorLog(ERROR_TITLE, "Secure Operation Failed")
        # Mock justified: fault injection at the entry's own validate; the approval flow, the
        # secure operation and the Error Log write all run for real.
        with patch.object(ExpulsionReportEntry, "validate", side_effect=frappe.ValidationError("injected")):
            with self.assertErrorLog(ERROR_TITLE):
                self._approve_as_3281(APPROVER, request)

        request.reload()
        self.assertEqual(request.status, "Approved")
        self.assertEqual(request.approved_by, APPROVER)
        self.assertEqual(self._entries_3281(), [])

    def test_non_disciplinary_approval_creates_no_entry(self):
        request = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": self.member.name,
                "termination_type": "Voluntary",
                "termination_reason": "Moving away",
                "requested_by": "Administrator",
                "request_date": today(),
                "status": "Pending",
            }
        ).insert()

        # "Voluntary" is not a valid Expulsion type, so a wrongly attempted entry would fail
        # validation and log rather than persist: assert on the log as well as the rows.
        with self.assertNoErrorLog():
            self._approve_as_3281(APPROVER, request)

        request.reload()
        self.assertEqual(request.status, "Approved")
        self.assertEqual(self._entries_3281(), [])

    def test_user_without_approval_role_is_refused_and_no_entry_exists(self):
        request = self._pending_request_3281()
        self._create_user_3281(OUTSIDER, ["Member"] if frappe.db.exists("Role", "Member") else [])

        with self.assertRaises(frappe.ValidationError) as ctx:
            self._approve_as_3281(OUTSIDER, request)
        self.assertIn("does not have permission to approve", str(ctx.exception))

        request.reload()
        self.assertEqual(request.status, "Pending")
        self.assertEqual(self._entries_3281(), [])
