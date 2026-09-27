# Copyright (c) 2026, Verenigingen and contributors
# See license.txt

"""
Chapter-scoped MembershipGoal calculations (#1516, #1530, #1531, #1533).

Member.current_chapter_display is an HTML-fieldtype field with no DB column;
any frappe.get_all/db.count filter naming it raises MySQLdb.OperationalError
unconditionally. Three sites in MembershipGoal.calculate_member_growth() and
calculate_new_members() used it to scope a goal to a chapter, so ANY
chapter-scoped "Member Count Growth" or "New Member Acquisition" goal crashed
on save/recalculation.

The real per-member chapter relation is the Chapter Member child table
(parent=chapter, member=Member.name, enabled, status). These tests build
real Members with real Chapter Member rows -- including a member of ANOTHER
chapter as a control, and a member active in BOTH chapters at once to prove
per-chapter counting doesn't silently pick one (the "pick first chapter"
wrong fix).

A follow-up review round (#1530, #1531) found two more bugs in the first fix:
"Membership Termination Request".status was filtered as "Completed", which
is not a valid Select option (the real terminal value is "Executed"), so
lost_members was always 0; and the chapter-scope helper was Active-only,
which -- because termination DISABLES a Chapter Member row (enabled=0,
status=Inactive) rather than deleting it -- silently excluded every
terminated member from both sides of member growth. Those tests use the
REAL termination flow (TerminationExecutionService, via
_terminate_member_from_chapter() below), not a hand-set status, per the
review's explicit requirement.

A second follow-up (#1533) found that the #1530/#1531 fix's "status !=
Pending" filter double-counts a chapter TRANSFER: transfer_member_between_
chapters() disables the source row (enabled=0) WITHOUT flipping status to
"Inactive" the way termination does -- so the source row stays
status="Active", enabled=0, and "status != Pending" still matched it,
counting the member as a new member of BOTH chapters and never as a loss
for the source. Maintainer ruling on #1533: a chapter attributes each
member to ONE chapter -- a transfer counts only for the destination; the
source drops the member (neither new nor lost there). These tests use the
REAL transfer flow (ChapterMembershipManager.transfer_member_between_
chapters / .leave_chapter), not a hand-set enabled/status combination.
"""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, now, today

