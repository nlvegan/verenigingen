"""#2166: a member's OWN leave works without Chapter:write; nobody else's does.

`Chapter.leave_chapter` (whitelisted) identifies the caller by Member.user (#2069,
#1853) and then ran the Chapter save as that caller, so a Chapter Board Member
profile user without Chapter:write on that chapter was refused for their own row. Callers here are
real users with the real "Verenigingen Chapter Board Member" role profile (the least-privileged
profile that clears @high_security_api; a plain Verenigingen Member is refused by that tier gate
before any check under test, measured: PermissionError).
"""

import frappe

from verenigingen.setup.role_profile_setup import assign_role_profile_to_user
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.services.chapter.chapter_membership_manager import ChapterMembershipManager
from verenigingen.verenigingen.doctype.chapter.chapter import leave_chapter


class TestChapterOwnRowLeaveAndRejoin(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter(
            chapter_name=f"TEST 2166 Chapter {frappe.generate_hash()[:6]}", region="Test Region 2166"
        )
        self.me = self._member_user_2166("Own")
        self.other = self._member_user_2166("Other")
        self.add_member_to_test_chapter(self.me.member.name, self.chapter.name)
        self.add_member_to_test_chapter(self.other.member.name, self.chapter.name)

    def _member_user_2166(self, last_name):
        email = f"lv2166-{frappe.generate_hash()[:8]}@example.com"
        member = self.create_test_member(
            first_name="Lv", last_name=last_name, email=email, birth_date="1990-01-01"
        )
        member.db_set("status", "Active")
        self.create_test_user_with_roles(email=email, roles=["Verenigingen Member"])
        member.db_set("user", email)
        assign_role_profile_to_user(email, "Verenigingen Chapter Board Member")
        return frappe._dict(member=member, user=email)

    def _row_2166(self, member):
        return frappe.db.get_value(
            "Chapter Member",
            {"parent": self.chapter.name, "member": member.name},
            ["status", "enabled"],
            as_dict=True,
        )

    def _call_leave(self, caller, member_name):
        """Return (response, message_log tail added by the call, Error Log row count delta)."""
        frappe.local.message_log = []
        errors_before = frappe.db.count("Error Log")
        with self.as_user(caller.user):
            response = leave_chapter(member_name, self.chapter.name, "moving")
        return response, list(frappe.local.message_log), frappe.db.count("Error Log") - errors_before

    def test_caller_has_no_chapter_write(self):
        """Precondition: the fix is not just 'caller already may write the chapter'."""
        with self.as_user(self.me.user):
            self.assertFalse(frappe.has_permission("Chapter", "write", doc=self.chapter.name))

    def test_member_leaves_own_row_without_chapter_write(self):
        response, _log, _errors = self._call_leave(self.me, self.me.member.name)
        self.assertEqual(response, {"success": True, "removed": True})
        self.assertEqual(self._row_2166(self.me.member).enabled, 0)

    def test_member_cannot_leave_for_another_member(self):
        """The forbidden id (a real Active row) is refused and its row untouched."""
        response, _log, _errors = self._call_leave(self.me, self.other.member.name)
        self.assertEqual(response, {"success": False, "removed": False})
        row = self._row_2166(self.other.member)
        self.assertEqual((row.status, row.enabled), ("Active", 1))

    def test_forbidden_and_unknown_member_are_refused_identically(self):
        forbidden = self._call_leave(self.me, self.other.member.name)
        unknown = self._call_leave(self.me, "Assoc-Member-DOES-NOT-EXIST-2166")
        self.assertEqual(forbidden, unknown)

    def test_manager_default_does_not_elevate(self):
        """Control: remove_member keeps its permission check unless the caller was proved the member."""
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)
        with self.as_user(self.me.user):
            with self.assertRaises(frappe.PermissionError):
                chapter_doc.member_manager.remove_member(self.me.member.name, leave_reason="x")
        self.assertEqual(self._row_2166(self.me.member).enabled, 1)

    def test_proved_caller_is_false_for_internal_callers(self):
        self.assertFalse(ChapterMembershipManager._proved_member_caller(None))
        self.assertFalse(ChapterMembershipManager._proved_member_caller(""))
        self.assertFalse(ChapterMembershipManager._proved_member_caller("Administrator"))
        self.assertTrue(ChapterMembershipManager._proved_member_caller(self.me.user))

    def test_internal_caller_without_user_does_not_elevate(self):
        """user_email=None is trusted by the identity gate but must keep its own permissions."""
        with self.as_user(self.me.user):
            result = ChapterMembershipManager.leave_chapter(
                member_id=self.me.member.name, chapter_name=self.chapter.name, leave_reason="x"
            )
        self.assertFalse(result["success"], result)
        self.assertEqual(self._row_2166(self.me.member).enabled, 1)

    def test_non_active_member_may_leave_own_row(self):
        """Maintainer ruling 2026-11-07: a non-Active member may leave their own chapter.

        Probe shortcut: status is set with db_set (stand-in for a suspension flow).
        """
        self.me.member.db_set("status", "Suspended")
        response, _log, _errors = self._call_leave(self.me, self.me.member.name)
        self.assertEqual(response, {"success": True, "removed": True})
