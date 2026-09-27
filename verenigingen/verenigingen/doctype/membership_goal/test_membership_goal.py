# Copyright (c) 2026, Verenigingen and contributors
# See license.txt

"""
Chapter-scoped MembershipGoal calculations (#1516).

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
"""

import frappe
from frappe.utils import add_days, today

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
        """A goal tracks current (Active) membership growth, not applications
        still awaiting approval."""
        member = self._make_mg_member()
        self._seat_chapter_member(self.chapter_a.name, member.name, status="Pending")

        goal = self._make_goal("New Member Acquisition", self.chapter_a.name)

        self.assertEqual(goal.current_value, 0)

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
