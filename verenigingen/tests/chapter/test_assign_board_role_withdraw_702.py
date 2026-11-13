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

from verenigingen import permissions
from verenigingen.permissions import assign_chapter_board_role, update_all_chapter_board_roles
from verenigingen.services.member.account import user_role_profile_calculator as calculator
from verenigingen.services.member.account.user_role_profile_calculator import (
    PROFILE_BOARD_MEMBER,
    get_user_role_profiles,
    record_sync_granted_profiles,
    sync_user_role_profile,
)
from verenigingen.tests.utils.base import VereningingenTestCase

BOARD_ROLE = "Verenigingen Chapter Board Member"
STAFF = "Verenigingen Staff"
TREASURER = "Verenigingen Treasurer"
NATIONAL = "Verenigingen National Board Member"


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

    # ------------------------------------------------------------------ review round 2

    def _hand_assign_profiles(self, user, profiles):
        """Probe shortcut, stated: an administrator's manual grant, written as User Role Profile rows."""
        doc = frappe.get_doc("User", user)
        doc.set("role_profiles", [{"role_profile": p} for p in profiles])
        doc.save()

    def _record_granted(self, user, profiles):
        doc = frappe.get_doc("User", user)
        record_sync_granted_profiles(doc, profiles)
        doc.save()

    def _unlinked_holder(self, held, recorded):
        """A User with NO Member link that holds ``held`` profiles, of which the sync granted ``recorded``."""
        user = self.create_test_user(f"w702.solo.{frappe.generate_hash(length=8)}@test.invalid")
        self.track_doc("User", user.name)
        self._hand_assign_profiles(user.name, held)
        self._record_granted(user.name, recorded)
        self.assertIn(BOARD_ROLE, self._roles(user.name), "fixture: the held profiles confer the role")
        return user.name

    def test_unlinked_helper_keeps_manual_treasurer_and_national_profiles(self):
        """Control for 'strip every board-conferring profile': only the sync-granted one goes."""
        user = self._unlinked_holder([PROFILE_BOARD_MEMBER, TREASURER, NATIONAL], [PROFILE_BOARD_MEMBER])

        self.assertTrue(assign_chapter_board_role(user))

        self._save_user(user)
        self.assertEqual(set(get_user_role_profiles(user)), {TREASURER, NATIONAL})
        self.assertIn(BOARD_ROLE, self._roles(user), "still conferred by the manual profiles")

    def test_unlinked_helper_strips_a_builtin_profile_only_when_nothing_was_recorded(self):
        """The bootstrap case (None): built-in profiles are the sync's, so the board one goes."""
        user = self._unlinked_holder([PROFILE_BOARD_MEMBER], [])
        frappe.db.set_value("User", user, calculator.SYNC_GRANTED_FIELD, None, update_modified=False)
        self.assertIsNone(calculator.read_sync_granted_profiles(user), "fixture: nothing recorded")

        self.assertTrue(assign_chapter_board_role(user))

        self._assert_withdrawn_after_a_user_save(user)

    def test_a_manual_treasurer_profile_is_not_a_failed_withdrawal(self):
        """Post-condition control: the role surviving through a manual profile must not raise."""
        person = self._person_702("Manual")
        self._seat_702(person)
        self._hand_assign_profiles(person.user, [PROFILE_BOARD_MEMBER, TREASURER])
        self._record_granted(person.user, [PROFILE_BOARD_MEMBER])
        self._vacate_behind_the_hooks(person)

        update_all_chapter_board_roles()

        self._save_user(person.user)
        self.assertNotIn(PROFILE_BOARD_MEMBER, get_user_role_profiles(person.user))
        self.assertIn(TREASURER, get_user_role_profiles(person.user))

    def test_one_failing_user_does_not_stop_the_sweep_for_the_others(self):
        from verenigingen.verenigingen.doctype.chapter.managers import BoardAccessWithdrawalError

        bad, good = self._person_702("Bad"), self._person_702("Good")
        for person in (bad, good):
            self._seat_702(person)
            self._vacate_behind_the_hooks(person)
        real_sync = sync_user_role_profile

        def refuse_for_bad(user, *args, **kwargs):
            if user == bad.user:
                raise BoardAccessWithdrawalError("boom")
            return real_sync(user, *args, **kwargs)

        # Mock justified: injects a failure for one user at the profile-sync boundary.
        with mock.patch.object(calculator, "sync_user_role_profile", side_effect=refuse_for_bad):
            with self.assertRaises(BoardAccessWithdrawalError) as raised:
                update_all_chapter_board_roles()

        self.assertIn(bad.user, str(raised.exception))
        self.assertNotIn(good.user, str(raised.exception))
        self._assert_withdrawn_after_a_user_save(good.user)

    def test_a_refused_user_is_rolled_back_while_another_users_withdrawal_persists(self):
        """The refusal comes AFTER the real sync stripped the profile and role, so only the
        per-user savepoint can put the refused user back. A plain try/except would leave them
        half-withdrawn (profile and role gone, yet reported as failed)."""
        from verenigingen.verenigingen.doctype.chapter.managers import BoardAccessWithdrawalError

        bad, good = self._person_702("RollBad"), self._person_702("RollGood")
        for person in (bad, good):
            self._seat_702(person)
            self._vacate_behind_the_hooks(person)
        self._assert_seated(bad.user)
        real_attached = permissions._sync_owned_board_profiles_attached

        def refuse_for_bad(user):
            # The real sync has already run for this user by the time the post-condition asks.
            if user == bad.user:
                self.assertNotIn(BOARD_ROLE, self._roles(user), "fixture: the write happened first")
                return [PROFILE_BOARD_MEMBER]
            return real_attached(user)

        # Mock justified: forces the post-condition to refuse one user after the writes.
        with mock.patch.object(permissions, "_sync_owned_board_profiles_attached", side_effect=refuse_for_bad):
            with self.assertRaises(BoardAccessWithdrawalError) as raised:
                update_all_chapter_board_roles()

        self.assertIn(bad.user, str(raised.exception))
        self._assert_seated(bad.user)  # back to the pre-sweep state, not half-withdrawn
        self.assertNotIn(BOARD_ROLE, self._roles(good.user))
        self.assertNotIn(PROFILE_BOARD_MEMBER, get_user_role_profiles(good.user))

    def test_a_failed_profile_recalculation_names_the_user_and_the_fix(self):
        """Staff re-linking a Member hit this; the message must say whose User and what to do."""
        from verenigingen.verenigingen.doctype.chapter.managers import BoardAccessWithdrawalError

        person = self._person_702("Msg")
        self._seat_702(person)
        self._vacate_behind_the_hooks(person)
        # Mock justified: reproduces the sync's failure result for an invalid role row.
        failure = {"success": False, "error": "Could not find Row #2: Role: Nonexistent Role 702"}
        with mock.patch.object(calculator, "sync_user_role_profile", return_value=failure):
            with self.assertRaises(BoardAccessWithdrawalError) as raised:
                assign_chapter_board_role(person.user)

        message = str(raised.exception)
        self.assertIn(person.user, message)
        self.assertIn("Nonexistent Role 702", message)
        self.assertIn("role row", message)

    def test_an_orphan_has_role_row_is_skipped_and_recorded_not_fatal(self):
        ghost = f"w702.ghost.{frappe.generate_hash(length=8)}@test.invalid"
        frappe.get_doc(
            {
                "doctype": "Has Role",
                "parent": ghost,
                "parenttype": "User",
                "parentfield": "roles",
                "role": BOARD_ROLE,
            }
        ).db_insert()
        self.addCleanup(frappe.db.delete, "Has Role", {"parent": ghost})
        person = self._person_702("Beside")
        self._seat_702(person)
        self._vacate_behind_the_hooks(person)

        update_all_chapter_board_roles()  # must not raise DoesNotExist

        self._assert_withdrawn_after_a_user_save(person.user)
        logged = frappe.get_all(
            "Error Log",
            filters={"method": ["like", "%orphan Has Role row%"], "error": ["like", f"%{ghost}%"]},
            pluck="name",
        )
        self.assertTrue(logged, "the skipped orphan must be recorded as an orphan, not as a crash")
        self.assertTrue(frappe.db.exists("Has Role", {"parent": ghost}), "recorded, not deleted")

    # ------------------------------------------------------------------ hooks must not swallow it

    def test_a_member_save_is_aborted_by_a_failed_withdrawal(self):
        from verenigingen.verenigingen.doctype.chapter.managers import BoardAccessWithdrawalError

        old = self._person_702("HookM")
        self._seat_702(old)
        new_user = self.create_test_user(f"w702.hook.{frappe.generate_hash(length=8)}@test.invalid")
        self.track_doc("User", new_user.name)
        member = frappe.get_doc("Member", old.member)
        member.user = new_user.name
        # The seat is gone, so the old user's withdrawal is what the hook attempts.
        self._vacate_behind_the_hooks(old)

        # Mock justified: the old user is unlinked by now (so no profile sync runs); this makes
        # the post-condition see a surviving sync-owned profile, i.e. a withdrawal that failed.
        with mock.patch(
            "verenigingen.permissions._sync_owned_board_profiles_attached", return_value=[PROFILE_BOARD_MEMBER]
        ):
            with self.assertRaises(BoardAccessWithdrawalError):
                member.save()

    def test_a_chapter_role_save_is_aborted_by_a_failed_withdrawal(self):
        from verenigingen.verenigingen.doctype.chapter.managers import BoardAccessWithdrawalError

        person = self._person_702("HookR")
        self._seat_702(person)
        role = frappe.get_doc("Chapter Role", self.chapter_role)
        role.is_active = 0
        # Mock justified: the failure is injected where the handler delegates.
        with mock.patch(
            "verenigingen.services.chapter.chapter_role_events.assign_chapter_board_role",
            side_effect=BoardAccessWithdrawalError("boom"),
        ):
            with self.assertRaises(BoardAccessWithdrawalError):
                role.save()

    # ------------------------------------------------------------------ non-resumable errors

    def test_a_deadlock_is_not_swallowed_by_the_helper_or_the_sweep(self):
        person = self._person_702("Dead")
        self._seat_702(person)
        self._vacate_behind_the_hooks(person)
        # Mock justified: a real deadlock cannot be provoked deterministically.
        with mock.patch.object(calculator, "sync_user_role_profile", side_effect=frappe.QueryDeadlockError):
            with self.assertRaises(frappe.QueryDeadlockError):
                assign_chapter_board_role(person.user)
            with self.assertRaises(frappe.QueryDeadlockError):
                update_all_chapter_board_roles()
