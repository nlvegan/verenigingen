"""#2745: deleting a Chapter must complete its seat holders' Volunteer Assignment history.

Frappe removes a Chapter's board rows without running their controllers, so the history entry
(a Dynamic Link to the Chapter) stayed Active, the volunteer stayed Active, and any later
Volunteer save raised LinkValidationError on the dangling link.

Real flows: seats are added through a Chapter save, then a real ``frappe.delete_doc("Chapter",
force=1)`` (force skips only the Member link check). Probe shortcut: the Committee entry is
written with ``AssignmentHistoryManager.add_assignment_history`` (no product flow writes a
non-board entry that names a Chapter, so this is a synthetic row).

Helper names carry the issue number: the duplicate-helper baseline keys on the bare name.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.assignment_history_manager import AssignmentHistoryManager


class TestChapterDeleteCompletesHistory2745(VereningingenTestCase):
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

    def _volunteer_2745(self):
        member = self.create_test_member(
            first_name="Del", last_name=f"V{frappe.generate_hash(length=6)}", birth_date="1985-01-01"
        )
        return self.create_test_volunteer(member_name=member.name)

    def _seat_2745(self, chapter, volunteer, role):
        self.add_board_member_to_chapter(frappe.get_doc("Chapter", chapter.name), volunteer, role)

    def _entry_2745(self, volunteer, chapter):
        """The volunteer's entry for ``chapter``: by link while it exists, by note once unlinked."""
        by_link = {"reference_doctype": "Chapter", "reference_name": chapter.name}
        by_note = {"reference_name": ["is", "not set"], "notes": ["like", f"%{chapter.name}%"]}
        for criteria in (by_link, by_note):
            row = frappe.db.get_value(
                "Volunteer Assignment",
                {"parent": volunteer.name, **criteria},
                ["status", "end_date", "reference_name", "notes"],
                as_dict=True,
            )
            if row:
                return row

    def _status_2745(self, volunteer):
        return frappe.db.get_value("Volunteer", volunteer.name, "status")

    def _delete_2745(self, chapter):
        frappe.delete_doc("Chapter", chapter.name, force=1)
        self.assertFalse(frappe.db.exists("Chapter", chapter.name), "fixture: really deleted")

    def test_deleting_the_chapter_completes_the_only_seat_and_leaves_the_volunteer_saveable(self):
        chapter, volunteer, role = self._chapter_2745(), self._volunteer_2745(), self._role_2745()
        self._seat_2745(chapter, volunteer, role)
        self.assertEqual(self._entry_2745(volunteer, chapter).status, "Active", "control: seated")
        self.assertEqual(self._status_2745(volunteer), "Active", "control: seated")

        self._delete_2745(chapter)

        entry = self._entry_2745(volunteer, chapter)
        self.assertEqual(entry.status, "Completed")
        self.assertEqual(str(entry.end_date), str(today()))
        self.assertFalse(entry.reference_name, "the dangling link is cleared")
        self.assertIn(chapter.name, entry.notes, "the history still says which chapter")
        self.assertEqual(self._status_2745(volunteer), "Inactive")
        frappe.get_doc("Volunteer", volunteer.name).save()  # raised LinkValidationError before

    def test_a_seat_in_another_chapter_keeps_the_volunteer_active_and_its_entry_untouched(self):
        deleted, kept = self._chapter_2745(), self._chapter_2745()
        volunteer, role = self._volunteer_2745(), self._role_2745()
        self._seat_2745(deleted, volunteer, role)
        self._seat_2745(kept, volunteer, role)
        self.assertEqual(self._entry_2745(volunteer, kept).status, "Active", "control: second seat")

        self._delete_2745(deleted)

        self.assertEqual(self._entry_2745(volunteer, deleted).status, "Completed")
        other = self._entry_2745(volunteer, kept)
        self.assertEqual(other.status, "Active")
        self.assertFalse(other.end_date)
        self.assertEqual(self._status_2745(volunteer), "Active")

    def test_a_non_board_entry_naming_the_chapter_is_completed_too(self):
        chapter, volunteer, role = self._chapter_2745(), self._volunteer_2745(), self._role_2745()
        self._seat_2745(chapter, volunteer, role)
        bystander = self._volunteer_2745()  # not on the board: reached only through its entry
        AssignmentHistoryManager.add_assignment_history(
            bystander.name, "Committee", "Chapter", chapter.name, "Helper", today()
        )
        self.assertEqual(self._entry_2745(bystander, chapter).status, "Active", "control: synthetic row")

        self._delete_2745(chapter)

        self.assertEqual(self._entry_2745(bystander, chapter).status, "Completed")
        frappe.get_doc("Volunteer", bystander.name).save()

    def test_a_completed_entry_is_not_rewritten(self):
        """An already-Completed entry keeps its own end_date but is unlinked too: its dangling link
        would make the volunteer unsaveable just the same."""
        chapter, volunteer, role = self._chapter_2745(), self._volunteer_2745(), self._role_2745()
        self._seat_2745(chapter, volunteer, role)
        name = frappe.db.get_value(
            "Volunteer Assignment", {"parent": volunteer.name, "reference_name": chapter.name}
        )
        frappe.db.set_value(  # probe shortcut: stands in for an earlier real completion
            "Volunteer Assignment", name, {"status": "Completed", "start_date": "2020-01-01", "end_date": "2020-01-31"}
        )

        self._delete_2745(chapter)

        entry = self._entry_2745(volunteer, chapter)
        self.assertEqual(str(entry.end_date), "2020-01-31")
        self.assertFalse(entry.reference_name, "but its dangling link is cleared as well")
        frappe.get_doc("Volunteer", volunteer.name).save()
