"""Vacating a chapter board seat must withdraw the access that seat conferred.

Two things follow from a board seat: the Frappe role
``Verenigingen Chapter Board Member`` (granted by
``ChapterBoardMember.assign_board_member_role``) and the board-derived Role Profile
(applied by ``sync_user_role_profile`` via the profile calculator). Deleting the
``Chapter Board Member`` row is only bookkeeping; the access is what matters, so
every test here asserts both, and asserts them *before* the removal as well so a
vacuous pass is impossible.

The removal-side recalculation used to run inside ``Chapter.validate()``, i.e.
before the child rows were written. ``get_board_member_profiles()`` reads
``Chapter Board Member`` from the database, so it still saw the seat as active and
``sync_user_role_profile()`` reported ``changed: False`` — the profile survived
every removal path (desk, API, bulk). The additions path had already been deferred
to ``on_update`` for exactly this reason; these tests pin the deletion side to the
same guarantee. See issue #211.

Role profiles are asserted against the whole ``get_user_role_profiles()`` list
(``assertIn`` / ``assertNotIn``): it is an unordered ``frappe.get_all``, so
indexing into it would be a coin flip.
"""

import frappe
from frappe.utils import today

from verenigingen.services.member.account.user_role_profile_calculator import (
    get_user_role_profiles,
)
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.constants import Roles

BOARD_PROFILE = "Verenigingen Chapter Board Member"


