"""#2456 (maintainer ruling 2026-11-25): a plain member may leave their OWN chapter.

`Chapter.leave_chapter` was @high_security_api, which a bare "Verenigingen Member" (role
profile maps to LOW only) never clears, so the endpoint body was unreachable for the people
it exists for. It is now @self_service_api: any authenticated user passes the tier and the
body refuses every target but the caller's own member unless the caller holds a
Roles.ADMIN_ROLES role (ruling: staff may act for a member).

Callers are real users: a plain Verenigingen Member (NO role profile), the "Verenigingen
Staff" profile, and a Chapter Board Member. Probe shortcut: member status is set with
db_set (stand-in for a suspension flow) in the non-Active test only.
"""

import frappe

from verenigingen.setup.role_profile_setup import assign_role_profile_to_user
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.chapter.chapter import leave_chapter


REFUSED_2456 = {"success": False, "removed": False}


class TestPlainMemberLeavesOwnChapter2456(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter(
            chapter_name=f"TEST 2456 Chapter {frappe.generate_hash()[:6]}", region="Test Region 2456"
        )
        self.me = self._plain_member_2456("Own")
        self.other = self._plain_member_2456("Other")
        self.add_member_to_test_chapter(self.me.member.name, self.chapter.name)
        self.add_member_to_test_chapter(self.other.member.name, self.chapter.name)

    def _plain_member_2456(self, last_name, profile=None):
        email = f"lv2456-{frappe.generate_hash()[:8]}@example.com"
        member = self.create_test_member(
            first_name="Lv", last_name=last_name, email=email, birth_date="1990-01-01"
        )
        member.db_set("status", "Active")
        self.create_test_user_with_roles(email=email, roles=["Verenigingen Member"])
        member.db_set("user", email)
        if profile:
            assign_role_profile_to_user(email, profile)
        return frappe._dict(member=member, user=email)

    def _row_2456(self, member):
        return frappe.db.get_value(
            "Chapter Member",
            {"parent": self.chapter.name, "member": member.name},
            ["status", "enabled"],
            as_dict=True,
        )

    def _leave_2456(self, caller, member_name):
        """Return (outcome, message_log added by the call, Error Log delta); outcome is the
        response, or (exception type, text) when the call raised (Guest)."""
        frappe.local.message_log = []
        errors_before = frappe.db.count("Error Log")
        try:
            with self.as_user(caller.user):
                outcome = leave_chapter(
                    member_name=member_name, chapter_name=self.chapter.name, leave_reason="moving"
                )
        except frappe.PermissionError as exc:
            outcome = (type(exc).__name__, str(exc))
        return outcome, list(frappe.local.message_log), frappe.db.count("Error Log") - errors_before

    def test_caller_is_plain_member(self):
        """Precondition: no role profile, no Chapter write, so only the tier change can admit."""
        with self.as_user(self.me.user):
            self.assertFalse(frappe.has_permission("Chapter", "write", doc=self.chapter.name))
        self.assertFalse(frappe.get_all("Has Role", filters={"parent": self.me.user, "role": "Verenigingen Staff"}))
        self.assertFalse(frappe.db.get_value("User", self.me.user, "role_profile_name"))

    def test_endpoint_is_whitelisted(self):
        self.assertIsNone(frappe.is_whitelisted(leave_chapter))  # raises PermissionError when refused
        self.assertIn(leave_chapter, frappe.whitelisted)

    def test_plain_member_leaves_own_chapter(self):
        outcome, _log, _errors = self._leave_2456(self.me, self.me.member.name)
        self.assertEqual(outcome, {"success": True, "removed": True})
        self.assertEqual(self._row_2456(self.me.member).enabled, 0)

    def test_plain_member_cannot_leave_for_another_member(self):
        outcome, _log, _errors = self._leave_2456(self.me, self.other.member.name)
        self.assertEqual(outcome, REFUSED_2456)
        row = self._row_2456(self.other.member)
        self.assertEqual((row.status, row.enabled), ("Active", 1))

    def test_forbidden_and_unknown_member_are_refused_identically(self):
        """Compared on exception type, text, message_log and Error Log delta; the caller has
        no blanket Member access."""
        forbidden = self._leave_2456(self.me, self.other.member.name)
        unknown = self._leave_2456(self.me, "Assoc-Member-DOES-NOT-EXIST-2456")
        self.assertEqual(forbidden[0], REFUSED_2456)
        self.assertEqual(forbidden, unknown)

    def test_staff_profile_user_leaves_own_chapter(self):
        staff = self._plain_member_2456("Staff", profile="Verenigingen Staff")
        self.add_member_to_test_chapter(staff.member.name, self.chapter.name)
        outcome, _log, _errors = self._leave_2456(staff, staff.member.name)
        self.assertEqual(outcome, {"success": True, "removed": True})
        self.assertEqual(self._row_2456(staff.member).enabled, 0)

    def test_staff_leaving_for_another_member_is_allowed(self):
        """Maintainer ruling on #2456 (2026-11-25, per #1101): staff (Roles.ADMIN_ROLES) may leave a
        chapter on a member's behalf. The staff user is a member of nothing here."""
        staff = self._plain_member_2456("Staff2", profile="Verenigingen Staff")
        outcome, _log, _errors = self._leave_2456(staff, self.other.member.name)
        self.assertEqual(outcome, {"success": True, "removed": True})
        self.assertEqual(self._row_2456(self.other.member).enabled, 0)

    def test_board_member_who_is_not_staff_cannot_leave_for_another_member(self):
        board = self._plain_member_2456("Board", profile="Verenigingen Chapter Board Member")
        outcome, _log, _errors = self._leave_2456(board, self.other.member.name)
        self.assertEqual(outcome, REFUSED_2456)
        self.assertEqual(self._row_2456(self.other.member).enabled, 1)

    def test_guest_is_refused(self):
        outcome, _log, _errors = self._leave_2456(frappe._dict(user="Guest"), self.other.member.name)
        self.assertIsInstance(outcome, tuple, outcome)
        self.assertEqual(self._row_2456(self.other.member).enabled, 1)

    def test_non_member_user_is_refused(self):
        email = f"nm2456-{frappe.generate_hash()[:8]}@example.com"
        self.create_test_user_with_roles(email=email, roles=["Verenigingen Member"])
        outcome, _log, _errors = self._leave_2456(frappe._dict(user=email), self.other.member.name)
        self.assertEqual(outcome, REFUSED_2456)
        self.assertEqual(self._row_2456(self.other.member).enabled, 1)

    def test_non_active_member_may_leave_own_chapter(self):
        """#2166 stays true for the plain-member path."""
        self.me.member.db_set("status", "Suspended")
        outcome, _log, _errors = self._leave_2456(self.me, self.me.member.name)
        self.assertEqual(outcome, {"success": True, "removed": True})
