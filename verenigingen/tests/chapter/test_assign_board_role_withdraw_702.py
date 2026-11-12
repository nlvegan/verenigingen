"""#702: assign_chapter_board_role withdrew the board ROLE without the role PROFILE.

A User carrying a board role profile has ``roles`` reset to that profile's roles on every
save (User.populate_role_profile_roles), so a raw ``Has Role`` delete is undone by the next
``User.save()``. Every test here saves the user AFTER the withdrawal, which is the only way
the defect shows.

Real callers: ``on_member_on_update`` (Member.user re-link, driven by a real Member save) and
``update_all_chapter_board_roles`` (the sweep behind ``sync_all_chapter_board_roles``).
Probe shortcuts, stated: ``Member.user`` is set with ``db_set`` when building a person (what
account creation writes), and the sweep tests vacate the seat with ``db.delete`` behind every
hook's back, because the supported seat-ending flows (#1953) already withdraw the access
themselves; the sweep exists to repair exactly the state those hooks left behind.
"""

from unittest import mock

import frappe

from verenigingen.permissions import update_all_chapter_board_roles
from verenigingen.services.member.account.user_role_profile_calculator import (
    PROFILE_BOARD_MEMBER,
    get_user_role_profiles,
    sync_user_role_profile,
)
from verenigingen.tests.utils.base import VereningingenTestCase

BOARD_ROLE = "Verenigingen Chapter Board Member"
STAFF = "Verenigingen Staff"


