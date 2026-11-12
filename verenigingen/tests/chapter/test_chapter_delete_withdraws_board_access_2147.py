"""#2147: deleting a Chapter must withdraw its seat holders' board role and role profile.

Frappe deletes a parent's child rows without running the child controller, so neither
Chapter Board Member's own hooks (#1922/#1953, standalone rows only) nor ``Chapter.on_update``
run. The seats vanished and the holder kept ``Verenigingen Chapter Board Member`` plus the
board role profile.

Real flows: seats are added through a Chapter save, then a real ``frappe.delete_doc("Chapter")``.
Probe shortcut (same as the #1922/#1953 suites): ``Member.user`` is set with ``db_set``, which is
what account creation writes.
"""

import frappe

from verenigingen.services.member.account.user_role_profile_calculator import (
    PROFILE_BOARD_MEMBER,
    get_user_role_profiles,
)
from verenigingen.tests.utils.base import VereningingenTestCase

BOARD_ROLE = "Verenigingen Chapter Board Member"


class TestChapterDeleteWithdrawsBoardAccess2147(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self._chapter_2147()
        self.chapter_role = self._chapter_role_2147("Secretary")

    def tearDown(self):
        for user in [d["name"] for d in self._test_docs if d["doctype"] == "User"]:
            for employee in frappe.get_all("Employee", filters={"user_id": user}, pluck="name"):
                self.track_doc("Employee", employee)  # a seat's profile carries Employee (#1694)
        super().tearDown()

    def _chapter_2147(self):
        return self.create_test_chapter(
            chapter_name=f"Del2147 {frappe.generate_hash(length=6)}", postal_codes="3000-3999", published=1
        )

    def _chapter_role_2147(self, label):
        name = f"{label} {frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {"doctype": "Chapter Role", "role_name": name, "permissions_level": "Basic", "is_active": 1}
        ).insert()
        self.track_doc("Chapter Role", name)
        return name

    def _person_2147(self, label):
        email = f"del2147.{label.lower()}.{frappe.generate_hash(length=8)}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        member = self.create_test_member(first_name=label, last_name="Del", email=email, status="Active")
        member.db_set("user", user.name, update_modified=False)
        volunteer = self.create_test_volunteer(member=member.name)
        return frappe._dict(user=user.name, volunteer=volunteer.name, email=email, member=member.name)

    def _seat_2147(self, person, chapter=None):
        chapter = frappe.get_doc("Chapter", (chapter or self.chapter).name)
        self.add_board_member_to_chapter(chapter, person.volunteer, self.chapter_role, email=person.email)

    def _roles_2147(self, user):
        return set(frappe.get_all("Has Role", filters={"parent": user, "parenttype": "User"}, pluck="role"))

    def _assert_seated_2147(self, user):
        self.assertIn(BOARD_ROLE, self._roles_2147(user), "control: the seat gives the role")
        self.assertIn(PROFILE_BOARD_MEMBER, get_user_role_profiles(user), "control: and the profile")

    def _assert_withdrawn_2147(self, user):
        self.assertNotIn(BOARD_ROLE, self._roles_2147(user), "board role still on the user")
        self.assertNotIn(PROFILE_BOARD_MEMBER, get_user_role_profiles(user), "board profile still on user")

    def test_deleting_the_chapter_withdraws_every_seat_holders_role_and_profile(self):
        first, second = self._person_2147("One"), self._person_2147("Two")
        self._seat_2147(first)
        self._seat_2147(second)
        self._assert_seated_2147(first.user)
        self._assert_seated_2147(second.user)

        frappe.delete_doc("Chapter", self.chapter.name, force=1)

        self.assertFalse(frappe.db.exists("Chapter", self.chapter.name), "control: really deleted")
        self._assert_withdrawn_2147(first.user)
        self._assert_withdrawn_2147(second.user)

    def test_a_holder_of_a_second_chapters_seat_keeps_the_access(self):
        other_chapter = self._chapter_2147()
        keeper, leaver = self._person_2147("Keep"), self._person_2147("Leave")
        self._seat_2147(keeper)
        self._seat_2147(keeper, other_chapter)
        self._seat_2147(leaver)

        frappe.delete_doc("Chapter", self.chapter.name, force=1)

        self._assert_seated_2147(keeper.user)
        self._assert_withdrawn_2147(leaver.user)

    def test_an_inactive_seat_holder_and_an_unrelated_seat_are_unaffected(self):
        """Control with a real row for the wrong behaviour to find: a holder of ANOTHER
        chapter's seat who is not on the deleted chapter must keep the access."""
        other_chapter = self._chapter_2147()
        bystander = self._person_2147("Bystander")
        self._seat_2147(bystander, other_chapter)

        frappe.delete_doc("Chapter", self.chapter.name, force=1)

        self._assert_seated_2147(bystander.user)

    def test_a_verenigingen_administrator_can_delete_and_the_withdrawal_sticks(self):
        """Least-privileged caller who may delete a Chapter (no blanket System Manager)."""
        admin_email = f"del2147.admin.{frappe.generate_hash(length=8)}@test.invalid"
        admin = self.create_test_user(admin_email, roles=["Verenigingen Administrator"])
        self.track_doc("User", admin.name)
        person = self._person_2147("ByAdmin")
        self._seat_2147(person)
        self._assert_seated_2147(person.user)

        self.addCleanup(frappe.set_user, frappe.session.user)
        frappe.set_user(admin.name)
        frappe.delete_doc("Chapter", self.chapter.name, force=1)  # force: skips only the Member link check

        self.assertFalse(frappe.db.exists("Chapter", self.chapter.name))
        self._assert_withdrawn_2147(person.user)

    def test_a_chapter_whose_seat_holder_volunteer_was_deleted_first_still_deletes(self):
        """The order test_chapter.test_board_manager_functionality uses: the Volunteer goes first,
        then the Chapter. The withdrawal must not crash the delete on the missing Volunteer."""
        person = self._person_2147("Gone")
        self._seat_2147(person)

        frappe.delete_doc("Volunteer", person.volunteer, force=1)
        frappe.delete_doc("Chapter", self.chapter.name, force=1)

        self.assertFalse(frappe.db.exists("Chapter", self.chapter.name))
