"""#2250: several volunteers changed in ONE Chapter save must each get their own jobs.

``chapter_board_changed`` is emitted once per changed board row, and (unlike the membership
event) enqueues immediately with ``deduplicate=True``. Without per-row ``job_id_keys`` every
volunteer's job for a subscriber shares one id, and Frappe skips a job whose id is already
queued or running ("Not queueing job ... because it is in queue already").

CI has no RQ workers, so the test records ``frappe.enqueue`` calls from a REAL Chapter save and
asserts on the job ids and payloads that would have been queued.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase

SUBSCRIBERS = "verenigingen.events.subscribers.chapter_subscribers."


class TestChapterBoardJobIds2250(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter(
            chapter_name=f"Board Jobs {frappe.generate_hash(length=6)}",
            postal_codes="1000-9999",
            published=1,
        )
        self.role_a = self.create_test_chapter_role()
        self.role_b = self.create_test_chapter_role()
        self.volunteers = [self._volunteer(i) for i in range(2)]
        self._saved_flags = {
            k: getattr(frappe.flags, k, None) for k in ("in_import", "in_bulk_import", "bulk_chapter_operations")
        }
        frappe.flags.in_import = False
        frappe.flags.in_bulk_import = False
        frappe.flags.bulk_chapter_operations = False
        self._original_throttle_limit = frappe.local.conf.get("throttle_user_limit")
        self.addCleanup(self._restore_throttle_limit)
        frappe.local.conf["throttle_user_limit"] = 1000000

    def _restore_throttle_limit(self):
        if self._original_throttle_limit is None:
            frappe.local.conf.pop("throttle_user_limit", None)
        else:
            frappe.local.conf["throttle_user_limit"] = self._original_throttle_limit

    def tearDown(self):
        for k, v in self._saved_flags.items():
            setattr(frappe.flags, k, v)
        super().tearDown()

    def _volunteer(self, i):
        member = self.create_test_member(
            first_name=f"Board{i}",
            last_name="Jobs",
            email=f"board.jobs.{i}.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        return self.create_test_volunteer(member_name=member.name)

    def _save_recording_enqueues(self, mutate):
        """Run a real Chapter save, returning the enqueue kwargs of the board jobs."""
        jobs = []
        real_enqueue = frappe.enqueue

        def recording_enqueue(*args, **kwargs):
            jobs.append(kwargs)
            # Mock justified: the boundary under test is the worker queue (CI has none).

        chapter = frappe.get_doc("Chapter", self.chapter.name)
        mutate(chapter)
        frappe.enqueue = recording_enqueue
        try:
            chapter.save()
        finally:
            frappe.enqueue = real_enqueue
        return [j for j in jobs if j.get("event_name") == "chapter_board_changed"]

    def _row(self, chapter, volunteer, role):
        chapter.append(
            "board_members",
            {"volunteer": volunteer.name, "chapter_role": role.name, "from_date": today(), "is_active": 1},
        )

    def _ids_by_subscriber(self, jobs):
        by_sub = {}
        for j in jobs:
            by_sub.setdefault(j["method"], []).append(j["job_id"])
        return by_sub

    def _assert_one_job_per_volunteer(self, jobs, volunteers, action):
        self.assertEqual(len(jobs), 3 * len(volunteers), [j["job_id"] for j in jobs])
        for method, ids in self._ids_by_subscriber(jobs).items():
            self.assertEqual(len(ids), len(set(ids)), f"{method} jobs share an id (dedupe drops all but one): {ids}")
        for sub in ("handle_board_role_assignments", "handle_board_notifications", "handle_volunteer_sync"):
            got = {
                j["event_data"]["volunteer"]
                for j in jobs
                if j["method"] == SUBSCRIBERS + sub and j["event_data"]["action"] == action
            }
            self.assertEqual(got, {v.name for v in volunteers}, sub)

    def test_two_volunteers_added_in_one_save_get_distinct_job_ids(self):
        jobs = self._save_recording_enqueues(
            lambda c: [self._row(c, self.volunteers[0], self.role_a), self._row(c, self.volunteers[1], self.role_b)]
        )
        self._assert_one_job_per_volunteer(jobs, self.volunteers, "added")

    def test_two_volunteers_removed_in_one_save_get_distinct_job_ids(self):
        def seat(c):
            self._row(c, self.volunteers[0], self.role_a)
            self._row(c, self.volunteers[1], self.role_b)

        self._save_recording_enqueues(seat)

        def deactivate(c):
            for bm in c.board_members:
                bm.is_active = 0

        jobs = self._save_recording_enqueues(deactivate)
        self._assert_one_job_per_volunteer(jobs, self.volunteers, "removed")

    def test_two_volunteers_role_changed_in_one_save_get_distinct_job_ids(self):
        def seat(c):
            self._row(c, self.volunteers[0], self.role_a)
            self._row(c, self.volunteers[1], self.role_a)

        self._save_recording_enqueues(seat)

        def change(c):
            for bm in c.board_members:
                bm.chapter_role = self.role_b.name

        jobs = self._save_recording_enqueues(change)
        self._assert_one_job_per_volunteer(jobs, self.volunteers, "role_changed")

    def test_one_volunteer_given_two_roles_in_one_save_gets_one_job_per_role(self):
        """Same volunteer, same action, two roles: `volunteer`+`action` alone would collide."""
        jobs = self._save_recording_enqueues(
            lambda c: [self._row(c, self.volunteers[0], self.role_a), self._row(c, self.volunteers[0], self.role_b)]
        )
        self.assertEqual(len(jobs), 6)
        for method, ids in self._ids_by_subscriber(jobs).items():
            self.assertEqual(len(ids), len(set(ids)), f"{method}: {ids}")

    def test_control_a_single_change_keeps_a_stable_id_per_subscriber(self):
        """One change still dedupes against an identical re-emit (the point of the id)."""
        first = self._save_recording_enqueues(lambda c: self._row(c, self.volunteers[0], self.role_a))
        self.assertEqual(len(first), 3)
        self.assertEqual(len({j["job_id"] for j in first}), 3, "one id per subscriber")
        self.assertTrue(all(j["deduplicate"] is True for j in first))