class TestAssignBoardRoleWithdraw702(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter(
            chapter_name=f"W702 {frappe.generate_hash(length=6)}", postal_codes="3000-3999", published=1
        )
        self.chapter_role = self._role_702("Secretary")

    def tearDown(self):
        for user in [d["name"] for d in self._test_docs if d["doctype"] == "User"]:
            for employee in frappe.get_all("Employee", filters={"user_id": user}, pluck="name"):
                self.track_doc("Employee", employee)
        super().tearDown()

    # ------------------------------------------------------------------ helpers

    def _role_702(self, label):
        name = f"{label} {frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {"doctype": "Chapter Role", "role_name": name, "permissions_level": "Basic", "is_active": 1}
        ).insert()
        self.track_doc("Chapter Role", name)
        return name

    def _person_702(self, label):
        email = f"w702.{label.lower()}.{frappe.generate_hash(length=8)}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        member = self.create_test_member(first_name=label, last_name="W702", email=email, status="Active")
        member.db_set("user", user.name, update_modified=False)
        volunteer = self.create_test_volunteer(member=member.name)
        return frappe._dict(user=user.name, volunteer=volunteer.name, email=email, member=member.name)

    def _seat_702(self, person, chapter=None):
        chapter = frappe.get_doc("Chapter", (chapter or self.chapter).name)
        self.add_board_member_to_chapter(chapter, person.volunteer, self.chapter_role, email=person.email)

    def _roles(self, user):
        return set(frappe.get_all("Has Role", filters={"parent": user, "parenttype": "User"}, pluck="role"))

    def _assert_seated(self, user):
        self.assertIn(BOARD_ROLE, self._roles(user), "fixture: the seat gives the role")
        self.assertIn(PROFILE_BOARD_MEMBER, get_user_role_profiles(user), "fixture: and the profile")

    def _save_user(self, user):
        """The next ordinary save: this is what puts a profile-conferred role back."""
        frappe.get_doc("User", user).save()

    def _assert_withdrawn_after_a_user_save(self, user):
        self._save_user(user)
        self.assertNotIn(BOARD_ROLE, self._roles(user), "board role came back on the next User.save()")
        self.assertNotIn(PROFILE_BOARD_MEMBER, get_user_role_profiles(user), "board profile still attached")

    def _vacate_behind_the_hooks(self, person):
        frappe.db.delete("Chapter Board Member", {"volunteer": person.volunteer})
        self.assertEqual(frappe.db.count("Chapter Board Member", {"volunteer": person.volunteer}), 0)

    def _staff_team_702(self, person):
        from verenigingen.setup import create_default_team_roles

        create_default_team_roles()
        team = frappe.get_doc(
            {
                "doctype": "Team",
                "team_name": f"S702 Staff {frappe.generate_hash(length=6)}",
                "status": "Active",
                "team_type": "Project Team",
                "start_date": frappe.utils.today(),
                "default_role_profile": STAFF,
                "is_association_wide": 1,
            }
        )
        team.insert()
        self.track_doc("Team", team.name)
        team.append(
            "team_members",
            {
                "volunteer": person.volunteer,
                "team_role": "Team Member",
                "from_date": frappe.utils.today(),
                "status": "Active",
            },
        )
        team.save()

    # ------------------------------------------------------------------ the bug

    def test_the_sweep_withdraws_profile_and_role_of_an_unseated_user(self):
        person = self._person_702("Sweep")
        self._seat_702(person)
        self._assert_seated(person.user)

        self._vacate_behind_the_hooks(person)
        update_all_chapter_board_roles()

        self._assert_withdrawn_after_a_user_save(person.user)

    def test_relinking_member_user_withdraws_the_old_users_access(self):
        old = self._person_702("Relink")
        self._seat_702(old)
        self._assert_seated(old.user)
        new_user = self.create_test_user(f"w702.new.{frappe.generate_hash(length=8)}@test.invalid")
        self.track_doc("User", new_user.name)

        member = frappe.get_doc("Member", old.member)
        member.user = new_user.name
        member.save()

        self._assert_withdrawn_after_a_user_save(old.user)

    # ------------------------------------------------------------------ controls

    def test_the_sweep_keeps_access_the_user_still_earns(self):
        person = self._person_702("Keeper")
        self._seat_702(person)
        other = self.create_test_chapter(
            chapter_name=f"W702 B {frappe.generate_hash(length=6)}", postal_codes="3000-3999", published=1
        )
        self._seat_702(person, other)
        frappe.db.delete("Chapter Board Member", {"volunteer": person.volunteer, "parent": self.chapter.name})
        self.assertEqual(frappe.db.count("Chapter Board Member", {"volunteer": person.volunteer}), 1)

        update_all_chapter_board_roles()

        self._save_user(person.user)
        self._assert_seated(person.user)

    def test_the_sweep_leaves_a_staffer_staff_and_their_roles(self):
        person = self._person_702("Staffer")
        sync_user_role_profile(person.user)
        self._staff_team_702(person)
        sync_user_role_profile(person.user)
        self._seat_702(person)
        self.assertEqual(set(get_user_role_profiles(person.user)), {STAFF, PROFILE_BOARD_MEMBER}, "fixture")

        self._vacate_behind_the_hooks(person)
        update_all_chapter_board_roles()

        self._save_user(person.user)
        self.assertEqual(get_user_role_profiles(person.user), [STAFF])
        self.assertNotIn(BOARD_ROLE, self._roles(person.user))
        staff_roles = {r.role for r in frappe.get_doc("Role Profile", STAFF).roles}
        self.assertLessEqual(staff_roles, self._roles(person.user), "Staff's roles intact")

    # ------------------------------------------------------------------ fail loud (#1953)

    def test_a_failed_withdrawal_is_raised_not_swallowed(self):
        from verenigingen.verenigingen.doctype.chapter.managers import BoardAccessWithdrawalError

        person = self._person_702("Loud")
        self._seat_702(person)
        self._vacate_behind_the_hooks(person)
        # Mock justified: injects a failure at the profile-sync boundary.
        with mock.patch(
            "verenigingen.services.member.account.user_role_profile_calculator.sync_user_role_profile",
            side_effect=BoardAccessWithdrawalError("boom"),
        ):
            with self.assertRaises(BoardAccessWithdrawalError):
                update_all_chapter_board_roles()
