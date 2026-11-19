"""#2875: a seat with is_active=1 and a past to_date is real data that nothing ever ended.

Maintainer ruling (2026-11-19): a daily job ends every such seat THROUGH the Chapter save (the
seat-ending path that completes the volunteer's assignment history and withdraws the board
role/profile), and the ~45 ``is_active``-only readers stay unchanged.

Writer table for ``Chapter Board Member.is_active`` / ``to_date`` (real flows only; the lapsed
state is reached through them, never by a bare ``db.set_value``):

* Chapter save, Desk edit of the board table: accepts ``is_active=1`` beside a past ``to_date``
  (``BoardMemberValidator`` only warns) -> the lapsed state; ``to_date`` edited on an already
  live seat triggers no access recalculation (tested below), so the role is still on the user.
* Chapter save adding a row (``add_board_member_to_chapter``): same, with a past ``to_date`` set up front.
* Chapter save flipping ``is_active=0`` (``remove_board_member``, ``bulk_deactivate``): ends the seat;
  this job is the same route.
* Standalone row save (REST PUT, termination, ``ChapterAssignmentService``): ends a seat; the job
  never writes a row on its own.
* This job: ``is_active=0``, ``to_date`` left as the seat's own end date.
"""

from unittest import mock

import frappe
from frappe.utils import add_days, today

from verenigingen.services.chapter.board_seat_expiry_service import end_lapsed_board_seats
from verenigingen.services.member.account.user_role_profile_calculator import (
    PROFILE_BOARD_MEMBER,
    get_user_role_profiles,
)
from verenigingen.tests.utils.base import VereningingenTestCase

BOARD_ROLE = "Verenigingen Chapter Board Member"