from verenigingen.services.chapter.chapter_membership_manager import ChapterMembershipManager
from verenigingen.services.termination import TerminationExecutionService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMembershipGoalChapterScope(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.chapter_a = self.factory.create_chapter(chapter_name=f"MGChapterA-{self.uid}")
        self.chapter_b = self.factory.create_chapter(chapter_name=f"MGChapterB-{self.uid}")
        self.start_date = add_days(today(), -30)
        self.end_date = today()

    def _seat_chapter_member(self, chapter_name, member_name, status="Active", enabled=1):
        chapter_doc = frappe.get_doc("Chapter", chapter_name)
        chapter_doc.append(
            "members",
            {
                "member": member_name,
                "status": status,
                "enabled": enabled,
                "chapter_join_date": today(),
            },
        )
        chapter_doc.save()

    def _make_mg_member(self, **kwargs):
        kwargs.setdefault("email", f"mg-{self.uid}-{frappe.generate_hash(length=6)}@example.com")
        kwargs.setdefault("member_since", today())
        return self.factory.create_member(first_name="MGTest", last_name="Member", **kwargs)

    def _make_goal(self, goal_type, chapter):
        return frappe.get_doc(
            {
                "doctype": "Membership Goal",
                "goal_name": f"MG-{goal_type}-{chapter}-{self.uid}-{frappe.generate_hash(length=4)}",
                "goal_type": goal_type,
                "target_value": 10,
                "applies_to_all_chapters": 0,
                "chapter": chapter,
                "start_date": self.start_date,
                "end_date": self.end_date,
            }
        ).insert()

    def _new_goal_for_rates(self):
        """An UNSAVED Membership Goal for calculate_churn_rate()/
        calculate_retention_rate() -- both are global (non-chapter) counts
        that only read start_date/end_date, so no insert/validate is needed."""
        goal = frappe.new_doc("Membership Goal")
        goal.start_date = self.start_date
        goal.end_date = self.end_date
        return goal

    def _terminate_member_from_chapter(self, member_name, termination_date):
        """Run a REAL termination through TerminationExecutionService (not a
        hand-set status -- #1530 was found precisely because a prior fix
        trusted a status string instead of the real flow). This sets
        Membership Termination Request.status to whatever the service
        actually writes ("Executed"), disables the member's enabled Chapter
        Member row(s) (termination_integration.py::
        disable_chapter_memberships_safe: enabled=0, status="Inactive"), and
        moves Member.status to "Quit" (status_mapping["Voluntary"] in
        termination_integration.py::update_member_status_safe).
        """
        request = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": member_name,
                "termination_type": "Voluntary",
                "termination_reason": "Test termination",
                "termination_date": termination_date,
                "requested_by": frappe.session.user,
                "request_date": today(),
                "status": "Approved",
                "approved_by": frappe.session.user,
                "approval_date": now(),
            }
        )
        request.insert()
        # No .submit(): Membership Termination Request's own DocType JSON has
        # no is_submittable, so a .submit() call here would be new
        # docstatus/submittable drift (caught by the pre-push
        # submittability-drift-validator ratchet) for no functional reason --
        # TerminationExecutionService._validate_preconditions only checks the
        # status SELECT field ("Approved"), never docstatus.
        #
        # Mocking frappe.db.begin/commit/rollback mirrors
        # test_termination_execution_service.py's own pattern: the service
        # manages its own savepoint/commit/rollback (Pattern 5 in CLAUDE.md),
        # which conflicts with EnhancedTestCase's transaction if allowed to
        # actually run mid-test.
        with patch("frappe.db.begin"), patch("frappe.db.commit"), patch("frappe.db.rollback"):
            result = TerminationExecutionService().execute(request)
        self.assertTrue(result, "Real termination execution must succeed")
        request.reload()
        return request

    def test_member_growth_does_not_crash_and_excludes_other_chapter(self):
        member_a = self._make_mg_member()
        self._seat_chapter_member(self.chapter_a.name, member_a.name, status="Active")

        # Control: a member of a DIFFERENT chapter, joined in the same
        # window, must NOT count towards chapter_a's goal.
        member_b = self._make_mg_member()
        self._seat_chapter_member(self.chapter_b.name, member_b.name, status="Active")

        goal = self._make_goal("Member Count Growth", self.chapter_a.name)

        self.assertEqual(goal.current_value, 1)

    def test_new_members_does_not_crash_and_excludes_other_chapter(self):
        member_a = self._make_mg_member()
        self._seat_chapter_member(self.chapter_a.name, member_a.name, status="Active")

        member_b = self._make_mg_member()
        self._seat_chapter_member(self.chapter_b.name, member_b.name, status="Active")

        goal = self._make_goal("New Member Acquisition", self.chapter_a.name)

        self.assertEqual(goal.current_value, 1)

    def test_pending_chapter_member_not_counted(self):
        """A Chapter Member row still at status="Pending" is a chapter
        join/switch request the chapter board has not yet approved -- the
        per-chapter analogue of the unscoped branch's own exclusion of
        Member.status == "Rejected" (a never-approved applicant was never
        acquired). This is NOT the same thing as "not yet Active": #1531
        established that an Inactive (terminated) row DOES count -- only
        Pending is excluded, because the chapter never approved it in the
        first place."""
        member = self._make_mg_member()
        self._seat_chapter_member(self.chapter_a.name, member.name, status="Pending")

        goal = self._make_goal("New Member Acquisition", self.chapter_a.name)

        self.assertEqual(goal.current_value, 0)

    def test_member_growth_counts_real_terminated_member_as_lost(self):
        """#1531: termination DISABLES the Chapter Member row (enabled=0,
        status="Inactive") rather than deleting it
        (termination_integration.py::disable_chapter_memberships_safe), so an
        Active-only chapter-membership list can never see the very member a
        lost-members query is trying to count. Uses the REAL termination
        flow (#1530's own bug -- an invalid "Completed" status filter --
        would otherwise mask this one: lost_members would read 0 for the
        wrong reason)."""
        old_since = add_days(self.start_date, -60)  # outside the goal window

        lost_member = self._make_mg_member(member_since=old_since)
        self._seat_chapter_member(self.chapter_a.name, lost_member.name, status="Active")
        self._terminate_member_from_chapter(lost_member.name, termination_date=today())

        # Control: a member terminated from a DIFFERENT chapter in the same
        # window must not count as lost for chapter_a's goal.
        foreign_lost = self._make_mg_member(member_since=old_since)
        self._seat_chapter_member(self.chapter_b.name, foreign_lost.name, status="Active")
        self._terminate_member_from_chapter(foreign_lost.name, termination_date=today())

        # Control: a chapter_a termination OUTSIDE the goal window must not
        # count.
        out_of_window_member = self._make_mg_member(member_since=old_since)
        self._seat_chapter_member(self.chapter_a.name, out_of_window_member.name, status="Active")
        self._terminate_member_from_chapter(
            out_of_window_member.name, termination_date=add_days(self.start_date, -5)
        )

        goal = self._make_goal("Member Count Growth", self.chapter_a.name)

        # member_since is outside the window for all three seeded members,
        # so new_members == 0 for each; only lost_member's in-window,
        # in-chapter termination should be counted -> net growth -1.
        self.assertEqual(goal.current_value, -1)

    def test_new_members_counts_member_who_joined_and_left_within_window(self):
        """#1531: a member who joined AND was terminated from the chapter
        within the same goal window must still count as a new member
        acquired -- their Chapter Member row is Inactive by the time the
        goal recalculates, so an Active-only list would miss them even
        though they plainly did join in the window."""
        member = self._make_mg_member(member_since=today())
        self._seat_chapter_member(self.chapter_a.name, member.name, status="Active")
        self._terminate_member_from_chapter(member.name, termination_date=today())

        goal = self._make_goal("New Member Acquisition", self.chapter_a.name)

        self.assertEqual(goal.current_value, 1)

    def test_member_in_multiple_chapters_counted_for_each(self):
        """A member with an active row in BOTH chapters must be counted by
        EACH chapter's own goal -- a pick-first-chapter implementation would
        miss it for whichever chapter didn't win the pick."""
        member = self._make_mg_member()
        self._seat_chapter_member(self.chapter_a.name, member.name, status="Active")
        self._seat_chapter_member(self.chapter_b.name, member.name, status="Active")

        goal_a = self._make_goal("New Member Acquisition", self.chapter_a.name)
        goal_b = self._make_goal("New Member Acquisition", self.chapter_b.name)

        self.assertEqual(goal_a.current_value, 1)
        self.assertEqual(goal_b.current_value, 1)

    def test_churn_rate_increases_after_real_termination(self):
        """#1530's invalid "Completed" status filter also affects
        calculate_churn_rate() (global, not chapter-scoped), so it silently
        read 0% churn regardless of real terminations. Compares BEFORE vs
        AFTER a real termination rather than an absolute value: churn_rate
        is a GLOBAL count, so an absolute expected value would be fragile
        against whatever else exists on the site. The direction is
        guaranteed regardless of any pre-existing site data: one real
        Executed termination both increases the numerator (churned) and
        decreases the denominator (total_members no longer counts the
        terminated member, whose status is no longer "Active"), so
        churn_rate strictly increases."""
        old_since = add_days(self.start_date, -10)
        self._make_mg_member(member_since=old_since, status="Active")  # keeps total_members >= 1 throughout
        terminated_member = self._make_mg_member(member_since=old_since, status="Active")

        goal = self._new_goal_for_rates()
        before = goal.calculate_churn_rate()

        self._terminate_member_from_chapter(terminated_member.name, termination_date=today())

        after = goal.calculate_churn_rate()
        self.assertGreater(after, before)

    def test_retention_rate_decreases_after_real_termination(self):
        """Same #1530 fix, calculate_retention_rate() side -- see
        test_churn_rate_increases_after_real_termination for why this
        compares before/after rather than an absolute value. Terminating one
        of >=2 pre-window members simultaneously raises the numerator's
        subtrahend (terminated) and lowers the denominator (start_members,
        since the terminated member's status is no longer "!= Quit"); the
        algebra (retention = (S-T)/S) makes the after-value strictly lower
        whenever S >= 2 AND before > 0.

        The `S >= 2` half is guaranteed by the two seeded members regardless
        of whatever else exists on the site -- but `before > 0` is NOT:
        calculate_retention_rate() clamps its result with max(0, ...), so if
        enough REAL terminations already exist site-wide in this exact
        window (leaked test data, or genuine production-like data on a
        shared site) to already floor `before` at 0, `after` cannot go any
        lower and assertLess would fail -- not because the #1530 fix is
        wrong, but because the site's pre-existing state left no room to
        observe a decrease. Assert that precondition explicitly, so that
        failure mode surfaces as a clear, actionable precondition failure
        instead of a confusing false "regression"."""
        old_since = add_days(self.start_date, -10)
        self._make_mg_member(
            member_since=old_since, status="Active"
        )  # keeps start_members >= 2 with the next
        terminated_member = self._make_mg_member(member_since=old_since, status="Active")

        goal = self._new_goal_for_rates()
        before = goal.calculate_retention_rate()
        self.assertGreater(
            before,
            0,
            "precondition: retention_rate is already clamped to 0 before this test's own "
            "termination -- too much pre-existing terminated/site data in this window to "
            "observe a decrease; not a #1530/#1531/#1533 regression",
        )

        self._terminate_member_from_chapter(terminated_member.name, termination_date=today())

        after = goal.calculate_retention_rate()
        self.assertLess(after, before)

    def test_transfer_attributes_member_to_destination_only(self):
        """#1533 (maintainer ruling): a chapter attributes each member to
        ONE chapter. A transfer counts only for the destination; the
        source drops the member (neither new nor lost there). Uses the REAL
        transfer flow (ChapterMembershipManager.transfer_member_between_
        chapters), which disables the source row (enabled=0) WITHOUT
        touching its status (stays "Active") -- the exact same row shape a
        standalone leave_chapter() produces (see
        test_voluntary_leave_without_transfer_counts_nowhere)."""
        member = self._make_mg_member(member_since=today())
        self._seat_chapter_member(self.chapter_a.name, member.name, status="Active")

        result = ChapterMembershipManager.transfer_member_between_chapters(
            member_id=member.name,
            from_chapter=self.chapter_a.name,
            to_chapter=self.chapter_b.name,
            reason="Test transfer",
        )
        self.assertTrue(result.get("success"), msg=result)

        # Confirm the real flow produces the documented row shape -- the
        # premise this fix depends on.
        source_row = frappe.db.get_value(
            "Chapter Member",
            {"member": member.name, "parent": self.chapter_a.name},
            ["status", "enabled"],
            as_dict=True,
        )
        self.assertEqual(source_row.status, "Active")
        self.assertEqual(source_row.enabled, 0)

        goal_source = self._make_goal("New Member Acquisition", self.chapter_a.name)
        goal_dest = self._make_goal("New Member Acquisition", self.chapter_b.name)

        self.assertEqual(
            goal_source.current_value, 0, "source chapter must NOT count the transferred-out member"
        )
        self.assertEqual(
            goal_dest.current_value, 1, "destination chapter must count the transfer as acquired"
        )

    def test_transfer_out_does_not_count_as_lost_but_termination_still_does(self):
        """Control: a transfer-out must not appear as a loss for the source
        chapter (no Membership Termination Request is ever created for a
        transfer), but a REAL termination in the SAME goal/chapter/window
        must still count as lost -- proving the fix distinguishes the two
        enabled=0 row shapes (transfer/leave vs termination) rather than
        excluding every disabled row (the #1531 regression this must not
        reintroduce)."""
        old_since = add_days(self.start_date, -60)  # outside the goal window

        transferred_member = self._make_mg_member(member_since=old_since)
        self._seat_chapter_member(self.chapter_a.name, transferred_member.name, status="Active")
        result = ChapterMembershipManager.transfer_member_between_chapters(
            member_id=transferred_member.name,
            from_chapter=self.chapter_a.name,
            to_chapter=self.chapter_b.name,
            reason="Test transfer",
        )
        self.assertTrue(result.get("success"), msg=result)

        terminated_member = self._make_mg_member(member_since=old_since)
        self._seat_chapter_member(self.chapter_a.name, terminated_member.name, status="Active")
        self._terminate_member_from_chapter(terminated_member.name, termination_date=today())

        goal = self._make_goal("Member Count Growth", self.chapter_a.name)

        # member_since is outside the window for both seeded members, so
        # new_members == 0; the transfer contributes nothing (neither new
        # nor lost), and only the real termination counts as lost -> -1.
        self.assertEqual(goal.current_value, -1)

    def test_voluntary_leave_without_transfer_counts_nowhere(self):
        """A member who leaves chapter A but does NOT join any other
        chapter (stays a general Member) hits the exact same
        remove_member(permanent=False) code as a transfer's source side --
        ChapterMembershipManager.leave_chapter() called standalone, not
        through transfer_member_between_chapters -- producing the
        identical row shape (status unchanged, enabled disabled). Per the
        #1533 ruling this member ends up attributed NOWHERE: not lost for A
        (no termination was ever created) and not new anywhere else (no
        destination chapter exists to attribute them to)."""
        member = self._make_mg_member(member_since=today())
        self._seat_chapter_member(self.chapter_a.name, member.name, status="Active")

        result = ChapterMembershipManager.leave_chapter(
            member_id=member.name,
            chapter_name=self.chapter_a.name,
            leave_reason="Test voluntary leave",
        )
        self.assertTrue(result.get("success"), msg=result)

        row = frappe.db.get_value(
            "Chapter Member",
            {"member": member.name, "parent": self.chapter_a.name},
            ["status", "enabled"],
            as_dict=True,
        )
        self.assertEqual(row.status, "Active")
        self.assertEqual(row.enabled, 0)

        goal = self._make_goal("New Member Acquisition", self.chapter_a.name)
        self.assertEqual(goal.current_value, 0)
