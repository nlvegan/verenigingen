"""#2137: chapter membership event jobs must not act for a rolled-back assignment.

``emit_event`` enqueues the chapter-membership subscribers the moment a Chapter
saves. Rolling back to a savepoint (``assign_with_cleanup`` #1793, the MijnRood
sync #2067) undoes the Chapter Member row but not the queued jobs, so the worker
mailed "Welcome to <chapter>" to a member who was not in it.

The jobs are captured by wrapping ``frappe.enqueue`` (CI has no RQ workers) and
then run directly, the way a worker would run them. Real flow: the chapter's own
``member_manager.add_member`` inside a real savepoint.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase

JOB_PREFIX = "verenigingen.events.subscribers.chapter_subscribers."


class TestChapterMembershipEventsRollback(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter(
            chapter_name=f"Rollback Chapter {frappe.generate_hash(length=6)}",
            postal_codes="1000-9999",
            published=1,
        )
        self.member = self.create_test_member(
            first_name="Rollback",
            last_name="Member",
            email=f"rollback.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        self._saved_flags = {
            k: getattr(frappe.flags, k, None) for k in ("in_import", "in_bulk_import", "bulk_chapter_operations")
        }
        # The harness sets in_import=True, which makes the subscribers early-return.
        frappe.flags.in_import = False
        frappe.flags.in_bulk_import = False
        frappe.flags.bulk_chapter_operations = False

    def tearDown(self):
        for k, v in self._saved_flags.items():
            setattr(frappe.flags, k, v)
        super().tearDown()

    def _capture_jobs(self, action):
        """Run ``action`` while recording every frappe.enqueue; return the jobs."""
        jobs = []
        real_enqueue = frappe.enqueue

        def recording_enqueue(*args, **kwargs):
            jobs.append(kwargs)
            # Mock justified: the boundary under test is the worker; the job is run
            # below by hand with the exact kwargs the worker would receive.

        frappe.enqueue = recording_enqueue
        try:
            action()
        finally:
            frappe.enqueue = real_enqueue
        return jobs

    def _run_jobs(self, jobs):
        for job in jobs:
            frappe.call(
                job["method"],
                **{k: v for k, v in job.items() if k in ("event_name", "event_data", "is_bulk_import")},
            )

    def _welcome_mails(self):
        return frappe.get_all(
            "Email Queue",
            filters={"reference_doctype": "Chapter", "reference_name": self.chapter.name},
            pluck="name",
        )

    @staticmethod
    def _has_role(user):
        return bool(frappe.db.exists("Has Role", {"parent": user, "role": "Chapter Member"}))

    def _add_member(self):
        return frappe.get_doc("Chapter", self.chapter.name).member_manager.add_member(
            self.member.name, notify=False
        )

    def _enabled_rows(self):
        return frappe.db.count(
            "Chapter Member", {"parent": self.chapter.name, "member": self.member.name, "enabled": 1}
        )

    def test_control_committed_assignment_sends_the_welcome(self):
        jobs = self._capture_jobs(lambda: self.assertTrue(self._add_member()["success"]))
        self.assertTrue(any(j["method"] == JOB_PREFIX + "handle_membership_notifications" for j in jobs))
        self.assertEqual(self._enabled_rows(), 1)

        self._run_jobs(jobs)

        self.assertEqual(len(self._welcome_mails()), 1, "a real assignment must still be welcomed")

    def test_rolled_back_assignment_sends_no_welcome(self):
        savepoint = f"t2137_{frappe.generate_hash(length=8)}"
        frappe.db.savepoint(savepoint)
        jobs = self._capture_jobs(lambda: self.assertTrue(self._add_member()["success"]))
        frappe.db.rollback(save_point=savepoint)
        self.assertEqual(self._enabled_rows(), 0, "precondition: the assignment was rolled back")
        self.assertTrue(
            any(j["method"] == JOB_PREFIX + "handle_membership_notifications" for j in jobs),
            "precondition: the emitter queued the notification job",
        )

        self._run_jobs(jobs)

        self.assertEqual(self._welcome_mails(), [], "no welcome for a chapter the member is not in")

    def test_job_queued_for_a_join_is_held_until_commit(self):
        """The enqueue itself: membership jobs wait for the commit, other chapter events do not."""
        jobs = self._capture_jobs(lambda: self._add_member())
        self.assertEqual(len(jobs), 3)
        self.assertTrue(all(j["enqueue_after_commit"] is True for j in jobs), jobs)

        from verenigingen.events import chapter_events

        other = self._capture_jobs(
            lambda: chapter_events.emit_chapter_settings_changed(
                self.chapter.name, {"changed_fields": ["published"]}
            )
        )
        self.assertTrue(other)
        self.assertFalse(any(j["enqueue_after_commit"] for j in other), "settings events keep #168's default")

    def test_departure_job_is_skipped_when_the_member_is_back_in_the_chapter(self):
        """A 'left' job whose removal was rolled back must not send the farewell."""
        self.assertTrue(self._add_member()["success"])
        job = {
            "method": JOB_PREFIX + "handle_membership_notifications",
            "event_name": "chapter_membership_changed",
            "event_data": {"chapter": self.chapter.name, "member": self.member.name, "action": "left"},
            "is_bulk_import": False,
        }
        self._run_jobs([job])
        self.assertEqual(self._welcome_mails(), [], "member is still in the chapter: no farewell")

    def test_departure_job_still_sends_the_farewell_when_the_member_is_gone(self):
        """Control for the test above: a real departure is still announced."""
        job = {
            "method": JOB_PREFIX + "handle_membership_notifications",
            "event_name": "chapter_membership_changed",
            "event_data": {"chapter": self.chapter.name, "member": self.member.name, "action": "left"},
            "is_bulk_import": False,
        }
        self._run_jobs([job])
        self.assertEqual(len(self._welcome_mails()), 1)

    def test_rolled_back_assignment_grants_no_chapter_member_role(self):
        """The role-update job is guarded the same way as the mail job."""
        if not frappe.db.exists("Role", "Chapter Member"):
            frappe.get_doc({"doctype": "Role", "role_name": "Chapter Member"}).insert()
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": f"rollback.user.{frappe.generate_hash(length=6)}@test.invalid",
                "first_name": "Rollback",
                "send_welcome_email": 0,
            }
        ).insert()
        self.track_doc("User", user.name)
        frappe.db.set_value("Member", self.member.name, "user", user.name)  # probe shortcut: link only
        savepoint = f"t2137_{frappe.generate_hash(length=8)}"
        frappe.db.savepoint(savepoint)
        jobs = self._capture_jobs(lambda: self._add_member())
        frappe.db.rollback(save_point=savepoint)

        self._run_jobs([j for j in jobs if j["method"].endswith("handle_member_role_updates")])
        self.assertFalse(self._has_role(user.name))

        # control: committed assignment grants it
        jobs = self._capture_jobs(lambda: self._add_member())
        self._run_jobs([j for j in jobs if j["method"].endswith("handle_member_role_updates")])
        self.assertTrue(self._has_role(user.name))

    def test_refused_assign_with_cleanup_sends_no_farewell(self):
        """#1793's own rollback: a refused move must leave no farewell or welcome behind.

        A non-Active member is refused by the add AFTER the cleanup removed them from
        their current chapter; everything rolls back, so they are still in it. Probe
        shortcut: the status is set with db_set after joining, standing in for a
        member who became Suspended.
        """
        from verenigingen.services.chapter.chapter_assignment_service import ChapterAssignmentService

        target = self.create_test_chapter(
            chapter_name=f"Rollback Target {frappe.generate_hash(length=6)}",
            postal_codes="1000-9999",
            published=1,
        )
        self.assertTrue(self._add_member()["success"])
        frappe.db.set_value("Member", self.member.name, "status", "Suspended")

        result = {}
        jobs = self._capture_jobs(
            lambda: result.update(ChapterAssignmentService().assign_with_cleanup(self.member.name, target.name))
        )

        self.assertFalse(result.get("success"), "precondition: the move was refused")
        self.assertEqual(self._enabled_rows(), 1, "precondition: still in the old chapter")

        # Whatever the refused move queued (today remove_member flips `enabled` without
        # dropping the row, so the member-set diff emits nothing) must not mail anyone.
        self._run_jobs(jobs)

        self.assertEqual(self._welcome_mails(), [], "no farewell: the member never left")
