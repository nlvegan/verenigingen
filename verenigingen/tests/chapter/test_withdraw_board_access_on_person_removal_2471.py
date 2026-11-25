"""#2471: deleting a seated Volunteer or Member, or disabling the User, ends the seat and
withdraws the board role (maintainer ruling 2026-11-25, option a).

Real flows: seats are added through a Chapter save, then a real ``frappe.delete_doc`` /
User save with ``enabled=0``. Probe shortcut: ``Member.user`` is set with ``db_set`` (what
account creation writes, same as the #2147 suite). The Member-delete test deletes a Member
that has no dues schedule, i.e. the plain delete branch; the #1306 anonymise branch is
covered by ``test_anonymised_member_...`` below (the Member row survives there).
"""

from unittest import mock

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

    def _system_manager_only_2471(self):
        """A user who can delete a Member/Volunteer (System Manager) but has no Chapter write."""
        email = f"rm2471.sm.{frappe.generate_hash(length=8)}@test.invalid"
        admin = self.create_test_user(email, roles=["System Manager"])
        self.track_doc("User", admin.name)
        self.assertFalse(
            frappe.has_permission("Chapter", "write", user=admin.name), "precondition: no Chapter write"
        )
        return admin.name

    def test_a_system_manager_without_chapter_write_can_delete_a_seated_volunteer(self):
        leaver, bystander = self._two_holders_2471()
        caller = frappe.session.user
        self.addCleanup(frappe.set_user, caller)
        frappe.set_user(self._system_manager_only_2471())

        frappe.delete_doc("Volunteer", leaver.volunteer, force=1)

        frappe.set_user(caller)
        self.assertFalse(frappe.db.exists("Volunteer", leaver.volunteer), "control: really deleted")
        self._assert_unseated_2471(leaver)
        self._assert_seated_2471(bystander)

    def test_a_system_manager_without_chapter_write_can_delete_a_seated_member(self):
        leaver, bystander = self._two_holders_2471()
        caller = frappe.session.user
        self.addCleanup(frappe.set_user, caller)
        frappe.set_user(self._system_manager_only_2471())

        frappe.delete_doc("Member", leaver.member, force=1)

        frappe.set_user(caller)
        self.assertFalse(frappe.db.exists("Member", leaver.member), "control: really deleted")
        self._assert_unseated_2471(leaver)
        self._assert_seated_2471(bystander)

    def test_resaving_an_already_disabled_user_does_not_end_a_new_seat(self):
        """Only the 1 -> 0 transition ends seats. A disabled user re-seated afterwards keeps the
        seat across a further save of the (still disabled) account."""
        person = self._person_2471("Reseat")
        self._seat_2471(person)
        self._disable_2471(person.user)
        self._assert_unseated_2471(person)
        other_chapter = self._chapter_2471()
        self._seat_2471(person, other_chapter)
        self.assertTrue(
            any(r.is_active for r in self._seat_rows_2471(person.volunteer, other_chapter)),
            "control: re-seated",
        )

        user_doc = frappe.get_doc("User", person.user)
        user_doc.last_name = "Resaved"
        user_doc.save()

        self.assertEqual(frappe.db.get_value("User", person.user, "enabled"), 0, "control: still disabled")
        self.assertTrue(
            any(r.is_active for r in self._seat_rows_2471(person.volunteer, other_chapter)),
            "an already-disabled user's re-seat was ended by an unrelated save",
        )

    def test_disabling_an_unseated_users_account_keeps_its_direct_roles(self):
        """The role sync is a REPLACE: running it for a user with no seat and no board role would
        strip direct roles. Disabling such a user must not touch the role set."""
        person = self._person_2471("Unseated")
        user_doc = frappe.get_doc("User", person.user)
        user_doc.append("roles", {"role": "Report Manager"})
        user_doc.save()
        before = self._roles_2471(person.user)
        self.assertIn("Report Manager", before, "control: the direct role is held")
        self.assertNotIn(BOARD_ROLE, before, "control: no board role")
        self.assertFalse(self._seat_rows_2471(person.volunteer), "control: no seat")

        self._disable_2471(person.user)

        self.assertEqual(frappe.db.get_value("User", person.user, "enabled"), 0, "control: disabled")
        self.assertEqual(self._roles_2471(person.user), before, "disable rewrote an unseated user's roles")

    def test_a_failed_role_withdrawal_on_disable_is_logged_and_the_disable_succeeds(self):
        self.expectErrorLog("Board seats not ended for disabled user")
        person = self._person_2471("SoftFail")
        self._seat_2471(person)
        before = frappe.utils.now_datetime()

        # Mock justified: forces the role-withdrawal step to fail, which no real fixture can do.
        with mock.patch(
            "verenigingen.services.member.account.user_role_profile_calculator.sync_user_role_profile",
            side_effect=RuntimeError("boom 2471"),
        ):
            self._disable_2471(person.user)

        self.assertEqual(frappe.db.get_value("User", person.user, "enabled"), 0, "the disable must succeed")
        logs = frappe.get_all(
            "Error Log",
            filters={"method": "Board seats not ended for disabled user", "creation": [">=", before]},
            fields=["error"],
        )
        self.assertTrue(logs, "no Error Log row for the failed withdrawal")
        self.assertIn("boom 2471", logs[0].error)
