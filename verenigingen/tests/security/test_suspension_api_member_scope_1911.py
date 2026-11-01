"""#1911: the suspension API let any caller who cleared the endpoint's security tier
read, or probe the existence of, ANY member.

- get_suspension_preview (@high_security_api) returned a member's status, linked user
  email, teams and memberships with no member-level check; "Verenigingen Chapter Board
  Member" clears HIGH on its own, so a board member of chapter B could read a member of
  chapter A.
- suspend_member / unsuspend_member / can_suspend_member / bulk_suspend_members checked
  existence BEFORE permission (or let the failed Member load queue a "not found" message),
  so an unknown name and a forbidden name answered differently.

Callers: the least-privileged real ones -- a board member seated on ANOTHER chapter
(refused) and a board member seated on the member's OWN chapter (allowed), plus an
administrator. Seats are built through create_test_board_member (real Volunteer + Chapter
Board Member + role profile), and the member is placed in its chapter with
add_member_to_test_chapter (a real Chapter Member row, no db.set_value shortcut).
"""

import frappe

from verenigingen.api import suspension_api
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.member_ownership_probe_mixin import MemberOwnershipProbeMixin

UNKNOWN = "Member-DOES-NOT-EXIST-1911"


class TestSuspensionApiMemberScope(MemberOwnershipProbeMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.chapter_a = self.create_test_chapter()
        self.chapter_b = self.create_test_chapter()
        self.member = self.create_test_member(
            first_name="Scope", last_name="Target1911", status="Active"
        )
        self.add_member_to_test_chapter(self.member.name, self.chapter_a.name)
        self.own_board = self.create_test_board_member(self.chapter_a.name)
        self.other_board = self.create_test_board_member(self.chapter_b.name)
        self.admin = self._staff_user("Scope1911Admin")
        # suspend/unsuspend/bulk are CRITICAL-tier. A board member only clears HIGH, so the
        # least-privileged real caller that reaches those bodies is a Treasurer profile
        # seated on ANOTHER chapter (no ADMIN_PAIR role, so can_terminate_member is not
        # short-circuited to True).
        from verenigingen.setup.role_profile_setup import assign_role_profile_to_user

        self.treasurer = self.create_test_board_member(self.chapter_b.name).user
        assign_role_profile_to_user(self.treasurer, "Verenigingen Treasurer")

    def _channels(self, call):
        """Run call() and capture every observable channel."""
        log_len = len(frappe.message_log)
        errors_before = frappe.db.count("Error Log")
        try:
            outcome = call()
        except Exception as e:  # noqa: BLE001 - the exception class IS the observation
            outcome = ("raised", type(e).__name__, str(e))
        msgs = [str(m) for m in frappe.message_log[log_len:]]
        del frappe.message_log[log_len:]
        return {
            "outcome": outcome,
            "messages": msgs,
            "errors": frappe.db.count("Error Log") - errors_before,
        }

    def _normalise(self, channels, name):
        """The member name is the caller's own input and may echo; timestamps/exc ids vary per call."""
        import re

        text = re.sub(r"'timestamp': '[^']*'", "'timestamp': <T>", str(channels))
        text = re.sub(r"'__frappe_exc_id': '[^']*'", "'__frappe_exc_id': <ID>", text)
        return text.replace(name, "<NAME>")

    # --- get_suspension_preview ------------------------------------------

    def test_preview_refused_for_board_member_of_another_chapter(self):
        with self.set_user(self.other_board.user):
            self.assertFalse(frappe.has_permission("Member", "read", self.member.name))
            result = suspension_api.get_suspension_preview(member_name=self.member.name)
        self.assertFalse(result["success"], msg=result)
        self.assertNotIn("member_status", str(result))
        self.assertNotIn("user_email", str(result))

    def test_preview_allowed_for_board_member_of_own_chapter(self):
        with self.set_user(self.own_board.user):
            self.assertTrue(frappe.has_permission("Member", "read", self.member.name))
            result = suspension_api.get_suspension_preview(member_name=self.member.name)
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["data"]["member_status"], "Active")

    def test_preview_allowed_for_admin(self):
        with self.set_user(self.admin):
            result = suspension_api.get_suspension_preview(member_name=self.member.name)
        self.assertTrue(result["success"], msg=result)

    def test_preview_unknown_and_forbidden_are_indistinguishable(self):
        self.expectErrorLog("Suspension API Error")
        with self.set_user(self.other_board.user):
            forbidden = self._channels(
                lambda: suspension_api.get_suspension_preview(member_name=self.member.name)
            )
            unknown = self._channels(lambda: suspension_api.get_suspension_preview(member_name=UNKNOWN))
        self.assertFalse(forbidden["outcome"]["success"], msg=forbidden)
        self.assertEqual(
            self._normalise(forbidden, self.member.name), self._normalise(unknown, UNKNOWN)
        )

    # --- suspend / unsuspend / can_suspend / bulk -------------------------

    def test_suspend_unknown_and_forbidden_are_indistinguishable(self):
        self.expectErrorLog("Suspension API Permission Error")
        self.expectErrorLog("Suspension API Validation Error")
        with self.set_user(self.treasurer):
            forbidden = self._channels(
                lambda: suspension_api.suspend_member(self.member.name, "scope test")
            )
            unknown = self._channels(lambda: suspension_api.suspend_member(UNKNOWN, "scope test"))
        self.assertFalse(forbidden["outcome"]["success"], msg=forbidden)
        self.assertEqual(forbidden["outcome"]["error"]["code"], "PERMISSION_DENIED")
        self.assertEqual(
            self._normalise(forbidden, self.member.name), self._normalise(unknown, UNKNOWN)
        )
        self.assertEqual(frappe.db.get_value("Member", self.member.name, "status"), "Active")

    def test_unsuspend_unknown_and_forbidden_are_indistinguishable(self):
        self.expectErrorLog("Suspension API Permission Error")
        self.expectErrorLog("Suspension API Validation Error")
        with self.set_user(self.treasurer):
            forbidden = self._channels(
                lambda: suspension_api.unsuspend_member(self.member.name, "scope test")
            )
            unknown = self._channels(lambda: suspension_api.unsuspend_member(UNKNOWN, "scope test"))
        self.assertFalse(forbidden["outcome"]["success"], msg=forbidden)
        self.assertEqual(forbidden["outcome"]["error"]["code"], "PERMISSION_DENIED")
        self.assertEqual(
            self._normalise(forbidden, self.member.name), self._normalise(unknown, UNKNOWN)
        )

    def test_can_suspend_unknown_and_forbidden_are_indistinguishable(self):
        with self.set_user(self.other_board.user):
            forbidden = self._channels(lambda: suspension_api.can_suspend_member(self.member.name))
            unknown = self._channels(lambda: suspension_api.can_suspend_member(UNKNOWN))
        self.assertFalse(forbidden["outcome"]["data"]["can_suspend"], msg=forbidden)
        self.assertEqual(
            self._normalise(forbidden, self.member.name), self._normalise(unknown, UNKNOWN)
        )

    def test_bulk_unknown_and_forbidden_are_indistinguishable(self):
        with self.set_user(self.treasurer):
            forbidden = self._channels(
                lambda: suspension_api.bulk_suspend_members([self.member.name], "scope test")
            )
            unknown = self._channels(
                lambda: suspension_api.bulk_suspend_members([UNKNOWN], "scope test")
            )
        self.assertEqual(
            self._normalise(forbidden, self.member.name), self._normalise(unknown, UNKNOWN)
        )
        self.assertIn("No permission to suspend", str(forbidden["outcome"]))

    def test_admin_still_gets_does_not_exist_for_unknown(self):
        self.expectErrorLog("Suspension API Validation Error")
        with self.set_user(self.admin):
            result = suspension_api.suspend_member(UNKNOWN, "scope test")
        self.assertEqual(result["error"]["code"], "DOES_NOT_EXIST")
