"""#2745 / #2773: a Chapter is deletable, forced or not, ONLY when nothing references it.

``force=1`` skips Frappe's link checks and used to leave dangling references: the seated
volunteer's Volunteer Assignment history (a Dynamic Link, so the Volunteer could no longer be
saved) and the Member's Chapter Membership History row (a Link, so the Member could not be
saved either). Maintainer ruling 2026-11-17 (option 4): refuse, and complete/unlink nothing.

Real flows: seats are added through a Chapter save, then a real ``frappe.delete_doc``.
Probe shortcuts: the Volunteer-only reference is a Committee entry written with
``AssignmentHistoryManager.add_assignment_history`` (no product flow writes a non-board entry that
names a Chapter); the Member-only reference is a Chapter Membership History row appended with
``Member.append(...).save()`` (the real join flow also writes a Chapter Member row; the row
alone is what the Member-side check needs).

Helper names carry the issue number: the duplicate-helper baseline keys on the bare name.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.assignment_history_manager import AssignmentHistoryManager


class TestChapterDeleteRefusedWhileReferenced2745(VereningingenTestCase):
    def _chapter_2745(self):
        return self.create_test_chapter(
            chapter_name=f"Ch2745 {frappe.generate_hash(length=6)}", postal_codes="5000-5999", published=1
        )

    def _role_2745(self):
        name = f"Role2745 {frappe.generate_hash(length=8)}"
        frappe.get_doc(
            {"doctype": "Chapter Role", "role_name": name, "permissions_level": "Basic", "is_active": 1}
        ).insert()
        self.track_doc("Chapter Role", name)
        return name

    def _member_2745(self):
        return self.create_test_member(
            first_name="Del", last_name=f"V{frappe.generate_hash(length=6)}", birth_date="1985-01-01"
        )

    def _seated_2745(self):
        """A Chapter with a volunteer seated through a real Chapter save."""
        chapter, role = self._chapter_2745(), self._role_2745()
        member = self._member_2745()
        volunteer = self.create_test_volunteer(member_name=member.name)
        self.add_board_member_to_chapter(frappe.get_doc("Chapter", chapter.name), volunteer, role)
        return chapter, member, volunteer

    def _history_rows_2745(self, volunteer, chapter):
        return frappe.get_all(
            "Volunteer Assignment",
            filters={"parent": volunteer.name, "reference_doctype": "Chapter", "reference_name": chapter.name},
            fields=["name", "status", "end_date", "reference_name"],
        )

    def _membership_rows_2745(self, member, chapter):
        return frappe.get_all(
            "Chapter Membership History",
            filters={"parent": member.name, "chapter_name": chapter.name},
            fields=["name", "status", "end_date"],
        )

    def _assert_refused_2745(self, chapter, force):
        with self.assertRaises(frappe.LinkExistsError):
            frappe.delete_doc("Chapter", chapter.name, force=force)
        self.assertTrue(frappe.db.exists("Chapter", chapter.name), "the Chapter must survive")

    def test_forced_delete_of_a_chapter_with_a_seated_volunteer_is_refused_and_nothing_changes(self):
        chapter, member, volunteer = self._seated_2745()
        history_before = self._history_rows_2745(volunteer, chapter)
        membership_before = self._membership_rows_2745(member, chapter)
        self.assertEqual(len(history_before), 1, "control: the seat wrote a Volunteer history row")
        self.assertEqual(history_before[0].status, "Active", "control: seated")
        self.assertTrue(membership_before, "control: the seat wrote a Member history row")

        self._assert_refused_2745(chapter, force=1)

        self.assertEqual(self._history_rows_2745(volunteer, chapter), history_before)
        self.assertEqual(self._membership_rows_2745(member, chapter), membership_before)
        self.assertTrue(frappe.db.exists("Chapter Board Member", {"parent": chapter.name}), "seat intact")
        frappe.get_doc("Volunteer", volunteer.name).save()
        frappe.get_doc("Member", member.name).save()

    def test_unforced_delete_of_a_referenced_chapter_is_still_refused(self):
        chapter, _member, _volunteer = self._seated_2745()
        self._assert_refused_2745(chapter, force=0)

    def test_a_chapter_referenced_only_by_a_members_history_row_is_refused_under_force(self):
        """#2773: no Volunteer, so only the Member's Link reaches the Chapter."""
        chapter, member = self._chapter_2745(), self._member_2745()
        member_doc = frappe.get_doc("Member", member.name)
        member_doc.append(
            "chapter_membership_history",
            {"chapter_name": chapter.name, "assignment_type": "Member", "start_date": "2020-01-01", "status": "Active"},
        )
        member_doc.save()
        self.assertTrue(self._membership_rows_2745(member, chapter), "control: only the Member references it")
        self.assertFalse(
            frappe.get_all("Volunteer Assignment", filters={"reference_name": chapter.name}),
            "control: no Volunteer history",
        )

        self._assert_refused_2745(chapter, force=1)

        self.assertTrue(self._membership_rows_2745(member, chapter))
        frappe.get_doc("Member", member.name).save()

    def test_a_chapter_referenced_only_by_a_volunteers_dynamic_link_is_refused_under_force(self):
        """No Member row names the Chapter, so only the Volunteer Assignment Dynamic Link reaches it."""
        chapter, volunteer = self._chapter_2745(), self.create_test_volunteer(member_name=self._member_2745().name)
        AssignmentHistoryManager.add_assignment_history(
            volunteer.name, "Committee", "Chapter", chapter.name, "Helper", today()
        )
        self.assertEqual(len(self._history_rows_2745(volunteer, chapter)), 1, "control: synthetic row")
        self.assertFalse(
            frappe.get_all("Chapter Membership History", filters={"chapter_name": chapter.name}),
            "control: no Member history, so Frappe's static link check finds nothing",
        )

        self._assert_refused_2745(chapter, force=1)

        self.assertEqual(len(self._history_rows_2745(volunteer, chapter)), 1)
        frappe.get_doc("Volunteer", volunteer.name).save()

    def test_an_unreferenced_chapter_is_deletable_with_and_without_force(self):
        for force in (0, 1):
            chapter = self._chapter_2745()
            self.assertFalse(frappe.get_all("Volunteer Assignment", filters={"reference_name": chapter.name}))
            frappe.delete_doc("Chapter", chapter.name, force=force)
            self.assertFalse(frappe.db.exists("Chapter", chapter.name), f"force={force}")

    def test_merge_rename_repoints_the_references_and_still_deletes_the_old_chapter(self):
        old, member, volunteer = self._seated_2745()
        target = self._chapter_2745()

        frappe.rename_doc("Chapter", old.name, target.name, merge=True, force=True)

        self.assertFalse(frappe.db.exists("Chapter", old.name))
        self.assertTrue(frappe.db.exists("Chapter", target.name))
        self.assertTrue(self._history_rows_2745(volunteer, target), "history repointed to the target")
        self.assertTrue(self._membership_rows_2745(member, target), "member history repointed")
        frappe.get_doc("Volunteer", volunteer.name).save()
        frappe.get_doc("Member", member.name).save()
