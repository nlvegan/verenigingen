"""#1969: a staffer (via a staff Team) who holds ANY chapter board seat keeps Staff AND gets the seat.

Maintainer ruling (2026-11-01): extends the #1615 national exception to every seat kind (default
priority 70, role-specific mapped 80, financial 100). A default seat must also give the board
role. Everything runs through real flows: a staff Team insert with the volunteer as a member,
then a Chapter append + save for the seat, ``remove_board_member`` to unseat. No probe shortcuts
except ``Member.user`` being set with ``db_set`` (the account link an account-creation request
would write).
"""

import frappe

from verenigingen.services.member.account.user_role_profile_calculator import (
    PROFILE_BOARD_MEMBER,
    get_user_role_profiles,
    sync_user_role_profile,
)
from verenigingen.tests.utils.base import VereningingenTestCase

STAFF = "Verenigingen Staff"
BOARD_ROLE = "Verenigingen Chapter Board Member"
MAPPED_PROFILE = "Verenigingen Auditor"  # a role-specific mapping that is not the board default


class TestStaffKeepsProfileOnSeat1969(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter(
            chapter_name=f"Staff1969 {frappe.generate_hash(length=6)}", postal_codes="4000-4999", published=1
        )

    def tearDown(self):
        users = [d["name"] for d in self._test_docs if d["doctype"] == "User"]
        for user in users:  # seating applies a profile carrying Employee; see #1694
            for employee in frappe.get_all("Employee", filters={"user_id": user}, pluck="name"):
                self.track_doc("Employee", employee)
        super().tearDown()

    # ------------------------------------------------------------------ helpers

    def _chapter_role_1969(self, label):
        name = f"{label} {frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {"doctype": "Chapter Role", "role_name": name, "permissions_level": "Basic", "is_active": 1}
        ).insert()
        self.track_doc("Chapter Role", name)
        return name

    def _person_1969(self, label):
        email = f"staff1969.{label.lower()}.{frappe.generate_hash(length=8)}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        member = self.create_test_member(first_name=label, last_name="S1969", email=email, status="Active")
        member.db_set("user", user.name, update_modified=False)
        volunteer = self.create_test_volunteer(member=member.name)
        return frappe._dict(user=user.name, volunteer=volunteer.name, email=email)

    def _staff_team_1969(self):
        from verenigingen.setup import create_default_team_roles

        create_default_team_roles()
        team = frappe.get_doc(
            {
                "doctype": "Team",
                "team_name": f"S1969 Staff {frappe.generate_hash(length=6)}",
                "status": "Active",
                "team_type": "Project Team",
                "start_date": frappe.utils.today(),
                "default_role_profile": STAFF,
                "is_association_wide": 1,
            }
        )
        team.insert()
        self.track_doc("Team", team.name)
        return team.name

    def _staffer_1969(self, label="Staffer"):
        person = self._person_1969(label)
        sync_user_role_profile(person.user)
        team = frappe.get_doc("Team", self._staff_team_1969())
        team.append(
            "team_members",
            {"volunteer": person.volunteer, "team_role": "Team Member", "from_date": frappe.utils.today(), "status": "Active"},
        )
        team.save()
        sync_user_role_profile(person.user)
        person.team = team.name
        self.assertEqual(get_user_role_profiles(person.user), [STAFF], "fixture: staff via the Team")
        return person

    def _seat_1969(self, person, role, chapter=None):
        self.add_board_member_to_chapter(
            frappe.get_doc("Chapter", (chapter or self.chapter).name), person.volunteer, role, email=person.email
        )

    def _map_1969(self, role, profile):
        chapter = frappe.get_doc("Chapter", self.chapter.name)
        chapter.enable_board_role_specific_profiles = 1
        chapter.append("board_role_specific_profiles", {"chapter_role": role, "role_profile": profile})
        chapter.save()

    def _profile_roles_1969(self, profile):
        return {r.role for r in frappe.get_doc("Role Profile", profile).roles}

    def _user_roles_1969(self, user):
        return set(frappe.get_all("Has Role", filters={"parent": user, "parenttype": "User"}, pluck="role"))

    def _assert_holds_1969(self, user, *profiles):
        held = get_user_role_profiles(user)
        for profile in profiles:
            self.assertIn(profile, held)
            missing = self._profile_roles_1969(profile) - self._user_roles_1969(user)
            self.assertEqual(missing, set(), f"roles of {profile} missing from the user")

    # ------------------------------------------------------------ one per seat kind

    def test_staffer_on_a_default_seat_keeps_staff_and_gets_the_board_profile_and_role(self):
        staffer = self._staffer_1969()
        self.assertNotIn(BOARD_ROLE, self._user_roles_1969(staffer.user), "control: no board role yet")
        self._seat_1969(staffer, self._chapter_role_1969("Secretary"))
        self._assert_holds_1969(staffer.user, STAFF, PROFILE_BOARD_MEMBER)
        self.assertIn(BOARD_ROLE, self._user_roles_1969(staffer.user))

    def test_staffer_on_a_role_specific_mapped_seat_keeps_staff_and_gets_the_mapped_profile(self):
        staffer = self._staffer_1969()
        role = self._chapter_role_1969("Secretary")
        self._map_1969(role, MAPPED_PROFILE)
        self._seat_1969(staffer, role)
        self._assert_holds_1969(staffer.user, STAFF, MAPPED_PROFILE)

    def test_staffer_on_a_financial_seat_keeps_staff_and_gets_the_seat_profile(self):
        staffer = self._staffer_1969()
        role = self._chapter_role_1969("Penningmeester")  # priority 100 via the accounting keyword
        self._map_1969(role, MAPPED_PROFILE)
        self._seat_1969(staffer, role)
        sync_user_role_profile(staffer.user)  # the issue saw the financial case after a resync
        self._assert_holds_1969(staffer.user, STAFF, MAPPED_PROFILE)

    # ------------------------------------------------------------ bookkeeping

    def test_unseating_removes_the_board_profile_and_keeps_staff(self):
        staffer = self._staffer_1969()
        self._seat_1969(staffer, self._chapter_role_1969("Secretary"))
        self._assert_holds_1969(staffer.user, STAFF, PROFILE_BOARD_MEMBER)

        chapter = frappe.get_doc("Chapter", self.chapter.name)
        self.assertTrue(chapter.board_manager.remove_board_member(staffer.volunteer, notify=False)["success"])

        self.assertNotIn(PROFILE_BOARD_MEMBER, get_user_role_profiles(staffer.user))
        self._assert_holds_1969(staffer.user, STAFF)
        self.assertNotIn(BOARD_ROLE, self._user_roles_1969(staffer.user))

    def test_leaving_the_team_removes_staff_and_keeps_the_board_profile(self):
        staffer = self._staffer_1969()
        self._seat_1969(staffer, self._chapter_role_1969("Secretary"))
        team = frappe.get_doc("Team", staffer.team)
        team.remove(team.team_members[0])
        team.save()
        sync_user_role_profile(staffer.user)

        held = get_user_role_profiles(staffer.user)
        self.assertNotIn(STAFF, held)
        self._assert_holds_1969(staffer.user, PROFILE_BOARD_MEMBER)

    def test_the_stacked_sync_is_idempotent(self):
        staffer = self._staffer_1969()
        self._seat_1969(staffer, self._chapter_role_1969("Secretary"))
        again = sync_user_role_profile(staffer.user)
        self.assertTrue(again["success"], again)
        self.assertFalse(again["role_changed"], again)

    # ------------------------------------------------------------ opposite harm

    def test_a_non_staff_board_member_holds_exactly_the_board_profile(self):
        person = self._person_1969("Plain")
        self._seat_1969(person, self._chapter_role_1969("Secretary"))
        sync_user_role_profile(person.user)
        self.assertEqual(get_user_role_profiles(person.user), [PROFILE_BOARD_MEMBER])
        self.assertNotIn(STAFF, get_user_role_profiles(person.user))

    def test_a_staffer_with_no_seat_holds_only_staff(self):
        staffer = self._staffer_1969()
        sync_user_role_profile(staffer.user)
        self.assertEqual(get_user_role_profiles(staffer.user), [STAFF])
        self.assertNotIn(BOARD_ROLE, self._user_roles_1969(staffer.user))

    def test_a_mapped_profile_does_not_leak_to_a_staffer_without_that_seat(self):
        holder = self._person_1969("Holder")
        staffer = self._staffer_1969()
        role = self._chapter_role_1969("Penningmeester")
        self._map_1969(role, MAPPED_PROFILE)
        self._seat_1969(holder, role)  # control row: the mapped seat exists and is held
        sync_user_role_profile(staffer.user)
        self.assertIn(MAPPED_PROFILE, get_user_role_profiles(holder.user), "control: seat grants it")
        self.assertEqual(get_user_role_profiles(staffer.user), [STAFF])
