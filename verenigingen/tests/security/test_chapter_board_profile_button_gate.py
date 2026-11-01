"""The Chapter form's 'Apply Role Profiles to Board' button follows the endpoint's gate (#1831).

#1686 made the chapter board bulk endpoints admin-only, but chapter.js still showed the
button to everyone who sees the Board menu. The server now hands the form its own answer
through `onload` (`__onload.can_bulk_apply_board_role_profiles`). Each test asks the REAL
endpoint (`bulk_apply_chapter_board_role_profiles`) as the same actor and requires the flag to
equal "the endpoint did not refuse", so a flag computed from anything else (a hardcoded role
list, always-True) disagrees for at least one actor here.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

FLAG = "can_bulk_apply_board_role_profiles"


class TestChapterBoardProfileButtonGate(EnhancedTestCase):
    def _make_actor_1831(self, roles=(), profile=None):
        email = f"btn1831-{frappe.generate_hash(length=8)}@example.com"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "Btn",
                "send_welcome_email": 0,
                "roles": [{"role": r} for r in roles],
                "role_profiles": [{"role_profile": profile}] if profile else [],
            }
        ).insert()
        self.track_doc("User", user.name)
        return user.name

    def _flag_and_endpoint_as_1831(self, user, chapter_name):
        from verenigingen.verenigingen.doctype.chapter.chapter import bulk_apply_chapter_board_role_profiles

        doc = frappe.get_doc("Chapter", chapter_name)
        frappe.set_user(user)
        try:
            doc.onload()
            flag = doc.get_onload(FLAG)
            try:
                bulk_apply_chapter_board_role_profiles(chapter_name)
                refused = False
            except frappe.PermissionError:
                # Either layer may refuse (the ADMIN security tier, or require_profile_admin's
                # own message); the button must be hidden for both.
                refused = True
        finally:
            frappe.set_user("Administrator")
        return flag, refused

    def _make_chapter_1831(self):
        chapter = self.create_test_chapter()
        self.track_doc("Chapter", chapter.name)
        return chapter.name

    def test_admins_get_true_and_the_endpoint_accepts_them(self):
        chapter = self._make_chapter_1831()
        for user in (
            "Administrator",
            self._make_actor_1831(profile="Verenigingen Administrator"),
            self._make_actor_1831(profile="Verenigingen System Administrator"),
        ):
            flag, refused = self._flag_and_endpoint_as_1831(user, chapter)
            self.assertIs(flag, True, user)
            self.assertFalse(refused, user)

    def test_treasurer_national_board_and_chapter_board_get_false_and_are_refused(self):
        chapter = self._make_chapter_1831()
        seat = self.create_test_board_member(chapter, permissions_level="Admin")
        actors = {
            "treasurer": self._make_actor_1831(profile="Verenigingen Treasurer"),
            "national board": self._make_actor_1831(profile="Verenigingen National Board Member"),
            "chapter board": seat.user,
        }
        for label, user in actors.items():
            flag, refused = self._flag_and_endpoint_as_1831(user, chapter)
            self.assertIs(flag, False, label)
            self.assertTrue(refused, f"control: the endpoint refuses {label}")

    def test_the_flag_follows_the_guard_for_a_bare_role_without_a_profile(self):
        """The ADMIN security tier is profile-based, so a role-only user is refused by the tier
        before require_profile_admin runs and cannot be compared through the endpoint. The flag
        still follows the guard (System Manager / Verenigingen Administrator by ROLE)."""
        chapter = self._make_chapter_1831()
        for roles, expected in (
            (("Verenigingen Administrator",), True),
            (("System Manager",), True),
            (("Verenigingen Treasurer",), False),
        ):
            flag, _refused = self._flag_and_endpoint_as_1831(self._make_actor_1831(roles=roles), chapter)
            self.assertIs(flag, expected, roles)
