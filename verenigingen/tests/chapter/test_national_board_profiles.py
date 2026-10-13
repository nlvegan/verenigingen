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
        roles_before = set(frappe.get_roles(victim.user))
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
        self.assertTrue(roles_before <= set(frappe.get_roles(victim.user)))

    def test_a_resync_never_drops_a_manually_assigned_profile(self):
        user = self._hold_a_board_seat(self.national, "Secretary").user
        manual = ["Verenigingen Administrator", "Verenigingen Auditor"]
        self._assign_profiles_directly(user, manual + [NATIONAL_MEMBER])

        sync_user_role_profile(user)

        profiles = set(get_user_role_profiles(user))
        self.assertTrue(set(manual) <= profiles, profiles)
        self.assertIn(NATIONAL_MEMBER, profiles)

    def test_a_stale_derived_profile_is_still_withdrawn_next_to_manual_ones(self):
        """Control for the above: non-destructive must not mean never-removing."""
        seat = self._hold_a_board_seat(self.national, "Secretary")
        self._assign_profiles_directly(seat.user, ["HR", NATIONAL_MEMBER, NATIONAL_TREASURER])

        sync_user_role_profile(seat.user)

        profiles = set(get_user_role_profiles(seat.user))
        self.assertIn("HR", profiles)
        self.assertIn(NATIONAL_MEMBER, profiles)
        self.assertNotIn(NATIONAL_TREASURER, profiles, "a treasurer profile without a treasurer seat is stale")

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
        with self.assertRaisesRegex(frappe.PermissionError, "national board chapter"):
            self._settings_change_as(["Verenigingen Financial Manager"])
        self.assertEqual(
            frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter"), self.national.name
        )

    def test_a_verenigingen_administrator_can_repoint_the_national_chapter(self):
        self._settings_change_as(["Verenigingen Administrator"])
        self.assertEqual(
            frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter"), self.other.name
        )

    def test_a_system_manager_can_repoint_the_national_chapter(self):
        self._settings_change_as(["System Manager"])
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
