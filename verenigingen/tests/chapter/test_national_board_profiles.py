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
