"""#2607: ending a seat through a STANDALONE Chapter Board Member write must derive Volunteer.status.

The seat is added by a Chapter save (real flow) and ended by saving or deleting the row on
its own, as #1953's hooks serve (REST ``PUT``/``DELETE``, ``get_doc(row).save()``). Probe
shortcut, named where used: the orphan-row test removes the Chapter with a raw
``frappe.db.delete`` because no real flow leaves a row behind (Chapter delete removes its rows).

Helper names carry the issue number: the duplicate-helper baseline keys on the bare name.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase


class TestStandaloneSeatEndStatus2607(VereningingenTestCase):
    def _role_2607(self):
        name = f"Role2607 {frappe.generate_hash(length=8)}"
        frappe.get_doc(
            {"doctype": "Chapter Role", "role_name": name, "permissions_level": "Basic", "is_active": 1}
        ).insert()
        self.track_doc("Chapter Role", name)
        return name

    def _volunteer_2607(self):
        member = self.create_test_member(
            first_name="Stand", last_name=f"V{frappe.generate_hash(length=6)}", birth_date="1985-01-01"
        )
        return self.create_test_volunteer(member_name=member.name)

    def _chapter_2607(self):
        return self.create_test_chapter(
            chapter_name=f"Ch2607 {frappe.generate_hash(length=6)}", postal_codes="7000-7999", published=1
        )

    def _seat_2607(self, chapter, volunteer, role):
        """Seat through a Chapter save; returns the persisted row's name."""
        self.add_board_member_to_chapter(frappe.get_doc("Chapter", chapter.name), volunteer, role)
        return frappe.db.get_value(
            "Chapter Board Member", {"parent": chapter.name, "volunteer": volunteer.name, "is_active": 1}
        )

    def _status_2607(self, volunteer):
        return frappe.db.get_value("Volunteer", volunteer.name, "status")

    def _history_2607(self, volunteer, chapter):
        return frappe.db.get_value(
            "Volunteer Assignment",
            {"parent": volunteer.name, "reference_doctype": "Chapter", "reference_name": chapter.name},
            ["status", "end_date"],
            as_dict=True,
        )

    def _end_row_2607(self, row_name):
        row = frappe.get_doc("Chapter Board Member", row_name)
        row.is_active = 0
        row.to_date = today()
        row.save()

    def test_a_standalone_row_save_ending_the_only_seat_makes_the_volunteer_inactive(self):
        chapter, volunteer, role = self._chapter_2607(), self._volunteer_2607(), self._role_2607()
        row = self._seat_2607(chapter, volunteer, role)
        self.assertEqual(self._status_2607(volunteer), "Active", "control: seating derives Active")
        self.assertEqual(self._history_2607(volunteer, chapter).status, "Active", "control")

        self._end_row_2607(row)

        self.assertFalse(frappe.db.exists("Chapter Board Member", {"volunteer": volunteer.name, "is_active": 1}))
        self.assertEqual(self._history_2607(volunteer, chapter).status, "Completed")
        self.assertEqual(self._status_2607(volunteer), "Inactive")

    def test_a_standalone_row_delete_of_the_only_seat_makes_the_volunteer_inactive(self):
        chapter, volunteer, role = self._chapter_2607(), self._volunteer_2607(), self._role_2607()
        row = self._seat_2607(chapter, volunteer, role)

        frappe.delete_doc("Chapter Board Member", row)

        self.assertFalse(frappe.db.exists("Chapter Board Member", row), "fixture: the row is gone")
        self.assertEqual(self._history_2607(volunteer, chapter).status, "Completed")
        self.assertEqual(self._status_2607(volunteer), "Inactive")

    def test_a_standalone_end_keeps_a_volunteer_with_a_seat_in_another_chapter_active(self):
        """Control: the other chapter's seat is a real row AND a real Active history entry."""
        chapter_a, chapter_b = self._chapter_2607(), self._chapter_2607()
        volunteer, role = self._volunteer_2607(), self._role_2607()
        row_a = self._seat_2607(chapter_a, volunteer, role)
        self._seat_2607(chapter_b, volunteer, role)

        self._end_row_2607(row_a)

        self.assertEqual(self._history_2607(volunteer, chapter_a).status, "Completed")
        self.assertEqual(self._history_2607(volunteer, chapter_b).status, "Active", "other seat untouched")
        self.assertEqual(self._status_2607(volunteer), "Active")

    def test_handing_the_row_to_another_volunteer_ends_the_previous_holders_seat(self):
        chapter, role = self._chapter_2607(), self._role_2607()
        old, new = self._volunteer_2607(), self._volunteer_2607()
        row_name = self._seat_2607(chapter, old, role)

        row = frappe.get_doc("Chapter Board Member", row_name)
        row.volunteer = new.name
        row.save()

        self.assertEqual(self._history_2607(old, chapter).status, "Completed")
        self.assertEqual(self._status_2607(old), "Inactive")

    def test_a_retired_volunteer_keeps_retired_when_the_standalone_seat_ends(self):
        """Probe shortcut: Retired is written with ``db.set_value`` after seating (a retired
        volunteer cannot be seated). The seat and its end are real."""
        chapter, volunteer, role = self._chapter_2607(), self._volunteer_2607(), self._role_2607()
        row = self._seat_2607(chapter, volunteer, role)
        frappe.db.set_value("Volunteer", volunteer.name, "status", "Retired")

        self._end_row_2607(row)

        self.assertEqual(self._history_2607(volunteer, chapter).status, "Completed")
        self.assertEqual(self._status_2607(volunteer), "Retired")

    def test_deleting_an_already_ended_row_changes_nothing(self):
        """Control: a row that no longer holds a seat must not touch the history of a
        volunteer who was re-seated in the same chapter."""
        chapter, volunteer, role = self._chapter_2607(), self._volunteer_2607(), self._role_2607()
        row = self._seat_2607(chapter, volunteer, role)
        self._end_row_2607(row)
        self._seat_2607(chapter, volunteer, role)  # re-seat: a second, Active entry
        self.assertEqual(self._status_2607(volunteer), "Active", "fixture")

        frappe.delete_doc("Chapter Board Member", row)

        self.assertEqual(self._status_2607(volunteer), "Active")
        self.assertTrue(
            frappe.db.exists(
                "Volunteer Assignment",
                {"parent": volunteer.name, "reference_name": chapter.name, "status": "Active"},
            ),
            "the live seat's history entry is still Active",
        )

    def test_an_orphan_row_delete_ends_the_seat_status(self):
        """Probe shortcut: the Chapter is removed with a raw ``frappe.db.delete`` to leave an
        orphan row (the state #1953's ``_withdraw_access_without_chapter`` serves)."""
        chapter, volunteer, role = self._chapter_2607(), self._volunteer_2607(), self._role_2607()
        row = self._seat_2607(chapter, volunteer, role)
        frappe.db.delete("Chapter", {"name": chapter.name})
        self.assertTrue(frappe.db.exists("Chapter Board Member", row), "fixture: orphan row")

        frappe.delete_doc("Chapter Board Member", row)

        self.assertEqual(self._status_2607(volunteer), "Inactive")

    def test_a_standalone_role_change_keeps_the_seat_active(self):
        """Control: the seat continues, so its history entry must not be completed."""
        chapter, volunteer, role = self._chapter_2607(), self._volunteer_2607(), self._role_2607()
        row_name = self._seat_2607(chapter, volunteer, role)

        row = frappe.get_doc("Chapter Board Member", row_name)
        row.chapter_role = self._role_2607()
        row.save()

        self.assertEqual(self._history_2607(volunteer, chapter).status, "Active")
        self.assertEqual(self._status_2607(volunteer), "Active")
