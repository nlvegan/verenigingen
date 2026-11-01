"""A seat on the national chapter's board grants the national profiles (#1615).

Policy (maintainer, 2026-10-11): the chapter set as
``Verenigingen Settings.national_board_chapter`` confers ``Verenigingen Treasurer``
on its treasurer seat and ``Verenigingen National Board Member`` on every other
seat. Treasurer seats on other chapters are unchanged. An explicit profile mapping
on the national chapter keeps winning. Seats are created and vacated through the
real flows (a Chapter save, ``BoardManager.remove_board_member``), and profiles are
read back from ``User.role_profiles``.

The profiles are asserted, never the literal roles of the same name (#1512: the
National Board Member profile does not grant its namesake role).
"""

import frappe

from verenigingen.services.member.account.user_role_profile_calculator import (
    PROFILE_BOARD_MEMBER,
    get_user_role_profiles,
    sync_user_role_profile,
)
from verenigingen.tests.utils.base import VereningingenTestCase

NATIONAL_MEMBER = "Verenigingen National Board Member"
NATIONAL_TREASURER = "Verenigingen Treasurer"
MAPPED_PROFILE = "Verenigingen Auditor"  # neither national nor the board default


class TestNationalBoardProfiles(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.national = self.create_test_chapter(
            chapter_name=f"National {frappe.generate_hash(length=6)}", postal_codes="1000-1999", published=1
        )
        self.other = self.create_test_chapter(
            chapter_name=f"Other {frappe.generate_hash(length=6)}", postal_codes="2000-2999", published=1
        )
        old = frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter")
        self.addCleanup(frappe.db.set_single_value, "Verenigingen Settings", "national_board_chapter", old)
        frappe.db.set_single_value("Verenigingen Settings", "national_board_chapter", self.national.name)

    def tearDown(self):
        """Track the stub Employees that role-profile assignment created (#1694).

        Seating a board member applies a profile carrying the Employee role, and
        _ensure_employee_for_profile() inserts and COMMITS an Employee for that
        User. Nothing here created it, so nothing tracked it: the User was deleted
        and the Employee stayed behind with a dangling user_id (same shape as
        #1689). Cleanup runs in reverse registration order, so registering the
        Employee AFTER its User deletes the Employee first.

        After the drain, assert none survived: this fires on every test in the
        module that seats a user, without re-running any test.
        """
        users = [d["name"] for d in self._test_docs if d["doctype"] == "User"]
        for user in users:
            for employee in frappe.get_all("Employee", filters={"user_id": user}, pluck="name"):
                self.track_doc("Employee", employee)
        super().tearDown()
        survivors = frappe.get_all("Employee", filters={"user_id": ["in", users or [""]]}, pluck="name")
        self.assertEqual(survivors, [], "Employee rows outlived their User (#1694)")

    # ------------------------------------------------------------------ helpers

    def _chapter_role_labelled(self, label):
        # The treasurer seat is recognised by its exact name, so those two are not suffixed.
        if label in ("Treasurer", "Penningmeester"):
            if not frappe.db.exists("Chapter Role", label):
                frappe.get_doc(
                    {"doctype": "Chapter Role", "role_name": label, "permissions_level": "Basic", "is_active": 1}
                ).insert()
                self.track_doc("Chapter Role", label)
            return label
        name = f"{label} {frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {"doctype": "Chapter Role", "role_name": name, "permissions_level": "Basic", "is_active": 1}
        ).insert()
        self.track_doc("Chapter Role", name)
        return name

    def _hold_a_board_seat(self, chapter, role_label):
        """Seat a fresh volunteer (with a real User) through a Chapter save."""
        email = f"natboard.{frappe.generate_hash(length=8)}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        member = self.create_test_member(first_name="Nat", last_name="Board", email=email, status="Active")
        member.db_set("user", user.name, update_modified=False)
        volunteer = self.create_test_volunteer(member=member.name)
        role = self._chapter_role_labelled(role_label)
        self.add_board_member_to_chapter(frappe.get_doc("Chapter", chapter.name), volunteer, role, email=email)
        return frappe._dict(user=user.name, volunteer=volunteer.name, role=role)

    def _profiles(self, seat):
        sync_user_role_profile(seat.user)  # idempotent; the seating flow already ran one
        return get_user_role_profiles(seat.user)

    # ------------------------------------------------------------------- tests

    def test_a_treasurer_seat_on_the_national_board_gets_the_treasurer_profile(self):
        seat = self._hold_a_board_seat(self.national, "Treasurer")

        profiles = self._profiles(seat)

        self.assertIn(NATIONAL_TREASURER, profiles)
        self.assertNotIn(NATIONAL_MEMBER, profiles)

    def test_a_dutch_penningmeester_seat_is_a_treasurer_too(self):
        """Same keyword rule as the accounting priority, English and Dutch."""
        seat = self._hold_a_board_seat(self.national, "Penningmeester")

        self.assertIn(NATIONAL_TREASURER, self._profiles(seat))

    def test_accounting_sounding_seats_are_not_the_treasurer(self):
        """The treasurer profile grants accounting roles; only the treasurer seat may get it."""
        for label in ("Finance Officer", "Controller", "Financial Controller", "Accounting Committee"):
            seat = self._hold_a_board_seat(self.national, label)

            profiles = self._profiles(seat)

            self.assertIn(NATIONAL_MEMBER, profiles, label)
            self.assertNotIn(NATIONAL_TREASURER, profiles, label)

    def test_any_other_seat_on_the_national_board_gets_the_national_board_member_profile(self):
        seat = self._hold_a_board_seat(self.national, "Secretary")

        profiles = self._profiles(seat)

        self.assertIn(NATIONAL_MEMBER, profiles)
        self.assertNotIn(NATIONAL_TREASURER, profiles)
        self.assertNotIn(PROFILE_BOARD_MEMBER, profiles)

    def test_a_treasurer_seat_on_another_chapter_is_unchanged(self):
        seat = self._hold_a_board_seat(self.other, "Treasurer")

        profiles = self._profiles(seat)

        self.assertIn(PROFILE_BOARD_MEMBER, profiles)
        self.assertNotIn(NATIONAL_TREASURER, profiles)
        self.assertNotIn(NATIONAL_MEMBER, profiles)

    def test_a_non_treasurer_seat_on_another_chapter_gets_no_national_profile(self):
        seat = self._hold_a_board_seat(self.other, "Secretary")

        profiles = self._profiles(seat)

        self.assertNotIn(NATIONAL_MEMBER, profiles)
        self.assertNotIn(NATIONAL_TREASURER, profiles)

    def test_an_explicit_default_mapping_on_the_national_chapter_wins(self):
        # Administrator configures it, as the mapping guard requires.
        self.national.reload()
        self.national.default_board_role_profile = MAPPED_PROFILE
        self.national.save()
        seat = self._hold_a_board_seat(self.national, "Secretary")

        profiles = self._profiles(seat)

        self.assertIn(MAPPED_PROFILE, profiles)
        self.assertNotIn(NATIONAL_MEMBER, profiles)

    def test_an_explicit_role_specific_mapping_wins_for_that_role_only(self):
        role = self._chapter_role_labelled("Secretary")
        self.national.reload()
        self.national.enable_board_role_specific_profiles = 1
        self.national.default_board_role_profile = None
        self.national.append("board_role_specific_profiles", {"chapter_role": role, "role_profile": MAPPED_PROFILE})
        self.national.save()
        mapped = self._seat_with_role(role)
        unmapped = self._hold_a_board_seat(self.national, "Chair")

        self.assertIn(MAPPED_PROFILE, self._profiles(mapped))
        self.assertIn(NATIONAL_MEMBER, self._profiles(unmapped))

    def _seat_with_role(self, role):
        email = f"natboard.{frappe.generate_hash(length=8)}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        member = self.create_test_member(first_name="Nat", last_name="Mapped", email=email, status="Active")
        member.db_set("user", user.name, update_modified=False)
        volunteer = self.create_test_volunteer(member=member.name)
        self.add_board_member_to_chapter(
            frappe.get_doc("Chapter", self.national.name), volunteer, role, email=email
        )
        return frappe._dict(user=user.name, volunteer=volunteer.name, role=role)

    def test_leaving_the_national_board_withdraws_the_profile(self):
        for label, profile in (("Treasurer", NATIONAL_TREASURER), ("Secretary", NATIONAL_MEMBER)):
            seat = self._hold_a_board_seat(self.national, label)
            self.assertIn(profile, self._profiles(seat), "the seat must grant it before it is vacated")

            chapter = frappe.get_doc("Chapter", self.national.name)
            result = chapter.board_manager.remove_board_member(seat.volunteer, notify=False)
            self.assertTrue(result["success"], result)

            self.assertNotIn(profile, get_user_role_profiles(seat.user), label)

    def test_a_chapter_that_stops_being_national_loses_the_profile_on_the_next_sync(self):
        seat = self._hold_a_board_seat(self.national, "Secretary")
        self.assertIn(NATIONAL_MEMBER, self._profiles(seat))

        frappe.db.set_single_value("Verenigingen Settings", "national_board_chapter", self.other.name)
        sync_user_role_profile(seat.user)

        profiles = get_user_role_profiles(seat.user)
        self.assertNotIn(NATIONAL_MEMBER, profiles)
        self.assertIn(PROFILE_BOARD_MEMBER, profiles)

    def test_with_no_national_chapter_configured_nothing_is_national(self):
        frappe.db.set_single_value("Verenigingen Settings", "national_board_chapter", None)
        seat = self._hold_a_board_seat(self.national, "Treasurer")

        profiles = self._profiles(seat)

        self.assertNotIn(NATIONAL_TREASURER, profiles)
        self.assertNotIn(NATIONAL_MEMBER, profiles)

    def test_a_surviving_national_profile_is_reported_as_unwithdrawn_access(self):
        """The post-removal check knows the national profiles are conferred by this chapter.

        The seat is deleted behind every hook's back (as test_board_role_withdrawal does)
        so the profile stays attached, which is the leak the check exists to catch.
        """
        from verenigingen.verenigingen.doctype.chapter.managers import BoardAccessWithdrawalError

        seat = self._hold_a_board_seat(self.national, "Secretary")
        self.assertIn(NATIONAL_MEMBER, self._profiles(seat))
        frappe.db.delete("Chapter Board Member", {"volunteer": seat.volunteer})

        chapter = frappe.get_doc("Chapter", self.national.name)
        with self.assertRaises(BoardAccessWithdrawalError) as caught:
            chapter.board_manager._assert_board_access_withdrawn(seat.volunteer)

        self.assertIn(NATIONAL_MEMBER, str(caught.exception))

    # ---- #1615 maintainer rulings (2026-10-13), driven through real flows

    STAFF = "Verenigingen Staff"
    ADMINISTRATOR = "Verenigingen Administrator"

    def _staff_team(self, profile):
        from verenigingen.setup import create_default_team_roles

        create_default_team_roles()
        team = frappe.get_doc(
            {
                "doctype": "Team",
                "team_name": f"NBP Staff {frappe.generate_hash(length=6)}",
                "status": "Active",
                "team_type": "Project Team",
                "start_date": frappe.utils.today(),
                "default_role_profile": profile,
                "is_association_wide": 1,
            }
        )
        team.insert()
        self.track_doc("Team", team.name)
        return team.name

    def _staffer_on_the_national_board(self, staff_profile, role_label="Secretary"):
        """A volunteer on an association-wide team (real Team Member row), THEN seated."""
        email = f"natstaff.{frappe.generate_hash(length=8)}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        member = self.create_test_member(first_name="Nat", last_name="Staff", email=email, status="Active")
        member.db_set("user", user.name, update_modified=False)
        volunteer = self.create_test_volunteer(member=member.name)
        team = frappe.get_doc("Team", self._staff_team(staff_profile))
        team.append(
            "team_members",
            {"volunteer": volunteer.name, "team_role": "Team Member", "from_date": frappe.utils.today(), "status": "Active"},
        )
        team.save()
        sync_user_role_profile(user.name)
        before = get_user_role_profiles(user.name)
        role = self._chapter_role_labelled(role_label)
        self.add_board_member_to_chapter(
            frappe.get_doc("Chapter", self.national.name), volunteer, role, email=email
        )
        return frappe._dict(user=user.name, volunteer=volunteer.name, role=role, before=before)

    # ---- ruling 1: added on top, never replacing

    def test_a_staffer_seated_on_the_national_board_keeps_staff_and_gains_the_national_profile(self):
        seat = self._staffer_on_the_national_board(self.STAFF)
        self.assertEqual(seat.before[0], self.STAFF, "fixture: the staffer holds Staff before being seated")

        profiles = get_user_role_profiles(seat.user)

        self.assertIn(self.STAFF, profiles)
        self.assertIn(NATIONAL_MEMBER, profiles)

    def test_an_administrator_profile_survives_a_national_seat(self):
        seat = self._staffer_on_the_national_board(self.ADMINISTRATOR)
        self.assertEqual(seat.before[0], self.ADMINISTRATOR)

        profiles = get_user_role_profiles(seat.user)

        self.assertIn(self.ADMINISTRATOR, profiles)
        self.assertIn(NATIONAL_MEMBER, profiles)
        self.assertIn("Verenigingen Administrator", frappe.get_roles(seat.user))

    def test_a_staffer_treasurer_gets_both_and_loses_only_the_national_one_on_leaving(self):
        seat = self._staffer_on_the_national_board(self.STAFF, role_label="Treasurer")
        profiles = get_user_role_profiles(seat.user)
        self.assertIn(self.STAFF, profiles)
        self.assertIn(NATIONAL_TREASURER, profiles)

        chapter = frappe.get_doc("Chapter", self.national.name)
        self.assertTrue(chapter.board_manager.remove_board_member(seat.volunteer, notify=False)["success"])

        profiles = get_user_role_profiles(seat.user)
        self.assertIn(self.STAFF, profiles)
        self.assertNotIn(NATIONAL_TREASURER, profiles)

    def test_the_additive_sync_is_idempotent(self):
        seat = self._staffer_on_the_national_board(self.STAFF)

        again = sync_user_role_profile(seat.user)

        self.assertTrue(again["success"], again)
        self.assertFalse(again["role_changed"], again)

    # ---- ruling 2 / #1660: national_board_chapter changes

    def _change_national_chapter(self, chapter_name):
        settings = frappe.get_doc("Verenigingen Settings")
        settings.national_board_chapter = chapter_name
        settings.save()

    def test_changing_the_national_chapter_recalculates_both_chapters_seat_holders(self):
        old_holder = self._hold_a_board_seat(self.national, "Secretary")
        new_holder = self._hold_a_board_seat(self.other, "Secretary")
        self.assertIn(NATIONAL_MEMBER, get_user_role_profiles(old_holder.user), "fixture")
        self.assertNotIn(NATIONAL_MEMBER, get_user_role_profiles(new_holder.user), "fixture")

        self._change_national_chapter(self.other.name)

        old_profiles = get_user_role_profiles(old_holder.user)
        self.assertNotIn(NATIONAL_MEMBER, old_profiles)
        self.assertIn(PROFILE_BOARD_MEMBER, old_profiles)
        self.assertIn(NATIONAL_MEMBER, get_user_role_profiles(new_holder.user))

    def test_a_national_profile_stored_on_the_old_chapter_is_not_trusted_after_the_change(self):
        """The mapping guard let it in while the chapter was national; it must not outlive that."""
        self.national.reload()
        self.national.default_board_role_profile = NATIONAL_MEMBER
        self.national.save()
        holder = self._hold_a_board_seat(self.national, "Secretary")
        self.assertIn(NATIONAL_MEMBER, get_user_role_profiles(holder.user), "fixture: still national")

        self._change_national_chapter(self.other.name)

        profiles = get_user_role_profiles(holder.user)
        self.assertNotIn(NATIONAL_MEMBER, profiles)
        self.assertIn(PROFILE_BOARD_MEMBER, profiles)

    def test_a_role_specific_national_mapping_on_a_non_national_chapter_is_not_trusted(self):
        role = self._chapter_role_labelled("Secretary")
        self.national.reload()
        self.national.enable_board_role_specific_profiles = 1
        self.national.append("board_role_specific_profiles", {"chapter_role": role, "role_profile": NATIONAL_TREASURER})
        self.national.save()
        holder = self._seat_with_role(role)
        self.assertIn(NATIONAL_TREASURER, get_user_role_profiles(holder.user), "fixture: still national")

        self._change_national_chapter(self.other.name)

        self.assertNotIn(NATIONAL_TREASURER, get_user_role_profiles(holder.user))

    # ---- ruling 3: an existing National Board Member seats a new volunteer

    def _new_volunteer(self):
        email = f"natnew.{frappe.generate_hash(length=8)}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        member = self.create_test_member(first_name="Nat", last_name="New", email=email, status="Active")
        member.db_set("user", user.name, update_modified=False)
        volunteer = self.create_test_volunteer(member=member.name)
        return frappe._dict(user=user.name, volunteer=volunteer.name, email=email)

    def _an_existing_national_board_member(self):
        nbm = self._hold_a_board_seat(self.national, "Chair")
        self.assertIn(NATIONAL_MEMBER, get_user_role_profiles(nbm.user), "fixture: a real NBM")
        return nbm

    def test_an_nbm_seats_a_new_volunteer_through_the_chapter_endpoint(self):
        import json

        from frappe.handler import run_doc_method
        from werkzeug.test import EnvironBuilder
        from werkzeug.wrappers import Request

        original_request = getattr(frappe.local, "request", None)
        self.addCleanup(setattr, frappe.local, "request", original_request)
        # Mock justified: Infrastructure - run_doc_method reads the HTTP method of the request
        frappe.local.request = Request(EnvironBuilder(method="POST").get_environ())
        original_response = getattr(frappe.local, "response", None)
        self.addCleanup(setattr, frappe.local, "response", original_response)
        # Mock justified: Infrastructure - run_doc_method appends the doc to response.docs, which
        # only a real request cycle creates (an earlier test may have left a bare _dict() behind)
        frappe.local.response = frappe._dict(docs=[])
        nbm = self._an_existing_national_board_member()
        new = self._new_volunteer()
        role = self._chapter_role_labelled("Secretary")

        frappe.set_user(nbm.user)
        self.addCleanup(frappe.set_user, "Administrator")
        run_doc_method(
            method="add_board_member",
            dt="Chapter",
            dn=self.national.name,
            args=json.dumps({"volunteer": new.volunteer, "role": role}),
        )

        self.assertTrue(
            frappe.db.exists("Chapter Board Member", {"parent": self.national.name, "volunteer": new.volunteer, "is_active": 1}),
            "the seat must exist",
        )
        self.assertIn(NATIONAL_MEMBER, get_user_role_profiles(new.user))

    def test_an_nbm_seats_a_new_volunteer_by_saving_the_chapter(self):
        nbm = self._an_existing_national_board_member()
        new = self._new_volunteer()
        role = self._chapter_role_labelled("Secretary")

        frappe.set_user(nbm.user)
        self.addCleanup(frappe.set_user, "Administrator")
        chapter = frappe.get_doc("Chapter", self.national.name)
        chapter.append(
            "board_members",
            {"volunteer": new.volunteer, "chapter_role": role, "from_date": frappe.utils.today(), "is_active": 1, "email": new.email},
        )
        chapter.save()

        self.assertIn(NATIONAL_MEMBER, get_user_role_profiles(new.user))

    # ---- security review of 44a00a7eb: the sync must be non-destructive

    def _assign_profiles_directly(self, user, profiles):
        """Hand-assign profiles as an administrator would (User Role Profile rows)."""
        doc = frappe.get_doc("User", user)
        doc.set("role_profiles", [{"role_profile": name} for name in profiles])
        doc.save()

    def test_a_board_member_seating_an_admin_user_changes_nothing_but_the_seat_derived_profiles(self):
        """CRITICAL-1: a plain chapter board member's Chapter save must not rewrite another user's profiles."""
        actor = self._hold_a_board_seat(self.other, "Secretary")
        victim = self._new_volunteer()
        manual = ["HR", "Verenigingen System Administrator"]
        self._assign_profiles_directly(victim.user, manual)
        frappe.get_doc("User", victim.user).add_roles("System Manager")
        # Read the Has Role rows directly: frappe.get_roles goes through the per-user role cache.
        roles_before = set(
            frappe.get_all("Has Role", filters={"parent": victim.user, "parenttype": "User"}, pluck="role")
        )
        role = self._chapter_role_labelled("Chair")

        frappe.set_user(actor.user)
        self.addCleanup(frappe.set_user, "Administrator")
        chapter = frappe.get_doc("Chapter", self.other.name)
        chapter.append(
            "board_members",
            {
                "volunteer": victim.volunteer,
                "chapter_role": role,
                "from_date": frappe.utils.today(),
                "is_active": 1,
                "email": victim.email,
            },
        )
        chapter.save()

        profiles = set(get_user_role_profiles(victim.user))
        self.assertTrue(set(manual) <= profiles, f"manual profiles were stripped: {profiles}")
        self.assertIn(PROFILE_BOARD_MEMBER, profiles, "the seat-derived addition is still made")
        frappe.clear_cache(user=victim.user)
        self.assertIn("System Manager", frappe.get_roles(victim.user))
        roles_after = set(
            frappe.get_all("Has Role", filters={"parent": victim.user, "parenttype": "User"}, pluck="role")
        )
        self.assertTrue(roles_before <= roles_after, roles_before - roles_after)

    def test_a_resync_never_drops_a_manually_assigned_profile(self):
        user = self._hold_a_board_seat(self.national, "Secretary").user
        manual = ["Verenigingen Administrator", "Verenigingen Auditor"]
        self._assign_profiles_directly(user, manual + [NATIONAL_MEMBER])

        sync_user_role_profile(user)

        profiles = set(get_user_role_profiles(user))
        self.assertTrue(set(manual) <= profiles, profiles)
        self.assertIn(NATIONAL_MEMBER, profiles)

    def test_a_stale_derived_profile_is_still_withdrawn_next_to_manual_ones(self):
        """Control: non-destructive must not mean never-removing what the sync granted."""
        seat = self._hold_a_board_seat(self.national, "Treasurer")
        self._assign_profiles_directly(seat.user, [*get_user_role_profiles(seat.user), "HR"])
        chapter = frappe.get_doc("Chapter", self.national.name)
        self.assertTrue(chapter.board_manager.remove_board_member(seat.volunteer, notify=False)["success"])

        profiles = set(get_user_role_profiles(seat.user))

        self.assertIn("HR", profiles)
        self.assertNotIn(NATIONAL_TREASURER, profiles)

    # ---- MEDIUM-3: a team cannot fill the national slot

    def test_a_team_whose_stored_default_is_a_national_profile_confers_nothing_national(self):
        from verenigingen.setup import create_default_team_roles

        create_default_team_roles()
        seat = self._hold_a_board_seat(self.other, "Secretary")  # not national, so no national seat
        team = frappe.get_doc(
            {
                "doctype": "Team",
                "team_name": f"NBP Legacy {frappe.generate_hash(length=6)}",
                "status": "Active",
                "team_type": "Project Team",
                "start_date": frappe.utils.today(),
            }
        )
        team.insert()
        self.track_doc("Team", team.name)
        team.append(
            "team_members",
            {
                "volunteer": seat.volunteer,
                "team_role": "Team Member",
                "from_date": frappe.utils.today(),
                "status": "Active",
            },
        )
        team.save()
        # Probe shortcut, stated: the mapping guard now refuses this value on a Team, so a
        # row stored before the guard existed (legacy data) is simulated with a direct write.
        frappe.db.set_value("Team", team.name, "default_role_profile", NATIONAL_MEMBER)
        frappe.clear_document_cache("Team", team.name)
        from verenigingen.services.member.account.user_role_profile_calculator import (
            invalidate_profile_config_cache,
        )

        invalidate_profile_config_cache("team", team.name)

        sync_user_role_profile(seat.user)

        self.assertNotIn(NATIONAL_MEMBER, get_user_role_profiles(seat.user))

    # ---- HIGH-2 / #1626: who may repoint the national chapter

    def _settings_change_as(self, roles):
        email = f"setting.{frappe.generate_hash(length=8)}@test.invalid"
        self.create_test_user(email, roles=roles)
        frappe.set_user(email)
        self.addCleanup(frappe.set_user, "Administrator")
        settings = frappe.get_doc("Verenigingen Settings")
        settings.national_board_chapter = self.other.name
        settings.save()

    def test_a_financial_manager_cannot_repoint_the_national_chapter(self):
        with self.assertRaisesRegex(frappe.PermissionError, "Only a Verenigingen Administrator"):
            self._settings_change_as(["Verenigingen Financial Manager"])
        self.assertEqual(
            frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter"), self.national.name
        )

    def test_a_verenigingen_administrator_can_repoint_the_national_chapter(self):
        self._settings_change_as(["Verenigingen Administrator"])
        self.assertEqual(
            frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter"), self.other.name
        )

    def test_a_bare_system_manager_cannot_repoint_the_national_chapter(self):
        """Maintainer ruling on #1626 (2026-10-14): a bare System Manager may not.

        The earlier test asserted the opposite; its premise was the pre-ruling rule.
        """
        with self.assertRaisesRegex(frappe.PermissionError, "Only a Verenigingen Administrator"):
            self._settings_change_as(["System Manager"])
        self.assertEqual(
            frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter"), self.national.name
        )

    def _settings_change_as_profile_holder(self, profile):
        email = f"setting.{frappe.generate_hash(length=8)}@test.invalid"
        self.create_test_user(email, roles=[])
        self.assertNotIn("Verenigingen Administrator", frappe.get_roles(email), "fixture: no role before")
        self._assign_profiles_directly(email, [profile])
        # Frappe materialises a profile's roles as Has Role rows on save, so "role via profile"
        # and "role held directly" are the same state afterwards; this test cannot tell them
        # apart. What it does prove: a user given ONLY the profile (no direct role) is allowed.
        self.assertIn("Verenigingen Administrator", frappe.get_roles(email), "fixture: profile grants it")
        frappe.clear_cache(user=email)
        frappe.set_user(email)
        self.addCleanup(frappe.set_user, "Administrator")
        settings = frappe.get_doc("Verenigingen Settings")
        settings.national_board_chapter = self.other.name
        settings.save()

    def test_a_user_given_only_the_verenigingen_system_administrator_profile_can_repoint_the_national_chapter(self):
        self._settings_change_as_profile_holder("Verenigingen System Administrator")
        self.assertEqual(
            frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter"), self.other.name
        )

    def test_a_user_given_only_the_verenigingen_administrator_profile_can_repoint_the_national_chapter(self):
        self._settings_change_as_profile_holder("Verenigingen Administrator")
        self.assertEqual(
            frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter"), self.other.name
        )

    def test_the_administrator_user_can_repoint_the_national_chapter(self):
        """Control: the Administrator user holds every role, so dropping its special case is safe."""
        self._change_national_chapter(self.other.name)
        self.assertEqual(
            frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter"), self.other.name
        )

    # ---- MEDIUM-4: a failed resync is not silent

    def test_a_failed_resync_after_a_national_chapter_change_is_logged_and_shown(self):
        from unittest import mock

        holder = self._hold_a_board_seat(self.national, "Secretary")
        before = frappe.db.count("Error Log", {"method": "National board chapter change: role profile resync failed"})

        # Mock justified: failure injection at the sync boundary; a real sync failure needs a corrupt User
        with mock.patch(
            "verenigingen.services.member.account.user_role_profile_calculator.sync_user_role_profile",
            return_value={"success": False, "error": "boom", "user": holder.user},
        ):
            self.expectErrorLog()
            self._change_national_chapter(self.other.name)

        self.assertEqual(
            frappe.db.count("Error Log", {"method": "National board chapter change: role profile resync failed"}),
            before + 1,
        )
        self.assertIn(holder.user, " ".join(m.get("message", "") for m in frappe.local.message_log))

    # ---- round 2: production has default teams mapping Administrator / Staff

    def test_default_teams_mapping_administrator_and_staff_do_not_make_them_strippable(self):
        """Default MijnRood teams map VA and Staff; a board member's save must not strip them
        from a user who is in neither team."""
        self._staff_team(self.ADMINISTRATOR)
        self._staff_team(self.STAFF)
        actor = self._hold_a_board_seat(self.other, "Secretary")
        victim = self._new_volunteer()
        manual = ["HR", self.ADMINISTRATOR, self.STAFF]
        self._assign_profiles_directly(victim.user, manual)
        frappe.get_doc("User", victim.user).add_roles("System Manager")
        role = self._chapter_role_labelled("Chair")

        frappe.set_user(actor.user)
        self.addCleanup(frappe.set_user, "Administrator")
        chapter = frappe.get_doc("Chapter", self.other.name)
        chapter.append(
            "board_members",
            {
                "volunteer": victim.volunteer,
                "chapter_role": role,
                "from_date": frappe.utils.today(),
                "is_active": 1,
                "email": victim.email,
            },
        )
        chapter.save()

        self.assertTrue(set(manual) <= set(get_user_role_profiles(victim.user)))
        frappe.clear_cache(user=victim.user)
        self.assertIn("System Manager", frappe.get_roles(victim.user))

    # ---- round 3: provenance is what the SYNC granted, not the existence of a row

    def _nbp_team_member(self, profile, volunteer=None):
        """A volunteer (real User) added to an association-wide team mapped to ``profile``."""
        new = volunteer or self._new_volunteer()
        sync_user_role_profile(new.user)  # a real account has been synced once (records its base profile)
        team = frappe.get_doc("Team", self._staff_team(profile))
        team.append(
            "team_members",
            {
                "volunteer": new.volunteer,
                "team_role": "Team Member",
                "from_date": frappe.utils.today(),
                "status": "Active",
            },
        )
        team.save()
        sync_user_role_profile(new.user)
        return new, team.name

    def test_a_mapped_profile_is_withdrawn_when_the_team_row_is_deleted(self):
        member, team_name = self._nbp_team_member(self.STAFF)
        self.assertIn(self.STAFF, get_user_role_profiles(member.user), "fixture: Staff was granted")

        team = frappe.get_doc("Team", team_name)
        team.remove(team.team_members[0])
        team.save()
        sync_user_role_profile(member.user)

        self.assertNotIn(self.STAFF, get_user_role_profiles(member.user))

    def test_a_mapped_profile_is_withdrawn_when_the_team_row_goes_inactive(self):
        member, team_name = self._nbp_team_member(self.STAFF)
        team = frappe.get_doc("Team", team_name)
        team.team_members[0].status = "Inactive"
        team.save()
        sync_user_role_profile(member.user)

        self.assertNotIn(self.STAFF, get_user_role_profiles(member.user))

    def test_deleting_a_national_seat_in_the_chapter_form_withdraws_and_does_not_raise(self):
        seat = self._hold_a_board_seat(self.national, "Secretary")
        self.assertIn(NATIONAL_MEMBER, get_user_role_profiles(seat.user), "fixture")

        chapter = frappe.get_doc("Chapter", self.national.name)
        row = next(r for r in chapter.board_members if r.volunteer == seat.volunteer)
        chapter.remove(row)
        chapter.save()  # must not raise BoardAccessWithdrawalError for a legitimate removal

        self.assertNotIn(NATIONAL_MEMBER, get_user_role_profiles(seat.user))

    def test_a_team_lead_cannot_strip_a_manual_staff_profile_by_inactivating_the_row(self):
        """R3-3: the lead's own team maps Staff; the victim holds Staff by hand."""
        victim = self._new_volunteer()
        self._assign_profiles_directly(victim.user, [self.STAFF])
        sync_user_role_profile(victim.user)  # the victim's record exists; Staff is not in it
        self.assertIn(self.STAFF, get_user_role_profiles(victim.user), "fixture")
        team_name = self._staff_team(self.STAFF)
        team = frappe.get_doc("Team", team_name)
        team.append(
            "team_members",
            {
                "volunteer": victim.volunteer,
                "team_role": "Team Member",
                "from_date": frappe.utils.today(),
                "status": "Active",
            },
        )
        team.save()
        sync_user_role_profile(victim.user)

        team = frappe.get_doc("Team", team_name)
        team.team_members[0].status = "Inactive"
        team.save()
        sync_user_role_profile(victim.user)

        self.assertIn(self.STAFF, get_user_role_profiles(victim.user))

    def test_a_manual_administrator_profile_survives_a_default_team_row_going_inactive(self):
        """R3-4: Landelijk Beheer maps Administrator; the admin held it before the row existed."""
        admin = self._new_volunteer()
        self._assign_profiles_directly(admin.user, [self.ADMINISTRATOR])
        frappe.get_doc("User", admin.user).add_roles("System Manager")
        sync_user_role_profile(admin.user)  # records the admin's base state; Administrator is manual
        team_name = self._staff_team(self.ADMINISTRATOR)
        team = frappe.get_doc("Team", team_name)
        team.append(
            "team_members",
            {
                "volunteer": admin.volunteer,
                "team_role": "Team Member",
                "from_date": frappe.utils.today(),
                "status": "Active",
            },
        )
        team.save()
        sync_user_role_profile(admin.user)
        team = frappe.get_doc("Team", team_name)
        team.team_members[0].status = "Inactive"
        team.save()
        sync_user_role_profile(admin.user)

        self.assertIn(self.ADMINISTRATOR, get_user_role_profiles(admin.user))
        frappe.clear_cache(user=admin.user)
        self.assertIn("System Manager", frappe.get_roles(admin.user))

    def test_the_documented_bootstrap_residue_a_never_synced_user_is_indistinguishable(self):
        """Characterisation of the known limit, NOT a goal: with NO record yet, a manual profile that
        coincides with a currently-derived one is treated as the sync's own (legacy data)."""
        legacy = self._new_volunteer()
        self._assign_profiles_directly(legacy.user, [self.STAFF])
        team = frappe.get_doc("Team", self._staff_team(self.STAFF))
        team.append(
            "team_members",
            {
                "volunteer": legacy.volunteer,
                "team_role": "Team Member",
                "from_date": frappe.utils.today(),
                "status": "Active",
            },
        )
        team.save()
        sync_user_role_profile(legacy.user)  # first sync ever: Staff is derived and held -> recorded
        team = frappe.get_doc("Team", team.name)
        team.team_members[0].status = "Inactive"
        team.save()
        sync_user_role_profile(legacy.user)

        self.assertNotIn(self.STAFF, get_user_role_profiles(legacy.user))

    # ---- R3-2: the whitelisted remove endpoints

    def _call_remove_endpoint_as(self, roles, fn_path, *args):
        import importlib

        email = f"caller.{frappe.generate_hash(length=8)}@test.invalid"
        user = self.create_test_user(email, roles=roles)
        self._assign_profiles_directly(user.name, [self.STAFF])
        module, name = fn_path.rsplit(".", 1)
        fn = getattr(importlib.import_module(module), name)
        frappe.set_user(email)
        self.addCleanup(frappe.set_user, "Administrator")
        return fn(*args)

    def test_a_staff_caller_cannot_strip_an_admin_victim_with_no_team_row(self):
        victim = self._new_volunteer()
        self._assign_profiles_directly(victim.user, [self.ADMINISTRATOR])
        frappe.get_doc("User", victim.user).add_roles("System Manager")
        team_name = self._staff_team(self.STAFF)

        with self.assertRaisesRegex(frappe.PermissionError, "permission to change role profiles"):
            self._call_remove_endpoint_as(
                ["Verenigingen Staff"],
                "verenigingen.utils.team_role_profile_manager.remove_team_role_profile",
                victim.user,
                team_name,
            )
        self.assertIn(self.ADMINISTRATOR, get_user_role_profiles(victim.user))

    def test_the_remove_guard_refuses_unknown_and_forbidden_chapters_identically(self):
        """The chapter endpoint's own tier already refuses a Staff caller (measured: "Access
        denied"), so the guard behind it is exercised directly, as a Staff user."""
        from verenigingen.services.member.account.role_profile_mapping_guard import (
            require_may_remove_profile_for,
        )

        victim = self._new_volunteer()
        email = f"caller.{frappe.generate_hash(length=8)}@test.invalid"
        self.create_test_user(email, roles=["Verenigingen Staff"])
        frappe.set_user(email)
        self.addCleanup(frappe.set_user, "Administrator")
        seen = []
        for chapter in (self.other.name, "No Such Chapter " + frappe.generate_hash(length=6)):
            frappe.local.message_log = []
            with self.assertRaises(frappe.PermissionError) as caught:
                require_may_remove_profile_for("Chapter", chapter, victim.user)
            log = [{k: v for k, v in m.items() if k != "__frappe_exc_id"} for m in frappe.local.message_log]
            seen.append((str(caught.exception), log))
        self.assertEqual(seen[0], seen[1])

    def test_deleting_a_seat_mapped_to_a_configured_profile_in_the_chapter_form_withdraws_it(self):
        """R3-1: a mapped (non built-in) profile; the row is gone by the time the sync looks."""
        self.other.reload()
        self.other.default_board_role_profile = MAPPED_PROFILE
        self.other.save()
        seat = self._hold_a_board_seat(self.other, "Secretary")
        self.assertIn(MAPPED_PROFILE, get_user_role_profiles(seat.user), "fixture")

        chapter = frappe.get_doc("Chapter", self.other.name)
        chapter.remove(next(r for r in chapter.board_members if r.volunteer == seat.volunteer))
        chapter.save()  # must not raise BoardAccessWithdrawalError

        self.assertNotIn(MAPPED_PROFILE, get_user_role_profiles(seat.user))

    # ---- round 4

    def test_remove_role_profile_does_not_claim_not_assigned_for_a_held_unrecorded_profile(self):
        from verenigingen.utils.team_role_profile_manager import _team_manager

        user = self._new_volunteer()
        team_name = self._staff_team(self.STAFF)
        self._assign_profiles_directly(user.user, [self.STAFF])  # held by hand: not recorded
        sync_user_role_profile(user.user)

        result = _team_manager.remove_role_profile(user.user, team_name)

        self.assertEqual(result["action"], "not_recorded", result)
        self.assertIn(self.STAFF, get_user_role_profiles(user.user))

    def test_a_first_sync_that_records_nothing_still_writes_an_empty_record(self):
        from unittest import mock

        from verenigingen.services.member.account.user_role_profile_calculator import (
            read_sync_granted_profiles,
        )

        user = self._new_volunteer()
        self._assign_profiles_directly(user.user, ["HR"])
        self.assertIsNone(read_sync_granted_profiles(user.user), "fixture: never recorded")

        # Mock justified: no real member derives nothing (Member is always derived); this reaches
        # the empty-record branch of the first sync.
        with mock.patch(
            "verenigingen.services.member.account.user_role_profile_calculator."
            "calculate_user_role_profile_set",
            return_value=[],
        ):
            sync_user_role_profile(user.user)

        self.assertEqual(read_sync_granted_profiles(user.user), [])

    def _acr_requesting(self, user, profile, volunteer_status="Active"):
        """Run the real ACR role-assignment phase for ``user`` with ``role_profile=profile``."""
        from verenigingen.services.member.account.account_creation_manager import AccountCreationManager

        member = frappe.db.get_value("Volunteer", self._volunteer_of(user), "member")
        request = frappe.get_doc(
            {
                "doctype": "Account Creation Request",
                "request_type": "Member",
                "source_record": member,
                "email": user,
                "full_name": "Requested Profile",
                "status": "Queued",
                "role_profile": profile,
                "business_justification": "requested-profile retention test",
            }
        )
        request.insert()
        self.track_doc("Account Creation Request", request.name)
        manager = AccountCreationManager(request.name)
        manager.load_request()
        manager.created_user = user
        manager.assign_roles_and_profile()

    def _volunteer_of(self, user):
        member = frappe.db.get_value("Member", {"user": user}, "name")
        return frappe.db.get_value("Volunteer", {"member": member}, "name")

    def test_a_requested_volunteer_profile_is_withdrawn_once_the_volunteer_is_inactive(self):
        """The ACR asked for Volunteer; the calculator derives it, so it must also end it."""
        new = self._new_volunteer()
        self._acr_requesting(new.user, "Verenigingen Volunteer")
        sync_user_role_profile(new.user)
        self.assertIn("Verenigingen Volunteer", get_user_role_profiles(new.user), "fixture: derived, kept")

        # Labelled shortcut: a direct status write stands in for the volunteer leaving.
        frappe.db.set_value("Volunteer", new.volunteer, "status", "Inactive")
        sync_user_role_profile(new.user)

        self.assertNotIn("Verenigingen Volunteer", get_user_role_profiles(new.user))

    def test_a_requested_board_profile_without_a_seat_is_withdrawn_by_the_next_sync(self):
        new = self._new_volunteer()
        sync_user_role_profile(new.user)
        self._acr_requesting(new.user, PROFILE_BOARD_MEMBER)
        self.assertIn(PROFILE_BOARD_MEMBER, get_user_role_profiles(new.user), "fixture")

        sync_user_role_profile(new.user)

        self.assertNotIn(PROFILE_BOARD_MEMBER, get_user_role_profiles(new.user))

    def test_a_requested_profile_already_held_is_still_recorded(self):
        new = self._new_volunteer()
        self._assign_profiles_directly(new.user, [PROFILE_BOARD_MEMBER])
        sync_user_role_profile(new.user)
        self._assign_profiles_directly(new.user, [PROFILE_BOARD_MEMBER])  # held at ACR time
        self._acr_requesting(new.user, PROFILE_BOARD_MEMBER)

        sync_user_role_profile(new.user)

        self.assertNotIn(PROFILE_BOARD_MEMBER, get_user_role_profiles(new.user))

    def test_a_custom_requested_profile_is_kept_by_the_sync(self):
        new = self._new_volunteer()
        sync_user_role_profile(new.user)
        self._acr_requesting(new.user, MAPPED_PROFILE)  # Verenigingen Auditor: not built in

        sync_user_role_profile(new.user)

        self.assertIn(MAPPED_PROFILE, get_user_role_profiles(new.user))

    # ---- #1612 ruling (a): explicit full activation leaves the volunteer in Onboarding

    def test_the_calculator_derives_volunteer_for_onboarding_but_not_for_new(self):
        new = self._new_volunteer()
        sync_user_role_profile(new.user)
        # Labelled shortcut: direct status writes stand in for the states under test.
        frappe.db.set_value("Volunteer", new.volunteer, "status", "New")
        sync_user_role_profile(new.user)
        self.assertNotIn("Verenigingen Volunteer", get_user_role_profiles(new.user), "control: New")

        frappe.db.set_value("Volunteer", new.volunteer, "status", "Onboarding")
        sync_user_role_profile(new.user)

        self.assertIn("Verenigingen Volunteer", get_user_role_profiles(new.user))

    def test_an_activation_request_moves_a_new_volunteer_to_onboarding(self):
        new = self._new_volunteer()
        frappe.db.set_value("Volunteer", new.volunteer, "status", "New")
        self._acr_requesting(new.user, "Verenigingen Volunteer")

        sync_user_role_profile(new.user)

        self.assertEqual(frappe.db.get_value("Volunteer", new.volunteer, "status"), "Onboarding")
        self.assertIn("Verenigingen Volunteer", get_user_role_profiles(new.user))

    def test_an_activation_request_leaves_other_volunteer_statuses_alone(self):
        new = self._new_volunteer()
        frappe.db.set_value("Volunteer", new.volunteer, "status", "Inactive")

        self._acr_requesting(new.user, "Verenigingen Volunteer")

        self.assertEqual(frappe.db.get_value("Volunteer", new.volunteer, "status"), "Inactive")

    def test_full_activation_from_the_member_creates_an_onboarding_volunteer(self):
        from verenigingen.verenigingen.doctype.volunteer.volunteer import create_volunteer_from_member

        email = f"fullact.{frappe.generate_hash(length=8)}@test.invalid"
        member = self.create_test_member(first_name="Full", last_name="Act", email=email, status="Active")

        result = create_volunteer_from_member(member.name, create_user_account=1)

        self.assertTrue(result.get("success"), result)
        self.assertEqual(frappe.db.get_value("Volunteer", result["volunteer_name"], "status"), "Onboarding")
        light = create_volunteer_from_member(
            self.create_test_member(first_name="Lite", last_name="Vol", email="lite." + email, status="Active").name
        )
        self.assertEqual(frappe.db.get_value("Volunteer", light["volunteer_name"], "status"), "New", "control")

    def test_an_activation_request_for_a_quit_member_creates_no_volunteer_and_still_assigns_roles(self):
        """F1: a member who may not hold volunteer access gets no Volunteer record or profile, and the
        rest of the role assignment (the requested role) still runs."""
        from verenigingen.services.member.account.account_creation_manager import AccountCreationManager

        email = f"quitvol.{frappe.generate_hash(length=8)}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        member = self.create_test_member(first_name="Quit", last_name="Vol", email=email, status="Active")
        member.db_set("user", user.name, update_modified=False)
        member.db_set("status", "Quit", update_modified=False)  # labelled shortcut: the terminated state
        request = frappe.get_doc(
            {
                "doctype": "Account Creation Request",
                "request_type": "Member",
                "source_record": member.name,
                "email": email,
                "full_name": "Quit Volunteer",
                "status": "Queued",
                "role_profile": "Verenigingen Volunteer",
                "business_justification": "F1 test",
            }
        )
        request.append("requested_roles", {"role": "Verenigingen Auditor"})
        request.insert()
        self.track_doc("Account Creation Request", request.name)
        manager = AccountCreationManager(request.name)
        manager.load_request()
        manager.created_user = user.name
        self.expectErrorLog()

        manager.assign_roles_and_profile()
        # Checked before the Phase 3 sync: that sync re-derives roles from profiles (#1293).
        self.assertTrue(frappe.db.exists("Has Role", {"parent": user.name, "role": "Verenigingen Auditor"}))

        sync_user_role_profile(user.name)

        self.assertFalse(frappe.db.exists("Volunteer", {"member": member.name}), "no volunteer created")
        self.assertNotIn("Verenigingen Volunteer", get_user_role_profiles(user.name))
