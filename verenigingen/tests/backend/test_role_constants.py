"""Tests for the Roles constants class (audit T4.5).

permissions.py historically hard-coded role-name string literals. Two of
the most-used roles were not represented in the Roles constants class at
all. These tests pin the exact string value of each role constant so the
literal-replacement in permissions.py is a provably behaviour-neutral
substitution.

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.backend.test_role_constants
"""

import unittest

from verenigingen.utils.constants import Roles


class TestRoleConstants(unittest.TestCase):
    """Each role constant must equal its exact Frappe role name."""

    def test_chapter_board_member_constant(self):
        """CHAPTER_BOARD_MEMBER is the 'Verenigingen Chapter Board Member' role."""
        self.assertEqual(Roles.CHAPTER_BOARD_MEMBER, "Verenigingen Chapter Board Member")

    def test_verenigingen_member_constant(self):
        """VERENIGINGEN_MEMBER is the 'Verenigingen Member' role — distinct from
        MEMBER ('Member'), which is a different role."""
        self.assertEqual(Roles.VERENIGINGEN_MEMBER, "Verenigingen Member")
        self.assertNotEqual(Roles.VERENIGINGEN_MEMBER, Roles.MEMBER)

    def test_hr_user_constant(self):
        """HR_USER is the framework 'HR User' role."""
        self.assertEqual(Roles.HR_USER, "HR User")

    def test_remaining_permissions_role_constants(self):
        """The other roles permissions.py checks against, pinned to exact names."""
        self.assertEqual(Roles.CHAPTER_MANAGER, "Verenigingen Chapter Manager")
        self.assertEqual(Roles.EXPENSE_APPROVER, "Expense Approver")
        self.assertEqual(Roles.TEAM_LEADER, "Team Leader")
        self.assertEqual(Roles.VOLUNTEER_COORDINATOR, "Volunteer Coordinator")
        self.assertEqual(Roles.WEBHOOK_USER, "Verenigingen Webhook User")


if __name__ == "__main__":
    unittest.main()
