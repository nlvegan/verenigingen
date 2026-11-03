"""#1964: quick_approve_join_request must not activate the chapter row of a Member that is not Active.

Writer table (who leaves a Pending Chapter Member row, and which Member status it carries):
- application_materialiser -> create_pending_chapter_membership: Member Pending, row Pending, in the SAME
  transaction as the approval that flips both (api/membership_application_review.py, savepoint). Nothing
  committed carries it since #1765/#1855, so a Pending Member with a Pending row is reachable only through
  legacy data or a mid-approval failure; the writer is still driven for real below.
- Chapter.join_chapter -> member_manager.request_to_join: writes a Pending row for ANY Member status (it never
  looks at the status). This is the reachable source for a Suspended (or Quit, ...) member.
- Chapter Join Request: refuses a member that is not Active at validate, so it never writes this row.

Probe shortcuts, stated: `Quit`/`Banned`/`Deceased`/`Rejected`/`Expired` are set with db_set (no real flow is
driven for each); `Suspended` is reached through the real suspension API; `Pending` through the real writer
(create_pending_chapter_membership) on a Member created Pending. The caller is a real board seat built by
create_test_board_member (a Chapter Head), not Administrator.
"""

import re

import frappe

from verenigingen.api import chapter_dashboard_api
from verenigingen.api.suspension_api import suspend_member
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.application_helpers import create_pending_chapter_membership
from verenigingen.verenigingen.doctype.chapter.chapter import join_chapter

UNKNOWN = "Member-DOES-NOT-EXIST-1964"


