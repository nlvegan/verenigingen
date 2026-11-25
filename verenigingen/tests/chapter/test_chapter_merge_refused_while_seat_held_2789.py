"""#2789: a Chapter merge-rename is refused while any board seat is held.

A merge repoints the links, then deletes the old chapter, which withdraws the holders' board
access (#2147) but left their Volunteer Assignment history Active at the target chapter, where
they hold no seat. Maintainer ruling 2026-11-25 (option C): refuse; staff end or transfer the
seats first. An ended seat (``is_active = 0``) does not block.

Real flows: seats are added through a Chapter save, ended through a Chapter save, and the merge
is a real ``frappe.rename_doc("Chapter", old, new, merge=True)``. No probe shortcuts.

Helper names carry the issue number: the duplicate-helper baseline keys on the bare name.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase


class TestChapterMergeRefusedWhileSeatHeld2789(VereningingenTestCase):
    def _chapter_2789(self):
        return self.create_test_chapter(
            chapter_name=f"Mg2789 {frappe.generate_hash(length=6)}", postal_codes="6000-6999", published=1
        )

    def _seated_2789(self):
        chapter = self._chapter_2789()
        role = f"Role2789 {frappe.generate_hash(length=8)}"
        frappe.get_doc(
            {"doctype": "Chapter Role", "role_name": role, "permissions_level": "Basic", "is_active": 1}
        ).insert()
        self.track_doc("Chapter Role", role)
        member = self.create_test_member(
            first_name="Mg", last_name=f"V{frappe.generate_hash(length=6)}", birth_date="1985-01-01"
        )
        volunteer = self.create_test_volunteer(member_name=member.name)
        self.add_board_member_to_chapter(frappe.get_doc("Chapter", chapter.name), volunteer, role)
        return chapter, volunteer

    def _snapshot_2789(self, chapter, volunteer):
        return {
            "seats": frappe.get_all(
                "Chapter Board Member", filters={"parent": chapter.name}, fields=["name", "is_active"]
            ),
            "history": frappe.get_all(
                "Volunteer Assignment",
                filters={"parent": volunteer.name, "reference_name": chapter.name},
                fields=["name", "status", "reference_name"],
            ),
        }

    def test_merge_while_a_seat_is_held_is_refused_and_nothing_changes(self):
        old, volunteer = self._seated_2789()
        target = self._chapter_2789()
        before = self._snapshot_2789(old, volunteer)
        self.assertEqual([s.is_active for s in before["seats"]], [1], "control: a live seat")
        self.assertEqual([h.status for h in before["history"]], ["Active"], "control: history Active")

        with self.assertRaises(frappe.ValidationError) as ctx:
            frappe.rename_doc("Chapter", old.name, target.name, merge=True, force=True)

        self.assertIn("board seat", str(ctx.exception))
        self.assertTrue(frappe.db.exists("Chapter", old.name), "the old chapter must survive")
        self.assertEqual(self._snapshot_2789(old, volunteer), before, "no link repointed, nothing ended")
        self.assertFalse(frappe.get_all("Volunteer Assignment", filters={"reference_name": target.name}))
        frappe.get_doc("Volunteer", volunteer.name).save()

    def test_merge_with_no_seats_still_works(self):
        old, target = self._chapter_2789(), self._chapter_2789()

        frappe.rename_doc("Chapter", old.name, target.name, merge=True, force=True)

        self.assertFalse(frappe.db.exists("Chapter", old.name))
        self.assertTrue(frappe.db.exists("Chapter", target.name))

    def test_an_ended_seat_does_not_block_the_merge(self):
        old, volunteer = self._seated_2789()
        target = self._chapter_2789()
        chapter = frappe.get_doc("Chapter", old.name)
        for row in chapter.board_members:
            row.is_active = 0
        chapter.save()
        self.assertEqual(
            [s.is_active for s in self._snapshot_2789(old, volunteer)["seats"]], [0], "control: seat ended"
        )

        frappe.rename_doc("Chapter", old.name, target.name, merge=True, force=True)

        self.assertFalse(frappe.db.exists("Chapter", old.name))
        self.assertTrue(frappe.db.exists("Chapter", target.name))

    def test_a_plain_rename_is_not_affected_by_a_held_seat(self):
        old, _volunteer = self._seated_2789()
        new_name = f"Rn2789 {frappe.generate_hash(length=6)}"

        frappe.rename_doc("Chapter", old.name, new_name, force=True)
        self.track_doc("Chapter", new_name)

        self.assertTrue(frappe.db.exists("Chapter", new_name))
        self.assertFalse(frappe.db.exists("Chapter", old.name))
