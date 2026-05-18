"""Tests for the role-name bug fixes surfaced by the audit T4.5 review.

Two production helpers checked roles against the wrong (un-prefixed)
role names — the canonical roles all carry a "Verenigingen " prefix:

* auth_hooks.has_volunteer_role() checked "Volunteer" / "Chapter Board
  Member" — neither role exists, so it always returned False.
* permissions.update_all_chapter_board_roles() queried the Has Role
  table for "Chapter Board Member", so its stale-role cleanup never
  matched anyone (the role keeps the CBM role after losing the board
  position — an over-grant).

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.security.test_role_name_fixes
"""

from verenigingen.auth_hooks import has_volunteer_role
from verenigingen.permissions import _users_with_chapter_board_role
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.constants import Roles


class TestHasVolunteerRole(EnhancedTestCase):
    """has_volunteer_role must recognise the real, prefixed volunteer roles."""

    def test_recognises_verenigingen_volunteer_role(self):
        """A user holding the 'Verenigingen Volunteer' role is volunteer-related."""
        user = self.create_test_user_with_roles(roles=[Roles.VOLUNTEER])
        self.assertTrue(has_volunteer_role(user.name))

    def test_recognises_chapter_board_member_role(self):
        """A chapter board member is volunteer-related."""
        user = self.create_test_user_with_roles(roles=[Roles.CHAPTER_BOARD_MEMBER])
        self.assertTrue(has_volunteer_role(user.name))

    def test_plain_member_is_not_volunteer(self):
        """A user with only the Member role is not volunteer-related."""
        user = self.create_test_user_with_roles(roles=[Roles.VERENIGINGEN_MEMBER])
        self.assertFalse(has_volunteer_role(user.name))


class TestUsersWithChapterBoardRole(EnhancedTestCase):
    """_users_with_chapter_board_role must find users holding the CBM role."""

    def test_finds_user_holding_the_role(self):
        """A user granted the canonical CBM role is returned by the helper."""
        user = self.create_test_user_with_roles(roles=[Roles.CHAPTER_BOARD_MEMBER])
        self.assertIn(user.name, _users_with_chapter_board_role())

    def test_excludes_user_without_the_role(self):
        """A user without the CBM role is not returned."""
        user = self.create_test_user_with_roles(roles=[Roles.VERENIGINGEN_MEMBER])
        self.assertNotIn(user.name, _users_with_chapter_board_role())
