"""#3203: a 1213 deadlock must escape the two membership-duration handlers that swallowed it.

``Membership.update_member_duration`` (run from ``on_submit``) and
``MemberDurationService.update_duration`` both ended in a bare ``except Exception`` that turned a
lock error raised by ``update_member_duration_fields`` (which #2817 now lets escape) back into a
value. A 1213 has rolled the whole transaction back, so carrying on is wrong. Ordinary errors keep
being swallowed ("don't fail the membership submission").

1205 is deliberately NOT asserted either way: whether a lock-wait timeout aborts a membership
submit is a maintainer choice (#3203 "Not established"). ``test_1205_*`` only records today's behaviour.

The fault is injected at the DRIVER (``frappe.db.execute_query`` raises a real OperationalError and
frappe's own dispatch converts 1213/1205 into QueryDeadlockError/QueryTimeoutError), below every
swallow layer, and only while the named handler frame is on the stack.
"""

import traceback
from unittest.mock import patch

import frappe

from verenigingen.services.member.utils.member_duration_service import MemberDurationService
from verenigingen.tests.utils.base import VereningingenTestCase

DUPLICATE_MARKER = "injected for #3203"


def _fault_inside_frame_3203(frame_name, errno, hits):
    """Fail every statement naming tabMember/tabMembership while ``frame_name`` is on the stack
    (never while a failure is being recorded). Appends to ``hits`` each time it fires."""
    real = frappe.db.execute_query

    def execute_query(query, values=None):
        names = [f.name for f in traceback.extract_stack()]
        if frame_name in names and "log_error" not in names and "`tabMember" in str(query):
            hits.append(errno)
            raise frappe.db.OperationalError(errno, f"{DUPLICATE_MARKER} {errno}")
        return real(query, values)

    return patch.object(frappe.db, "execute_query", execute_query)


class TestMembershipDurationLockErrors3203(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="Duration",
            last_name="Lock",
            email=f"duration.lock.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        self.membership_type = self.create_test_membership_type(
            membership_type_name=f"MDurType{frappe.generate_hash(length=6)}",
        )

    def _draft_membership(self):
        return self.create_test_membership(
            member=self.member.name, membership_type=self.membership_type.name
        )

    # ---------------------------------------------------------------- Membership.update_member_duration

    def test_1213_during_member_duration_update_aborts_the_submit(self):
        membership = self._draft_membership()
        hits = []
        with _fault_inside_frame_3203("update_member_duration", 1213, hits):
            with self.assertRaises(frappe.QueryDeadlockError):
                membership.submit()
        self.assertTrue(hits, "the injected 1213 never fired inside update_member_duration")

    def test_control_ordinary_error_during_member_duration_update_lets_submit_succeed(self):
        membership = self._draft_membership()
        self.expectErrorLog(DUPLICATE_MARKER)
        hits = []
        with _fault_inside_frame_3203("update_member_duration", 2013, hits):
            membership.submit()
        self.assertTrue(hits, "the injected 2013 never fired inside update_member_duration")
        self.assertEqual(frappe.db.get_value("Membership", membership.name, "docstatus"), 1)

    def test_1213_during_current_plan_update_aborts_the_submit(self):
        membership = self._draft_membership()
        hits = []
        with _fault_inside_frame_3203("update_member_current_membership_plan", 1213, hits):
            with self.assertRaises(frappe.QueryDeadlockError):
                membership.submit()
        self.assertTrue(hits, "the injected 1213 never fired inside update_member_current_membership_plan")

    def test_control_ordinary_error_during_current_plan_update_lets_submit_succeed(self):
        membership = self._draft_membership()
        self.expectErrorLog(DUPLICATE_MARKER)
        hits = []
        with _fault_inside_frame_3203("update_member_current_membership_plan", 2013, hits):
            membership.submit()
        self.assertTrue(hits, "the injected 2013 never fired inside update_member_current_membership_plan")
        self.assertEqual(frappe.db.get_value("Membership", membership.name, "docstatus"), 1)

    def test_1205_during_current_plan_update_is_swallowed_today(self):
        """Characterisation of UNRULED behaviour (#3203): same ruling question as for 1205 above."""
        membership = self._draft_membership()
        self.expectErrorLog(DUPLICATE_MARKER)
        hits = []
        with _fault_inside_frame_3203("update_member_current_membership_plan", 1205, hits):
            membership.submit()
        self.assertTrue(hits)
        self.assertEqual(frappe.db.get_value("Membership", membership.name, "docstatus"), 1)

    def test_1205_during_member_duration_update_is_swallowed_today(self):
        """Characterisation of UNRULED behaviour (#3203): a 1205 does not abort the submit today.
        If the maintainer rules that it should, flip this test together with the handler."""
        membership = self._draft_membership()
        self.expectErrorLog(DUPLICATE_MARKER)
        hits = []
        with _fault_inside_frame_3203("update_member_duration", 1205, hits):
            membership.submit()
        self.assertTrue(hits)
        self.assertEqual(frappe.db.get_value("Membership", membership.name, "docstatus"), 1)

    # ---------------------------------------------------------------- MemberDurationService.update_duration

    def test_1213_in_service_update_duration_propagates(self):
        member_doc = frappe.get_doc("Member", self.member.name)
        hits = []
        with _fault_inside_frame_3203("update_duration", 1213, hits):
            with self.assertRaises(frappe.QueryDeadlockError):
                MemberDurationService().update_duration(member_doc)
        self.assertTrue(hits, "the injected 1213 never fired inside update_duration")

    def test_control_ordinary_error_in_service_update_duration_returns_failure(self):
        member_doc = frappe.get_doc("Member", self.member.name)
        self.expectErrorLog(DUPLICATE_MARKER)
        hits = []
        with _fault_inside_frame_3203("update_duration", 2013, hits):
            result = MemberDurationService().update_duration(member_doc)
        self.assertTrue(hits, "the injected 2013 never fired inside update_duration")
        self.assertFalse(result["success"])

    def test_1205_in_service_update_duration_returns_failure_today(self):
        """Characterisation of UNRULED behaviour (#3203): 1205 still becomes a failure dict."""
        member_doc = frappe.get_doc("Member", self.member.name)
        self.expectErrorLog(DUPLICATE_MARKER)
        hits = []
        with _fault_inside_frame_3203("update_duration", 1205, hits):
            result = MemberDurationService().update_duration(member_doc)
        self.assertTrue(hits)
        self.assertFalse(result["success"])