class TestBoardRoleWithdrawal(VereningingenTestCase):
    """Board access must be withdrawn when the seat is vacated, on every path."""

    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter(
            chapter_name=f"Withdrawal {frappe.generate_hash(length=6)}",
            postal_codes="1000-9999",
            published=1,
        )

    # ------------------------------------------------------------------ helpers

    def _make_role(self):
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
        return role_name

    def _make_volunteer_with_user(self, first="Board"):
        """A volunteer whose Member carries a real User — without one there is no
        access to grant or withdraw and every assertion below would be vacuous."""
        email = f"withdraw.{first.lower()}.{frappe.generate_hash(length=6)}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)

        member = self.create_test_member(
            first_name=first,
            last_name="Withdrawal",
            email=email,
            status="Active",
        )
        member.db_set("user", user.name, update_modified=False)
        member.reload()
        volunteer = self.create_test_volunteer(member=member.name)
        return user, member, volunteer

    def _roles_of(self, user_name):
        # frappe.get_roles() memoises per user in frappe.local; the Chapter save
        # rewrote User.roles underneath it.
        frappe.clear_cache(user=user_name)
        return frappe.get_roles(user_name)

    def _has_role_row(self, user_name):
        """The stored grant, as opposed to frappe.get_roles()'s derived view of it."""
        return bool(frappe.db.exists("Has Role", {"parent": user_name, "role": Roles.CHAPTER_BOARD_MEMBER}))

    def _assert_has_board_access(self, user_name, msg):
        self.assertIn(BOARD_PROFILE, get_user_role_profiles(user_name), f"{msg} (role profile)")
        self.assertIn(Roles.CHAPTER_BOARD_MEMBER, self._roles_of(user_name), f"{msg} (Frappe role)")
        self.assertTrue(self._has_role_row(user_name), f"{msg} (Has Role row)")

    def _assert_no_board_access(self, user_name, msg):
        # Frappe role first, then profile: they fail independently and knowing which
        # one survived is the whole diagnosis (see issue #211 item 2).
        self.assertNotIn(Roles.CHAPTER_BOARD_MEMBER, self._roles_of(user_name), f"{msg} (Frappe role)")
        self.assertFalse(self._has_role_row(user_name), f"{msg} (Has Role row)")
        self.assertNotIn(BOARD_PROFILE, get_user_role_profiles(user_name), f"{msg} (role profile)")

    def _seat(self, chapter, volunteer, role_name, email):
        chapter = frappe.get_doc("Chapter", chapter.name)
        self.add_board_member_to_chapter(chapter, volunteer, role_name, email=email)
        return chapter

    # ------------------------------------------------------------------- tests

    def test_deleting_the_only_board_row_withdraws_profile_and_role(self):
        """The desk path: drop the child row and save the Chapter."""
        user, _member, volunteer = self._make_volunteer_with_user(first="RowDelete")
        role_name = self._make_role()
        self._seat(self.chapter, volunteer, role_name, user.name)

        self._assert_has_board_access(
            user.name, "seating a board member must grant board access before the removal is tested"
        )

        chapter = frappe.get_doc("Chapter", self.chapter.name)
        chapter.board_members = [b for b in chapter.board_members if b.volunteer != volunteer.name]
        chapter.save()

        self._assert_no_board_access(user.name, "deleting the only board row left the board access in place")

    def test_deactivating_the_only_board_row_withdraws_profile_and_role(self):
        """The API path: BoardManager.remove_board_member sets is_active=0 + to_date."""
        user, _member, volunteer = self._make_volunteer_with_user(first="Deactivate")
        role_name = self._make_role()
        chapter = self._seat(self.chapter, volunteer, role_name, user.name)

        self._assert_has_board_access(
            user.name, "seating a board member must grant board access before the removal is tested"
        )

        result = chapter.board_manager.remove_board_member(volunteer.name, notify=False)
        self.assertTrue(result["success"], result)

        self._assert_no_board_access(
            user.name, "deactivating the only board row left the board access in place"
        )

    def test_bulk_remove_board_members_withdraws_profile_and_role(self):
        """The bulk path: BoardManager.bulk_remove_board_members drops the rows."""
        user, _member, volunteer = self._make_volunteer_with_user(first="BulkGone")
        role_name = self._make_role()
        chapter = self._seat(self.chapter, volunteer, role_name, user.name)

        self._assert_has_board_access(
            user.name, "seating a board member must grant board access before the removal is tested"
        )

        result = chapter.board_manager.bulk_remove_board_members(
            [
                {
                    "volunteer": volunteer.name,
                    "chapter_role": role_name,
                    "from_date": today(),
                    "end_date": today(),
                }
            ]
        )
        self.assertEqual(result.get("errors"), [], result)
        self.assertTrue(result.get("success"), result)

        self._assert_no_board_access(user.name, "bulk removal left the board access in place")

    def test_surviving_board_access_raises_instead_of_being_logged(self):
        """A withdrawal that did not withdraw must not be reported as a success.

        The state is built for real, not mocked: the seat is deleted straight out of
        the database so no hook recalculates anything, which is exactly what the user
        is left holding whenever the recalculation is skipped, refused or lost. The
        rest of this manager logs per-member failures and continues — right for a
        failed grant, wrong for a failed revocation, which leaves live permissions
        behind a UI that says the seat is gone.
        """
        from verenigingen.verenigingen.doctype.chapter.managers import BoardAccessWithdrawalError

        user, _member, volunteer = self._make_volunteer_with_user(first="Leaked")
        role_name = self._make_role()
        chapter = self._seat(self.chapter, volunteer, role_name, user.name)

        self._assert_has_board_access(user.name, "seating a board member must grant board access")

        # Vacate the seat behind every hook's back: profile and role stay attached.
        frappe.db.delete("Chapter Board Member", {"volunteer": volunteer.name})
        self.assertEqual(
            frappe.db.count("Chapter Board Member", {"volunteer": volunteer.name, "is_active": 1}), 0
        )

        with self.assertRaises(BoardAccessWithdrawalError) as caught:
            chapter.board_manager._assert_board_access_withdrawn(volunteer.name)

        self.assertIn(BOARD_PROFILE, str(caught.exception))

    def test_removal_keeps_access_when_another_chapter_seat_is_still_active(self):
        """Withdrawal is per-person, not per-seat: another live seat keeps the access."""
        user, _member, volunteer = self._make_volunteer_with_user(first="TwoSeats")
        role_name = self._make_role()
        other_chapter = self.create_test_chapter(
            chapter_name=f"Withdrawal Other {frappe.generate_hash(length=6)}",
            postal_codes="1000-9999",
            published=1,
        )

        self._seat(self.chapter, volunteer, role_name, user.name)
        self._seat(other_chapter, volunteer, role_name, user.name)

        self._assert_has_board_access(
            user.name, "seating two board rows must grant board access before the removal is tested"
        )

        chapter = frappe.get_doc("Chapter", self.chapter.name)
        chapter.board_members = [b for b in chapter.board_members if b.volunteer != volunteer.name]
        chapter.save()

        # Still seated on other_chapter's board — the access is still earned.
        self.assertEqual(
            frappe.db.count("Chapter Board Member", {"volunteer": volunteer.name, "is_active": 1}),
            1,
            "the second board seat should still be active",
        )
        self._assert_has_board_access(
            user.name, "vacating one seat withdrew access that a second active seat still justifies"
        )
