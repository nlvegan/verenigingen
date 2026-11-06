"""#2021: a member who is not Active cannot request to join a chapter.

Maintainer ruling 2026-11-04: any Member.status other than Active is refused at WRITE time by both
Chapter.join_chapter (whitelisted) and member_manager.request_to_join, matching
Chapter Join Request.validate, so no Pending Chapter Member row is ever written for them.

Writer table for Pending / enabled=0 Chapter Member rows (which are in scope):
- Chapter.join_chapter -> ChapterMembershipManager.join_chapter -> request_to_join: Pending/enabled=1.
  IN SCOPE (the only production caller of request_to_join; refused here for non-Active).
- request_to_join rejoin branch (Inactive+enabled -> Pending): same function, now behind the same guard.
- application_helpers.create_pending_chapter_membership (application/approval flow): Pending row for a not-yet-
  approved applicant. NOT touched, and driven below to prove it still works.
- member_manager.add_member: writes Inactive/enabled=0 for a non-Active member, never Pending. Out of scope.
- templates/pages/chapter_join.py portal page: writes Inactive/enabled=0 for non-Active. Out of scope.

Probe shortcuts, stated: Banned/Quit/Deceased/Rejected/Expired/Pending are set with db_set (no real flow is
driven for each); Suspended is reached through the real suspension API (suspend_member). The caller is the
member's own linked user (a least-privileged real caller), not Administrator.
"""

import frappe

from verenigingen.api.suspension_api import suspend_member
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.application_helpers import create_pending_chapter_membership
from verenigingen.verenigingen.doctype.chapter.chapter import join_chapter

NON_ACTIVE = ("Pending", "Rejected", "Expired", "Suspended", "Banned", "Deceased", "Quit")


class TestJoinChapterRefusesNonActiveMember(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.home = self.ensure_test_chapter("TEST Home 2021")
        self.target = self.ensure_test_chapter("TEST Join Target 2021")
        # A real, non-admin member user (Member.user linked), seated on a different chapter.
        self.seat = self.create_test_board_member(self.home.name, permissions_level="Basic")
        self.member_name = self.seat.member if isinstance(self.seat.member, str) else self.seat.member.name

    def _rows(self):
        return frappe.get_all(
            "Chapter Member",
            filters={"parent": self.target.name, "member": self.member_name},
            fields=["status", "enabled"],
        )

    def _join_as_member(self, **kwargs):
        with self.as_user(self.seat.user):
            return join_chapter(
                member_name=self.member_name, chapter_name=self.target.name, introduction="hi", **kwargs
            )

    def test_active_member_still_requests_to_join(self):
        """Control / opposite-harm: an Active member's request still writes its Pending row."""
        self.assertEqual(frappe.db.get_value("Member", self.member_name, "status"), "Active")
        result = self._join_as_member()
        self.assertTrue(result.get("success"), result)
        self.assertEqual([(r.status, r.enabled) for r in self._rows()], [("Pending", 1)])

    def test_suspended_via_real_api_is_refused_with_message_and_no_row(self):
        with self.as_user("Administrator"):
            self.expectErrorLog()
            suspended = suspend_member(
                self.member_name, "test #2021", suspend_user=False, suspend_teams=False
            )
        self.assertTrue(suspended.get("success"), suspended)
        self.assertEqual(frappe.db.get_value("Member", self.member_name, "status"), "Suspended")

        result = self._join_as_member()

        self.assertFalse(result.get("success"), result)
        self.assertIn("active members", str(result.get("message")), result)
        self.assertEqual(self._rows(), [], "no Chapter Member row may be written")

    def test_every_non_active_status_is_refused_at_both_entry_points(self):
        for status in NON_ACTIVE:
            with self.subTest(status=status):
                frappe.db.set_value("Member", self.member_name, "status", status)
                result = self._join_as_member()
                self.assertFalse(result.get("success"), result)
                direct = self.target.member_manager.request_to_join(self.member_name, notify=False)
                self.assertFalse(direct.get("success"), direct)
                self.assertEqual(direct.get("action"), "not_active", direct)
                self.assertEqual(self._rows(), [])

    def test_refusal_does_not_disclose_the_status(self):
        frappe.db.set_value("Member", self.member_name, "status", "Banned")
        result = self._join_as_member()
        self.assertFalse(result.get("success"), result)
        self.assertNotIn("Banned", str(result))

    def _seed_inactive_enabled_row(self):
        """Inactive + enabled=1 row: the state the rejoin branch of request_to_join acts on."""
        self.assertTrue(self._join_as_member().get("success"))
        frappe.db.set_value(
            "Chapter Member", {"parent": self.target.name, "member": self.member_name}, "status", "Inactive"
        )

    def test_rejoin_branch_is_behind_the_guard(self):
        """The rejoin branch is a second writer of a Pending row. Called DIRECTLY (as Administrator),
        because through join_chapter as the member an earlier Chapter:write permission check at the
        rejoin save refuses first and would hide a mis-placed guard."""
        self._seed_inactive_enabled_row()
        frappe.db.set_value("Member", self.member_name, "status", "Suspended")
        self.target.reload()

        result = self.target.member_manager.request_to_join(self.member_name, notify=False)

        self.assertFalse(result.get("success"), result)
        self.assertEqual(result.get("action"), "not_active", result)
        self.assertEqual([r.status for r in self._rows()], ["Inactive"])

    def test_rejoin_via_member_user_of_a_suspended_member_writes_nothing(self):
        """End-to-end as the member's own user. NOT proof of the rejoin guard: another permission
        check refuses this caller first (see test_rejoin_branch_is_behind_the_guard)."""
        self._seed_inactive_enabled_row()
        frappe.db.set_value("Member", self.member_name, "status", "Suspended")
        result = self._join_as_member()
        self.assertFalse(result.get("success"), result)
        self.assertEqual([r.status for r in self._rows()], ["Inactive"])

    def test_application_flow_still_writes_a_pending_row_for_a_pending_applicant(self):
        """Not broken: the application writer is a different function and keeps working."""
        applicant = self.create_test_member(first_name="Applicant2021", status="Pending")
        create_pending_chapter_membership(applicant, self.target.name)
        row = frappe.db.get_value(
            "Chapter Member", {"parent": self.target.name, "member": applicant.name}, "status"
        )
        self.assertEqual(row, "Pending")
