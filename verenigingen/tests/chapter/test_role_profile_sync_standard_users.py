"""A role-profile sync never touches Frappe's standard users (#694).

``frappe.STANDARD_USERS`` (Administrator, Guest) are refused a role profile by
``User.populate_role_profile_roles``, so there is nothing for a sync to govern. Before the
guard, ``sync_user_role_profile`` still ran ``_ensure_employee_for_profile`` for such an
account, silently inserting an Employee for Administrator when the account was linked to a
Member holding a board seat.

Probe shortcut: ``Member.user`` is set to "Administrator" with ``db_set`` (the Member form
does not offer it). The seat itself is created through the real Chapter save flow.
"""

import frappe

from verenigingen.services.member.account.user_role_profile_calculator import (
    auto_sync_on_role_change,
    sync_user_role_profile,
)
from verenigingen.tests.utils.base import VereningingenTestCase


class TestRoleProfileSyncStandardUsers(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.assertFalse(
            frappe.db.exists("Employee", {"user_id": "Administrator"}),
            "precondition: no Employee for Administrator on this site",
        )
        self.assertFalse(
            frappe.db.exists("Member", {"user": "Administrator"}),
            "precondition: Administrator is not already linked to a Member",
        )

    def tearDown(self):
        for employee in frappe.get_all("Employee", filters={"user_id": "Administrator"}, pluck="name"):
            frappe.delete_doc("Employee", employee, force=True, ignore_permissions=True)
        super().tearDown()

    def _administrator_with_a_board_seat(self):
        """Link a Member+Volunteer to Administrator and seat them through a Chapter save."""
        chapter = self.create_test_chapter(
            chapter_name=f"Std {frappe.generate_hash(length=6)}", postal_codes="3000-3999", published=1
        )
        member = self.create_test_member(
            first_name="Std", last_name="Admin", email=f"std.{frappe.generate_hash(length=8)}@test.invalid",
            status="Active",
        )
        member.db_set("user", "Administrator", update_modified=False)
        volunteer = self.create_test_volunteer(member=member.name)
        role = f"Seat {frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {"doctype": "Chapter Role", "role_name": role, "permissions_level": "Basic", "is_active": 1}
        ).insert()
        self.track_doc("Chapter Role", role)
        self.add_board_member_to_chapter(frappe.get_doc("Chapter", chapter.name), volunteer, role)

    def _employees_for_administrator(self):
        return frappe.get_all("Employee", filters={"user_id": "Administrator"}, pluck="name")

    def test_direct_sync_of_administrator_creates_no_employee(self):
        self._administrator_with_a_board_seat()
        for employee in self._employees_for_administrator():  # the seating flush may already have made it
            frappe.delete_doc("Employee", employee, force=True, ignore_permissions=True)

        result = sync_user_role_profile("Administrator")

        self.assertEqual(self._employees_for_administrator(), [])
        self.assertTrue(result["success"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["skipped"], "standard_user")

    def test_auto_sync_of_administrator_creates_no_employee(self):
        """auto_sync_on_role_change is the event-path entry (team/chapter/volunteer hooks)."""
        self._administrator_with_a_board_seat()
        for employee in self._employees_for_administrator():
            frappe.delete_doc("Employee", employee, force=True, ignore_permissions=True)

        auto_sync_on_role_change("Administrator")

        self.assertEqual(self._employees_for_administrator(), [])

    def test_seating_a_board_member_linked_to_administrator_creates_no_employee(self):
        """The real flow: the Chapter save drains the deferred board profile syncs."""
        self._administrator_with_a_board_seat()

        self.assertEqual(self._employees_for_administrator(), [])

    def test_guest_is_skipped_too(self):
        result = sync_user_role_profile("Guest")

        self.assertEqual(result.get("skipped"), "standard_user")

    def test_an_ordinary_user_is_still_synced(self):
        """Control: the guard is by account, not a blanket skip; a real member still gets a profile."""
        email = f"std.ctl.{frappe.generate_hash(length=8)}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        member = self.create_test_member(first_name="Ctl", last_name="User", email=email, status="Active")
        member.db_set("user", user.name, update_modified=False)

        result = sync_user_role_profile(user.name)

        self.assertTrue(result["success"])
        self.assertNotIn("skipped", result)
        self.assertTrue(result["new_profile"])