class TestEndLapsedBoardSeats2875(VereningingenTestCase):
    def setUp(self):
        super().setUp()
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

    def tearDown(self):
        for user in [d["name"] for d in self._test_docs if d["doctype"] == "User"]:
            for employee in frappe.get_all("Employee", filters={"user_id": user}, pluck="name"):
                self.track_doc("Employee", employee)  # a seat's profile carries Employee (#1694)
        super().tearDown()

    # ------------------------------------------------------------------ helpers

    def _chapter_2875(self, tag):
        return self.create_test_chapter(
            chapter_name=f"Lapse {tag} {frappe.generate_hash(length=6)}",
            postal_codes="1000-9999",
            published=1,
        )

    def _person_2875(self, label):
        email = f"lapse2875.{label.lower()}.{frappe.generate_hash(length=8)}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        member = self.create_test_member(first_name=label, last_name="Lapse", email=email, status="Active")
        member.db_set("user", user.name, update_modified=False)
        volunteer = self.create_test_volunteer(member=member.name)
        return frappe._dict(user=user.name, volunteer=volunteer.name, email=email, member=member.name)

    def _seat_2875(self, chapter, person, to_date=None):
        """Seat through a Chapter save (the Desk flow); returns the row name."""
        chapter = frappe.get_doc("Chapter", chapter.name)
        extra = {"from_date": add_days(today(), -30)}
        if to_date:
            extra["to_date"] = to_date
        self.add_board_member_to_chapter(chapter, person.volunteer, self.role_name, email=person.email, **extra)
        return frappe.db.get_value(
            "Chapter Board Member", {"parent": chapter.name, "volunteer": person.volunteer}, "name"
        )

    def _desk_edit_to_date_2875(self, chapter, row_name, to_date):
        """A Desk edit of an already-seated row's end date (a Chapter save)."""
        chapter = frappe.get_doc("Chapter", chapter.name)
        next(r for r in chapter.board_members if r.name == row_name).to_date = to_date
        chapter.save()

    def _lapse_seat_2875(self, chapter, person):
        """Seat live (role + profile granted), then lapse the date by a Desk edit."""
        row = self._seat_2875(chapter, person, to_date=add_days(today(), 5))
        self._desk_edit_to_date_2875(chapter, row, add_days(today(), -1))
        return row

    def _state_2875(self, row):
        return frappe.db.get_value("Chapter Board Member", row, ["is_active", "to_date"], as_dict=True)

    def _roles_2875(self, user):
        return set(frappe.get_all("Has Role", filters={"parent": user, "parenttype": "User"}, pluck="role"))

    def _assignment_status_2875(self, person, chapter):
        return frappe.db.get_value(
            "Volunteer Assignment",
            {"parent": person.volunteer, "reference_doctype": "Chapter", "reference_name": chapter.name},
            "status",
        )

    # ------------------------------------------------------------------ the fix

    def test_a_lapsed_seat_is_ended_and_its_access_and_history_withdrawn(self):
        chapter = self._chapter_2875("a")
        person = self._person_2875("Gone")
        row = self._lapse_seat_2875(chapter, person)

        state = self._state_2875(row)
        self.assertEqual(state.is_active, 1, "fixture: the Desk edit left the seat active")
        self.assertLess(str(state.to_date), today(), "fixture: the end date is past")
        self.assertIn(BOARD_ROLE, self._roles_2875(person.user), "fixture: the board role is still granted")
        self.assertIn(PROFILE_BOARD_MEMBER, get_user_role_profiles(person.user), "fixture: profile granted")

        ended, failed = end_lapsed_board_seats()

        self.assertGreaterEqual(ended, 1)
        self.assertEqual(failed, [])
        after = self._state_2875(row)
        self.assertEqual(after.is_active, 0)
        self.assertEqual(str(after.to_date), str(state.to_date), "the seat keeps its own end date")
        self.assertNotIn(BOARD_ROLE, self._roles_2875(person.user), "board role survived")
        self.assertNotIn(PROFILE_BOARD_MEMBER, get_user_role_profiles(person.user), "board profile survived")
        self.assertEqual(self._assignment_status_2875(person, chapter), "Completed", "history not completed")

    def test_live_seats_and_inactive_seats_are_left_alone(self):
        """Controls: each is a real row the wrong (over-broad) fix would touch."""
        chapter = self._chapter_2875("c")
        today_p, future_p, open_p, inactive_p = (
            self._person_2875(n) for n in ("Today", "Future", "Open", "Inactive")
        )
        rows = {
            "today": self._seat_2875(chapter, today_p, to_date=today()),
            "future": self._seat_2875(chapter, future_p, to_date=add_days(today(), 3)),
            "open": self._seat_2875(chapter, open_p),
        }
        inactive_row = self._seat_2875(chapter, inactive_p, to_date=add_days(today(), -3))
        # An already-ended seat: is_active=0 with a past date, written by the Desk flow.
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        next(r for r in chapter_doc.board_members if r.name == inactive_row).is_active = 0
        chapter_doc.save()
        modified_before = frappe.db.get_value("Chapter Board Member", inactive_row, "modified")
        self.assertEqual(self._state_2875(inactive_row).is_active, 0, "fixture: seat already inactive")

        end_lapsed_board_seats()

        for tag, row in rows.items():
            self.assertEqual(self._state_2875(row).is_active, 1, f"{tag} seat must stay active")
        self.assertEqual(frappe.db.get_value("Chapter Board Member", inactive_row, "modified"), modified_before)

    def test_a_second_run_is_a_no_op(self):
        chapter = self._chapter_2875("i")
        person = self._person_2875("Twice")
        row = self._lapse_seat_2875(chapter, person)
        self.assertGreaterEqual(end_lapsed_board_seats()[0], 1)
        modified = frappe.db.get_value("Chapter Board Member", row, "modified")
        notes = frappe.db.get_value("Chapter Board Member", row, "notes")

        self.assertEqual(end_lapsed_board_seats(), (0, []))

        self.assertEqual(frappe.db.get_value("Chapter Board Member", row, "modified"), modified)
        self.assertEqual(frappe.db.get_value("Chapter Board Member", row, "notes"), notes)

    def test_one_chapter_that_cannot_be_saved_does_not_block_the_others(self):
        self.expectErrorLog("Board seat expiry failed")
        bad_chapter, good_chapter = self._chapter_2875("bad"), self._chapter_2875("good")
        bad_p, good_p = self._person_2875("Bad"), self._person_2875("Good")
        bad_row = self._lapse_seat_2875(bad_chapter, bad_p)
        good_row = self._lapse_seat_2875(good_chapter, good_p)

        from verenigingen.verenigingen.doctype.chapter.chapter import Chapter

        real_save = Chapter.save

        def save(chapter_doc, *args, **kwargs):
            if chapter_doc.name == bad_chapter.name:
                frappe.throw("simulated: this chapter cannot be saved")
            return real_save(chapter_doc, *args, **kwargs)

        errors_before = frappe.db.count("Error Log", {"method": ["like", "%Board seat expiry%"]})
        with mock.patch.object(Chapter, "save", save):
            end_lapsed_board_seats()

        self.assertEqual(self._state_2875(bad_row).is_active, 1, "the unsavable chapter's seat stays")
        self.assertEqual(self._state_2875(good_row).is_active, 0, "the failure blocked another chapter")
        logged = frappe.get_all(
            "Error Log",
            filters={"method": ["like", "%Board seat expiry%"]},
            fields=["method", "error"],
        )
        self.assertEqual(len(logged), errors_before + 1, "exactly the failing chapter is logged")
        self.assertTrue(any(bad_chapter.name in (e.method + e.error) for e in logged))

    def test_a_failing_chapter_save_leaves_none_of_its_rows_half_ended(self):
        """Savepoint: a save that dies AFTER writing the rows must not leave them written."""
        self.expectErrorLog("Board seat expiry failed")
        staff = self._staff_2875()
        chapter = self._chapter_2875("sp")
        person = self._person_2875("Half")
        row = self._lapse_seat_2875(chapter, person)

        from verenigingen.verenigingen.doctype.chapter.chapter import Chapter

        def on_update_boom(chapter_doc):
            frappe.throw("simulated: on_update failed after the rows were written")

        with mock.patch.object(Chapter, "on_update", on_update_boom):
            ended, failed = end_lapsed_board_seats()

        self.assertEqual(self._state_2875(row).is_active, 1, "the failed save left the seat half-ended")
        self.assertEqual(ended, 0)
        self.assertEqual([(c, r) for c, r, _why in failed], [(chapter.name, [row])])
        logged = [e for e in self._expiry_errors_2875() if chapter.name in e.method]
        self.assertEqual(len(logged), 1, "exactly one Error Log row for the failing chapter")
        self.assertEqual(len(self._alerts_2875(staff, chapter.name)), 1, "staff are told")

    def test_the_job_is_registered_on_the_long_daily_queue(self):
        """daily_long, not daily: the first run clears a whole backlog through full Chapter saves."""
        from verenigingen.hooks.scheduler import scheduler_events

        path = "verenigingen.services.chapter.board_seat_expiry_service.end_lapsed_board_seats"
        self.assertIn(path, scheduler_events["daily_long"])
        self.assertNotIn(path, scheduler_events["daily"])
        self.assertTrue(frappe.get_attr(path))

    def test_every_lapsed_seat_of_one_chapter_is_ended(self):
        """Two lapsed seats in ONE chapter: a pick-first loop (break after the first row) ends one."""
        chapter = self._chapter_2875("two")
        first, second = self._person_2875("First"), self._person_2875("Second")
        rows = [self._lapse_seat_2875(chapter, p) for p in (first, second)]
        self.assertEqual([self._state_2875(r).is_active for r in rows], [1, 1], "fixture")

        ended, failed = end_lapsed_board_seats()

        self.assertEqual((ended, failed), (2, []))
        self.assertEqual([self._state_2875(r).is_active for r in rows], [0, 0])
        for person in (first, second):
            self.assertNotIn(BOARD_ROLE, self._roles_2875(person.user))

    # ------------------------------------------------------------------ the staff alert (F1, F5)

    def _expiry_errors_2875(self):
        return frappe.get_all(
            "Error Log",
            filters={"method": ["like", "%Board seat expiry failed%"]},
            fields=["method", "error"],
            order_by="creation desc",
        )

    def _staff_2875(self):
        """A recipient of the registered key (the admin pair), so the alert can be delivered."""
        from verenigingen.setup.notification_registry_setup import ensure_notification_registry_rows

        ensure_notification_registry_rows()
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": f"expiry.alert.{frappe.generate_hash(length=8).lower()}@example.org",
                "first_name": "Expiry",
                "send_welcome_email": 0,
                "enabled": 1,
                "roles": [{"role": "Verenigingen Administrator"}],
            }
        ).insert()
        self.track_doc("User", user.name)
        return user.name

    def _alerts_2875(self, staff, chapter_name):
        return [
            log
            for log in frappe.get_all(
                "Notification Log",
                {"for_user": staff, "subject": ["like", "Board seats past their end date%"]},
                ["name", "email_content"],
            )
            if chapter_name in (log.email_content or "")
        ]

    def _break_chapter_2875(self, chapter):
        """Probe shortcut: point the chapter at a Role Profile that no longer exists (an admin deleting
        one), so Chapter.validate refuses every save. Stands in for the real deletion."""
        frappe.db.set_value("Chapter", chapter.name, "default_board_role_profile", "No Such Profile 2875")

    def test_a_chapter_that_cannot_be_saved_alerts_staff_once(self):
        self.expectErrorLog("Board seat expiry failed")
        staff = self._staff_2875()
        chapter = self._chapter_2875("stuck")
        person = self._person_2875("Stuck")
        row = self._lapse_seat_2875(chapter, person)
        self._break_chapter_2875(chapter)

        ended, failed = end_lapsed_board_seats()

        self.assertEqual(self._state_2875(row).is_active, 1, "fixture: the seat could not be ended")
        self.assertEqual((ended, [(c, r) for c, r, _w in failed]), (0, [(chapter.name, [row])]))
        alerts = self._alerts_2875(staff, chapter.name)
        self.assertEqual(len(alerts), 1, "staff must be told")
        self.assertIn(row, alerts[0].email_content, "the alert names the seat row")
        self.assertIn("No Such Profile 2875", alerts[0].email_content, "the alert names the reason")

        end_lapsed_board_seats()
        self.assertEqual(len(self._alerts_2875(staff, chapter.name)), 1, "the same chapter alerts once")

    def test_an_orphan_lapsed_seat_reaches_the_alert(self):
        """Parent Chapter gone (#2745 leaves rows behind): reported under its own reason, not ended."""
        self.expectErrorLog("Board seat expiry failed")
        staff = self._staff_2875()
        chapter = self._chapter_2875("orphan")
        person = self._person_2875("Orphan")
        row = self._lapse_seat_2875(chapter, person)
        # Probe shortcut: the Chapter row is deleted under the seat, as #2745's delete leaves it.
        frappe.db.delete("Chapter", {"name": chapter.name})
        self.assertTrue(frappe.db.exists("Chapter Board Member", row), "fixture: the orphan row is there")

        ended, failed = end_lapsed_board_seats()

        self.assertEqual(ended, 0)
        self.assertIn((chapter.name, [row], "parent chapter missing"), failed)
        alerts = self._alerts_2875(staff, chapter.name)
        self.assertEqual(len(alerts), 1)
        self.assertIn("parent chapter missing", alerts[0].email_content)
        self.assertEqual(self._state_2875(row).is_active, 1, "no new ending path for orphans")