class TestQuickApproveJoinRequestMemberStatus(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self.ensure_test_chapter("TEST Join Status 1964")
        self.head = self.create_test_board_member(
            self.chapter.name, permissions_level="Admin", role_name="Chapter Head"
        )

    def _join_request_1964(self, **member_fields):
        """A member who has made a real join request (Chapter.join_chapter, no status check) to the chapter."""
        member = self.create_test_member(first_name="JoinStatus1964", **member_fields)
        result = join_chapter(member_name=member.name, chapter_name=self.chapter.name, introduction="join")
        self.assertTrue(result.get("success"), result)
        self.assertEqual(self._row_1964(member.name).status, "Pending", "premise: the request wrote a Pending row")
        return member

    def _row_1964(self, member_name):
        return frappe.db.get_value(
            "Chapter Member",
            {"parent": self.chapter.name, "member": member_name},
            ["status", "enabled"],
            as_dict=True,
        )

    def _approve_1964(self, member_name, **kwargs):
        with self.as_user(self.head.user):
            self.expectErrorLog()
            return chapter_dashboard_api.quick_approve_join_request(member_name, **kwargs)

    # --- controls: an Active member is still approved, whatever application_status carries -------------

    def test_active_member_with_default_application_status_is_approved(self):
        """Control, and the opposite-harm check: a plainly created Active Member carries the DEFAULT
        application_status 'Pending' (measured on test_site_4), so a guard on application_status would
        refuse it. The Member is NOT pinned Approved here."""
        member = self._join_request_1964(status="Active")
        frappe.db.set_value("Member", member.name, "application_status", "Pending")
        self.assertEqual(frappe.db.get_value("Member", member.name, "application_status"), "Pending")

        result = self._approve_1964(member.name, chapter_name=self.chapter.name)

        self.assertTrue(result.get("success"), result)
        self.assertEqual(self._row_1964(member.name).status, "Active")

    # --- refusals -----------------------------------------------------------------------------------

    def test_member_who_never_got_approved_is_not_activated(self):
        """The writer is the real one create_pending_chapter_membership (materialiser)."""
        member = self.create_test_member(first_name="NeverApproved1964", status="Pending")
        member.db_set("application_status", "Pending")
        create_pending_chapter_membership(member, self.chapter.name)
        self.assertEqual(self._row_1964(member.name).status, "Pending")

        for kwargs in ({"chapter_name": self.chapter.name}, {}):
            result = self._approve_1964(member.name, **kwargs)
            self.assertFalse(self._succeeded_1964(result), (kwargs, result))
        self.assertEqual(self._row_1964(member.name).status, "Pending")

    def test_suspended_member_who_requested_to_join_is_not_activated(self):
        """Real flow: suspend through the API, then the (unchecked) real join request, then the approval."""
        member = self.create_test_member(first_name="Suspended1964", status="Active")
        with self.as_user("Administrator"):
            self.expectErrorLog()
            suspended = suspend_member(member.name, "test #1964", suspend_user=False, suspend_teams=False)
        self.assertTrue(suspended.get("success"), suspended)
        self.assertEqual(frappe.db.get_value("Member", member.name, "status"), "Suspended")
        result = join_chapter(member_name=member.name, chapter_name=self.chapter.name, introduction="join")
        self.assertTrue(result.get("success"), result)
        self.assertEqual(self._row_1964(member.name).status, "Pending", "premise: a suspended member's request lands")

        outcome = self._approve_1964(member.name, chapter_name=self.chapter.name)

        self.assertFalse(self._succeeded_1964(outcome), outcome)
        self.assertEqual(self._row_1964(member.name).status, "Pending")

    def test_every_non_active_status_is_refused(self):
        for status in ("Quit", "Banned", "Deceased", "Rejected", "Expired"):
            with self.subTest(status=status):
                member = self._join_request_1964(status="Active")
                member.db_set("status", status)
                outcome = self._approve_1964(member.name, chapter_name=self.chapter.name)
                self.assertFalse(self._succeeded_1964(outcome), outcome)
                self.assertEqual(self._row_1964(member.name).status, "Pending")

    # --- the refusal does not tell the caller the member's status -------------------------------------

    def test_refused_member_looks_like_an_unknown_one_on_every_channel(self):
        refused = self.create_test_member(first_name="Oracle1964", status="Pending")
        refused.db_set("application_status", "Pending")
        create_pending_chapter_membership(refused, self.chapter.name)
        self.assertEqual(self._row_1964(refused.name).status, "Pending")

        for label, kwargs in (("explicit chapter", {"chapter_name": self.chapter.name}), ("inferred chapter", {})):
            with self.subTest(mode=label):
                with self.as_user(self.head.user):
                    self.expectErrorLog()
                    # Warm the per-user board/permission caches so the first call is not the costly one.
                    self._observe_1964(lambda: chapter_dashboard_api.quick_approve_join_request(UNKNOWN, **kwargs))
                    forbidden = self._observe_1964(lambda: chapter_dashboard_api.quick_approve_join_request(refused.name, **kwargs))
                    unknown = self._observe_1964(lambda: chapter_dashboard_api.quick_approve_join_request(UNKNOWN, **kwargs))
                self.assertFalse(self._succeeded_1964(forbidden["outcome"]), forbidden)
                self.assertEqual(
                    self._normalise_1964(forbidden, refused.name), self._normalise_1964(unknown, UNKNOWN), (forbidden, unknown)
                )

    # --- helpers -----------------------------------------------------------------------------------

    @staticmethod
    def _succeeded_1964(result):
        return isinstance(result, dict) and bool(result.get("success"))

    def _observe_1964(self, call):
        """Run call() and capture every observable channel (outcome, message_log, Error Log rows, queries)."""
        log_len = len(frappe.message_log)
        errors_before = frappe.db.count("Error Log")
        queries_before = self._questions_1964()
        try:
            outcome = call()
        except Exception as e:  # noqa: BLE001 - the exception class IS the observation
            outcome = ("raised", type(e).__name__, str(e))
        messages = [str(m) for m in frappe.message_log[log_len:]]
        del frappe.message_log[log_len:]
        return {
            "outcome": outcome,
            "messages": messages,
            "errors": frappe.db.count("Error Log") - errors_before,
            "queries": self._questions_1964() - queries_before,
        }

    @staticmethod
    def _questions_1964():
        return int(frappe.db.sql("SHOW SESSION STATUS LIKE 'Questions'")[0][1])

    @staticmethod
    def _normalise_1964(channels, name):
        text = re.sub(r"'timestamp': '[^']*'", "'timestamp': <T>", str(channels))
        text = re.sub(r"__frappe_exc_id\\?': \\?'[0-9a-f]+\\?'", "__frappe_exc_id: <ID>", text)
        text = re.sub(r"'trace_id': '[0-9a-f]+'", "'trace_id': <ID>", text)
        return text.replace(name, "<NAME>")
