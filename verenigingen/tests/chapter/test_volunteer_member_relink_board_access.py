"""Re-linking Volunteer.member must move board access with the seat (#2615, split from #702).

A board seat belongs to a Volunteer, and board access (the Frappe role
``Verenigingen Chapter Board Member`` plus the board Role Profile) follows
Volunteer -> Member -> Member.user. ``Volunteer.member`` is editable by staff
(#2752's guard allows ``Roles.ADMIN_ROLES``), and BoardManager only runs from
``Chapter.on_update``, so before this fix a staff re-link left the OLD member's user
holding board access for a seat they no longer have, and gave the NEW member's user
nothing until the next Chapter save.

Every test here drives the real path: a least-privileged STAFF user (the shipped
Verenigingen Staff profile, no System Manager) saves the Volunteer through the desk
controller. Access is asserted before the re-link, so a vacuous pass is impossible.
Rows are real; nothing is mocked. ``db.set_value`` is used only to link Member.user
in fixtures (the same shortcut test_board_role_withdrawal uses), never for the re-link.
"""

import json

import frappe
from frappe.utils import today

from verenigingen.services.member.account.user_role_profile_calculator import get_user_role_profiles
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.constants import Roles

BOARD_PROFILE_2615 = "Verenigingen Chapter Board Member"


def _shipped_profile_roles_2615(profile):
    path = frappe.get_app_path("verenigingen", "fixtures", "role_profile.json")
    with open(path) as f:
        for p in json.load(f):
            if p["name"] == profile:
                return [r["role"] for r in p["roles"]]
    raise AssertionError(f"Role Profile {profile} is not shipped")


class TestVolunteerMemberRelinkBoardAccess2615(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.token_2615 = frappe.generate_hash(length=6)
        self.chapter = self.create_test_chapter(
            chapter_name=f"Relink {self.token_2615}", postal_codes="1000-9999", published=1
        )
        self.staff_2615 = self._staff_user_2615()

    # ------------------------------------------------------------------ helpers

    def _staff_user_2615(self):
        profile = "Verenigingen Staff"
        user = self.create_test_user(
            f"staff2615.{self.token_2615}@test.invalid", roles=_shipped_profile_roles_2615(profile)
        )
        self.track_doc("User", user.name)
        user.append("role_profiles", {"role_profile": profile})
        user.save()
        return user

    def _person_2615(self, first, with_volunteer):
        """A Member with a real, enabled User; optionally a Volunteer."""
        email = f"relink.{first.lower()}.{frappe.generate_hash(length=6)}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        member = self.create_test_member(first_name=first, last_name="Relink", email=email, status="Active")
        member.db_set("user", user.name, update_modified=False)
        member.reload()
        volunteer = self.create_test_volunteer(member=member.name) if with_volunteer else None
        return user, member, volunteer

    def _seat_2615(self, volunteer, user, chapter=None):
        role_name = f"Role{frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": role_name,
                "permissions_level": "Basic",
                "is_chair": 0,
                "is_active": 1,
            }
        ).insert()
        self.track_doc("Chapter Role", role_name)
        chapter = frappe.get_doc("Chapter", (chapter or self.chapter).name)
        self.add_board_member_to_chapter(chapter, volunteer, role_name, email=user.name)

    def _relink_as_staff_2615(self, volunteer, new_member):
        original = frappe.session.user
        frappe.set_user(self.staff_2615.name)
        try:
            doc = frappe.get_doc("Volunteer", volunteer.name)
            doc.member = new_member.name
            doc.save()
        finally:
            frappe.set_user(original)

    def _roles_2615(self, user_name):
        frappe.clear_cache(user=user_name)
        return frappe.get_roles(user_name)

    def _row_2615(self, user_name):
        return bool(frappe.db.exists("Has Role", {"parent": user_name, "role": Roles.CHAPTER_BOARD_MEMBER}))

    def _assert_access_2615(self, user_name, msg):
        self.assertIn(BOARD_PROFILE_2615, get_user_role_profiles(user_name), f"{msg} (role profile)")
        self.assertIn(Roles.CHAPTER_BOARD_MEMBER, self._roles_2615(user_name), f"{msg} (Frappe role)")
        self.assertTrue(self._row_2615(user_name), f"{msg} (Has Role row)")

    def _assert_no_access_2615(self, user_name, msg):
        self.assertNotIn(Roles.CHAPTER_BOARD_MEMBER, self._roles_2615(user_name), f"{msg} (Frappe role)")
        self.assertFalse(self._row_2615(user_name), f"{msg} (Has Role row)")
        self.assertNotIn(BOARD_PROFILE_2615, get_user_role_profiles(user_name), f"{msg} (role profile)")

    # ------------------------------------------------------------------- tests

    def test_staff_relink_of_a_seated_volunteer_moves_board_access_to_the_new_user(self):
        old_user, _old_member, volunteer = self._person_2615("OldHolder", with_volunteer=True)
        new_user, new_member, _none = self._person_2615("NewHolder", with_volunteer=False)
        self._seat_2615(volunteer, old_user)
        self._assert_access_2615(old_user.name, "seating must grant the old user board access first")
        self._assert_no_access_2615(new_user.name, "the new user must start without board access")

        self._relink_as_staff_2615(volunteer, new_member)

        self.assertEqual(frappe.db.get_value("Volunteer", volunteer.name, "member"), new_member.name)
        self._assert_no_access_2615(old_user.name, "the old member's user kept board access after the re-link")
        self._assert_access_2615(new_user.name, "the seated volunteer's new user got no board access")

    def test_relink_of_a_volunteer_with_no_seat_leaves_access_alone(self):
        """Control: an unseated volunteer's re-link changes nobody's board access."""
        old_user, _old_member, volunteer = self._person_2615("Unseated", with_volunteer=True)
        new_user, new_member, _none = self._person_2615("Bystander", with_volunteer=False)
        self._assert_no_access_2615(old_user.name, "fixture: unseated user holds no board access")

        self._relink_as_staff_2615(volunteer, new_member)

        self._assert_no_access_2615(old_user.name, "an unseated re-link granted the old user access")
        self._assert_no_access_2615(new_user.name, "an unseated re-link granted the new user access")
