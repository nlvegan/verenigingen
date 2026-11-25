"""#3269: the event-mode role-profile sync keeps a user's directly held roles.

Maintainer ruling (2026-11-25): roles no role profile supplies survive an event sync, as they
already do in the nightly sweep. A role only a profile the user JUST LOST supplied must still
go, or the #720 harm (revoked board access that never leaves) comes back.

Real flow throughout: a Member-linked User with real Has Role rows is seated on / unseated from
a Chapter board (Chapter.on_update -> BoardManager -> sync_user_role_profile, event mode), and
``auto_sync_on_role_change`` (the entry the volunteer/ACR/chapter subscribers call) is driven
directly. Probe shortcut: the direct roles are stored by ``create_test_user(roles=...)``, which
writes the Has Role rows; no profile supplies them.
"""

import frappe

from verenigingen.services.member.account.user_role_profile_calculator import (
    auto_sync_on_role_change,
    sync_user_role_profile,
)
from verenigingen.tests.utils.base import VereningingenTestCase

BOARD_ROLE = "Verenigingen Chapter Board Member"
BOARD_PROFILE = "Verenigingen Chapter Board Member"
DIRECT = ("System Manager", "Accounts User", "Newsletter Manager")


class TestEventSyncKeepsDirectRoles3269(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter(
            chapter_name=f"Direct3269 {frappe.generate_hash(length=6)}",
            postal_codes="3000-3999",
            published=1,
        )
        name = f"Secretary {frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {"doctype": "Chapter Role", "role_name": name, "permissions_level": "Basic", "is_active": 1}
        ).insert()
        self.track_doc("Chapter Role", name)
        self.board_role = name

    def _staff_person_3269(self):
        email = f"direct3269.{frappe.generate_hash(length=8)}@test.invalid"
        user = self.create_test_user(email, roles=list(DIRECT))
        self.track_doc("User", user.name)
        member = self.create_test_member(first_name="Direct", last_name="Staff", email=email, status="Active")
        member.db_set("user", user.name, update_modified=False)
        volunteer = self.create_test_volunteer(member=member.name)
        return frappe._dict(user=user.name, volunteer=volunteer.name)

    def _roles_3269(self, user):
        return set(frappe.get_all("Has Role", filters={"parent": user, "parenttype": "User"}, pluck="role"))

    def _profiles_3269(self, user):
        return set(frappe.get_all("User Role Profile", filters={"parent": user}, pluck="role_profile"))

    def _seat_3269(self, person):
        self.add_board_member_to_chapter(
            frappe.get_doc("Chapter", self.chapter.name),
            person.volunteer,
            self.board_role,
            email=person.user,
        )

    def _unseat_3269(self, person):
        chapter = frappe.get_doc("Chapter", self.chapter.name)
        for row in chapter.board_members:
            if row.volunteer == person.volunteer:
                row.is_active = 0
                row.to_date = frappe.utils.today()
        chapter.save()

    def _assert_direct_kept_3269(self, user, expected=DIRECT):
        self.assertTrue(set(expected) <= self._roles_3269(user), f"direct roles lost: {self._roles_3269(user)}")

    def _direct_not_supplied_by_3269(self, profile):
        """A direct role the profile ALSO supplies cannot be told apart from a profile-supplied one
        (Accounts User is on the board profile), so after a profile is lost only the rest is provably direct."""
        supplied = {r.role for r in frappe.get_doc("Role Profile", profile).roles}
        provable = [role for role in DIRECT if role not in supplied]
        self.assertTrue(len(provable) >= 2, f"fixture: too few unambiguous direct roles: {provable}")
        return provable

    def test_fixture_holds_the_direct_roles_and_no_profile(self):
        person = self._staff_person_3269()
        self._assert_direct_kept_3269(person.user)
        self.assertEqual(self._profiles_3269(person.user), set(), "control: no profile before the sync")

    def test_direct_roles_survive_a_board_seat_event_sync(self):
        person = self._staff_person_3269()
        self._seat_3269(person)

        self.assertEqual(self._profiles_3269(person.user), {BOARD_PROFILE}, "the sync did not run")
        self.assertIn(BOARD_ROLE, self._roles_3269(person.user))
        self._assert_direct_kept_3269(person.user)

    def test_direct_roles_survive_auto_sync_on_role_change_for_a_profileless_member(self):
        person = self._staff_person_3269()

        result = auto_sync_on_role_change(person.user)

        self.assertTrue(result["success"], result)
        self.assertTrue(result["changed"], "fixture: the sync must actually rewrite the user")
        self.assertTrue(self._profiles_3269(person.user), "fixture: no profile was written")
        self._assert_direct_kept_3269(person.user)

    def test_role_only_a_lost_profile_supplied_is_withdrawn_but_direct_roles_stay(self):
        person = self._staff_person_3269()
        self._seat_3269(person)
        self.assertIn(BOARD_ROLE, self._roles_3269(person.user), "control: the seat grants the role")

        self._unseat_3269(person)

        self.assertNotIn(BOARD_PROFILE, self._profiles_3269(person.user))
        self.assertNotIn(BOARD_ROLE, self._roles_3269(person.user), "a lost profile's role was kept")
        self._assert_direct_kept_3269(person.user, self._direct_not_supplied_by_3269(BOARD_PROFILE))

    def test_a_plain_user_save_of_a_profiled_user_still_drops_direct_roles_framework_limit(self):
        """Durability limit, measured: Frappe's User.populate_role_profile_roles keeps only the
        roles the user's profiles supply, so ANY later User.save() of a profiled user drops the
        direct rows the sync restored. The event sync can only keep them until the next save; the
        nightly sweep restores them. Tracked in the PR body; not fixable in this handler."""
        person = self._staff_person_3269()
        self._seat_3269(person)
        self._assert_direct_kept_3269(person.user)

        frappe.get_doc("User", person.user).save()

        self.assertFalse(
            set(DIRECT) & self._roles_3269(person.user) - {"Accounts User"},
            "framework behaviour changed: direct roles now survive a plain save; strengthen this test",
        )

    def test_sync_is_idempotent_for_direct_roles(self):
        person = self._staff_person_3269()
        sync_user_role_profile(person.user)
        sync_user_role_profile(person.user)
        rows = frappe.get_all("Has Role", filters={"parent": person.user, "parenttype": "User"}, pluck="role")
        self.assertEqual(len(rows), len(set(rows)), "duplicate Has Role rows")
        self._assert_direct_kept_3269(person.user)
