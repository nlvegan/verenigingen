"""#2471: deleting a seated Volunteer or Member, or disabling the User, ends the seat and
withdraws the board role (maintainer ruling 2026-11-25, option a).

Real flows: seats are added through a Chapter save, then a real ``frappe.delete_doc`` /
User save with ``enabled=0``. Probe shortcut: ``Member.user`` is set with ``db_set`` (what
account creation writes, same as the #2147 suite). The Member-delete test deletes a Member
that has no dues schedule, i.e. the plain delete branch; the #1306 anonymise branch is
covered by ``test_anonymised_member_...`` below (the Member row survives there).
"""

import frappe

from verenigingen.services.member.account.user_role_profile_calculator import (
    PROFILE_BOARD_MEMBER,
    get_user_role_profiles,
)
from verenigingen.services.member.lifecycle.member_cleanup_service import MemberAnonymizedInsteadOfDeleted
from verenigingen.tests.support.dues_schedule_invoice_fixtures import (
    make_referenceable_dues_schedule,
    make_submitted_invoice_for_schedule,
)
from verenigingen.tests.utils.base import VereningingenTestCase

BOARD_ROLE = "Verenigingen Chapter Board Member"


class TestWithdrawBoardAccessOnPersonRemoval2471(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self._chapter_2471()
        self.chapter_role = self._chapter_role_2471("Secretary")

    def tearDown(self):
        for user in [d["name"] for d in self._test_docs if d["doctype"] == "User"]:
            for employee in frappe.get_all("Employee", filters={"user_id": user}, pluck="name"):
                self.track_doc("Employee", employee)  # a seat's profile carries Employee (#1694)
        super().tearDown()

    def _chapter_2471(self):
        return self.create_test_chapter(
            chapter_name=f"Rm2471 {frappe.generate_hash(length=6)}", postal_codes="3000-3999", published=1
        )

    def _chapter_role_2471(self, label):
        name = f"{label} {frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {"doctype": "Chapter Role", "role_name": name, "permissions_level": "Basic", "is_active": 1}
        ).insert()
        self.track_doc("Chapter Role", name)
        return name

    def _person_2471(self, label):
        email = f"rm2471.{label.lower()}.{frappe.generate_hash(length=8)}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        member = self.create_test_member(first_name=label, last_name="Rm", email=email, status="Active")
        member.db_set("user", user.name, update_modified=False)
        volunteer = self.create_test_volunteer(member=member.name)
        return frappe._dict(user=user.name, volunteer=volunteer.name, email=email, member=member.name)

    def _seat_2471(self, person, chapter=None):
        chapter = frappe.get_doc("Chapter", (chapter or self.chapter).name)
        self.add_board_member_to_chapter(chapter, person.volunteer, self.chapter_role, email=person.email)

    def _roles_2471(self, user):
        return set(frappe.get_all("Has Role", filters={"parent": user, "parenttype": "User"}, pluck="role"))

    def _seat_rows_2471(self, volunteer, chapter=None):
        return frappe.get_all(
            "Chapter Board Member",
            filters={"parent": (chapter or self.chapter).name, "volunteer": volunteer},
            fields=["name", "is_active", "to_date"],
        )

    def _assert_seated_2471(self, person, chapter=None):
        self.assertIn(BOARD_ROLE, self._roles_2471(person.user), "control: the seat gives the role")
        self.assertIn(PROFILE_BOARD_MEMBER, get_user_role_profiles(person.user), "control: and the profile")
        rows = self._seat_rows_2471(person.volunteer, chapter)
        self.assertTrue(rows and all(r.is_active for r in rows), "control: the seat row is live")

    def _assert_unseated_2471(self, person):
        self.assertNotIn(BOARD_ROLE, self._roles_2471(person.user), "board role still on the user")
        self.assertNotIn(PROFILE_BOARD_MEMBER, get_user_role_profiles(person.user), "board profile remains")
        rows = self._seat_rows_2471(person.volunteer)
        self.assertTrue(rows, "control: the seat row still exists, ended not removed")
        self.assertFalse(any(r.is_active for r in rows), "seat still active")
        self.assertTrue(all(r.to_date for r in rows), "ended seat has no end date")

    def _disable_2471(self, user):
        user_doc = frappe.get_doc("User", user)
        user_doc.enabled = 0
        user_doc.save()

    def _two_holders_2471(self):
        leaver, bystander = self._person_2471("Leave"), self._person_2471("Stay")
        self._seat_2471(leaver)
        self._seat_2471(bystander)
        self._assert_seated_2471(leaver)
        self._assert_seated_2471(bystander)
        return leaver, bystander

    def test_deleting_a_seated_volunteer_ends_the_seat_and_withdraws_the_role(self):
        leaver, bystander = self._two_holders_2471()

        frappe.delete_doc("Volunteer", leaver.volunteer, force=1)

        self.assertFalse(frappe.db.exists("Volunteer", leaver.volunteer), "control: really deleted")
        self._assert_unseated_2471(leaver)
        self._assert_seated_2471(bystander)

    def test_deleting_a_seated_member_ends_the_seat_and_withdraws_the_role(self):
        leaver, bystander = self._two_holders_2471()

        frappe.delete_doc("Member", leaver.member, force=1)

        self.assertFalse(frappe.db.exists("Member", leaver.member), "control: really deleted")
        self._assert_unseated_2471(leaver)
        self._assert_seated_2471(bystander)

    def test_disabling_the_user_ends_the_seat_and_withdraws_the_role(self):
        leaver, bystander = self._two_holders_2471()

        self._disable_2471(leaver.user)

        self.assertEqual(frappe.db.get_value("User", leaver.user, "enabled"), 0, "control: disabled")
        self._assert_unseated_2471(leaver)
        self._assert_seated_2471(bystander)

    def test_every_seat_in_every_chapter_ends_so_no_second_seat_keeps_the_role(self):
        """Member.user is unique and a Member has one Volunteer, so no OTHER person can keep a
        user's role alive; the only second seat is the same person's, in another chapter. The
        brief's "keeps the role through another active seat" is therefore the Chapter-delete case
        (#2147 suite). Here: a second chapter's seat must not be missed and keep the role."""
        other_chapter = self._chapter_2471()
        leaver = self._person_2471("TwoSeats")
        self._seat_2471(leaver)
        self._seat_2471(leaver, other_chapter)
        self._assert_seated_2471(leaver, other_chapter)

        frappe.delete_doc("Volunteer", leaver.volunteer, force=1)

        self.assertFalse(any(r.is_active for r in self._seat_rows_2471(leaver.volunteer)))
        self.assertFalse(any(r.is_active for r in self._seat_rows_2471(leaver.volunteer, other_chapter)))
        self.assertNotIn(BOARD_ROLE, self._roles_2471(leaver.user), "second chapter's seat kept the role")

    def test_a_member_anonymised_instead_of_deleted_also_withdraws(self):
        """#1306: a Member whose dues schedule is invoice-referenced is anonymised, not deleted.
        The Member row survives, so the seat and role must go on this path too. The schedule and
        invoice are real fixtures (same helpers as test_member_cleanup_service)."""
        self.expectErrorLog("Dues Schedule Not Deleted", "Member Deletion Audit Trail")
        leaver, bystander = self._two_holders_2471()
        member = frappe.get_doc("Member", leaver.member)
        schedule = make_referenceable_dues_schedule(self, member)
        make_submitted_invoice_for_schedule(self, schedule.name)

        with self.assertRaises(MemberAnonymizedInsteadOfDeleted):
            frappe.delete_doc("Member", leaver.member, force=1)

        self.assertTrue(frappe.db.exists("Member", leaver.member), "control: anonymised, not deleted")
        self._assert_unseated_2471(leaver)
        self._assert_seated_2471(bystander)
