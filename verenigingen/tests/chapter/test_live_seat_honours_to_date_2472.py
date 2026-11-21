"""One definition of a "live" board seat: is_active=1 AND not past its to_date (#2472).

``withdraw_board_member_role_if_unseated`` already treated a seat whose ``to_date`` is
past as vacated, while ``get_board_member_profiles`` / ``is_active_board_member`` counted
every ``is_active=1`` row. The state is reachable without any shortcut: nothing flips
``is_active`` when a fixed-term seat's ``to_date`` passes (no scheduled job), and a Desk
edit of the board table can save ``is_active=1`` beside a past ``to_date`` (the validator
only warns). The lapsed rows below are written by saving the Chapter, as the Desk does.
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.services.member.account.user_role_profile_calculator import (
    get_board_member_profiles,
    get_user_role_profiles,
    is_active_board_member,
)
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.constants import Roles

BOARD_PROFILE = "Verenigingen Chapter Board Member"


class TestLiveSeatHonoursToDate2472(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.chapter_a = self._chapter_2472("A")
        self.chapter_b = self._chapter_2472("B")
        email = f"liveseat.{frappe.generate_hash(length=6)}@test.invalid"
        self.user = self.create_test_user(email)
        self.track_doc("User", self.user.name)
        self.member = self.create_test_member(
            first_name="Live", last_name="Seat", email=email, status="Active"
        )
        self.member.db_set("user", self.user.name, update_modified=False)
        self.member.reload()
        self.volunteer = self.create_test_volunteer(member=self.member.name)
        self.role_name = f"Role{frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": self.role_name,
                "permissions_level": "Basic",
                "is_chair": 0,
                "is_active": 1,
            }
        ).insert()
        self.track_doc("Chapter Role", self.role_name)

    def _chapter_2472(self, tag):
        return self.create_test_chapter(
            chapter_name=f"LiveSeat {tag} {frappe.generate_hash(length=6)}",
            postal_codes="1000-9999",
            published=1,
        )

    def _seat_2472(self, chapter, to_date=None):
        """Seat the volunteer by saving the Chapter, optionally with an end date."""
        chapter = frappe.get_doc("Chapter", chapter.name)
        extra = {"from_date": add_days(today(), -30)}
        if to_date:
            extra["to_date"] = to_date
        self.add_board_member_to_chapter(
            chapter, self.volunteer, self.role_name, email=self.user.name, **extra
        )

    def _vacate_2472(self, chapter):
        chapter = frappe.get_doc("Chapter", chapter.name)
        chapter.board_members = [b for b in chapter.board_members if b.volunteer != self.volunteer.name]
        chapter.save()

    def _roles_2472(self):
        frappe.clear_cache(user=self.user.name)
        return frappe.get_roles(self.user.name)

    def test_lapsed_seat_is_not_a_board_seat_for_the_profile_calculator(self):
        self._seat_2472(self.chapter_a, to_date=add_days(today(), -1))
        row = frappe.db.get_value(
            "Chapter Board Member",
            {"parent": self.chapter_a.name, "volunteer": self.volunteer.name},
            ["is_active", "to_date"],
            as_dict=True,
        )
        self.assertEqual(row.is_active, 1, "fixture: the Desk save left the seat active")
        self.assertLess(str(row.to_date), today(), "fixture: the seat's end date is past")

        self.assertFalse(is_active_board_member(self.user.name, self.member.name))
        self.assertEqual(get_board_member_profiles(self.user.name, self.member.name), [])

    def test_open_ended_future_and_ends_today_seats_are_live(self):
        """Controls: each of the three live shapes is a real row the wrong fix would drop."""
        for tag, to_date in (("open", None), ("future", add_days(today(), 5)), ("today", today())):
            chapter = self._chapter_2472(tag)
            self._seat_2472(chapter, to_date=to_date)
            self.assertTrue(
                is_active_board_member(self.user.name, self.member.name), f"{tag} seat must be live"
            )
            self.assertTrue(get_board_member_profiles(self.user.name, self.member.name), tag)
            self._vacate_2472(chapter)

    def test_deleting_the_live_seat_withdraws_access_when_the_other_seat_lapsed(self):
        """The issue's case: seat B lapsed by date; deleting seat A must drop the access."""
        self._seat_2472(self.chapter_a)
        self._seat_2472(self.chapter_b, to_date=add_days(today(), -1))
        self.assertIn(BOARD_PROFILE, get_user_role_profiles(self.user.name), "fixture: access granted")
        self.assertIn(Roles.CHAPTER_BOARD_MEMBER, self._roles_2472(), "fixture: role granted")

        self._vacate_2472(self.chapter_a)

        self.assertNotIn(Roles.CHAPTER_BOARD_MEMBER, self._roles_2472(), "role survived (Frappe role)")
        self.assertNotIn(BOARD_PROFILE, get_user_role_profiles(self.user.name), "role profile survived")

    def test_a_live_second_seat_still_keeps_access(self):
        """Control: with a genuinely live second seat the access stays."""
        self._seat_2472(self.chapter_a)
        self._seat_2472(self.chapter_b, to_date=add_days(today(), 5))
        self._vacate_2472(self.chapter_a)
        self.assertIn(Roles.CHAPTER_BOARD_MEMBER, self._roles_2472())
        self.assertIn(BOARD_PROFILE, get_user_role_profiles(self.user.name))

    def _has_board_role_row_2472(self):
        return bool(
            frappe.db.exists("Has Role", {"parent": self.user.name, "role": Roles.CHAPTER_BOARD_MEMBER})
        )

    def test_withdraw_if_unseated_keeps_role_with_one_live_and_one_lapsed_seat(self):
        """Direct call, so the profile sync cannot mask the helper's use in the withdrawal."""
        from verenigingen.verenigingen.doctype.chapter_board_member.chapter_board_member import (
            withdraw_board_member_role_if_unseated,
        )

        self._seat_2472(self.chapter_a)
        self._seat_2472(self.chapter_b, to_date=add_days(today(), -1))
        self.assertTrue(self._has_board_role_row_2472(), "fixture: role granted")

        withdraw_board_member_role_if_unseated(self.volunteer.name)

        self.assertTrue(self._has_board_role_row_2472(), "a live seat exists; role must stay")

    def test_withdraw_if_unseated_drops_role_when_only_a_lapsed_seat_remains(self):
        from verenigingen.verenigingen.doctype.chapter_board_member.chapter_board_member import (
            withdraw_board_member_role_if_unseated,
        )

        self._seat_2472(self.chapter_b, to_date=add_days(today(), -1))
        # Probe shortcut: the profile sync (rightly) never granted the role for a lapsed-only seat,
        # so insert the Has Role row directly to stand in for a grant made while the seat was live.
        # The direct call, not a sync, is then the only thing that can remove it.
        if not self._has_board_role_row_2472():
            frappe.get_doc(
                {
                    "doctype": "Has Role",
                    "parent": self.user.name,
                    "parenttype": "User",
                    "parentfield": "roles",
                    "role": Roles.CHAPTER_BOARD_MEMBER,
                }
            ).db_insert()
        self.assertTrue(self._has_board_role_row_2472(), "fixture: role present before the call")

        withdraw_board_member_role_if_unseated(self.volunteer.name)

        self.assertFalse(self._has_board_role_row_2472(), "only a lapsed seat remains; role must go")
