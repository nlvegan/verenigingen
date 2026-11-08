"""#2144: member and team event jobs must not act for a rolled-back save.

Class sibling of #2137. ``emit_event`` enqueued the member and team subscribers the
moment the document saved, so a save rolled back to a savepoint (member merge, CSV
import, application payments) still disabled the member's User, mailed them, or wrote
assignment history for a change that never happened.

Jobs are captured by wrapping ``frappe.enqueue`` (CI has no RQ workers, this bench
does) and then run by hand with the kwargs a worker would receive. The saves are real
Member / Team saves inside a real savepoint.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase

MEMBER_JOBS = "verenigingen.events.subscribers.member_subscribers."
MEMBER_MAIL_FACTORY = "verenigingen.services.communication.compatibility.get_email_service"
TEAM_MAIL_FACTORY = "verenigingen.services.communication.email_service.get_email_service"
TEAM_JOBS = "verenigingen.events.subscribers.team_subscribers."


class _RollbackBase(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self._saved_flags = {
            k: getattr(frappe.flags, k, None)
            for k in ("in_import", "in_bulk_import", "bulk_member_operations", "bulk_team_operations", "in_test", "skip_volunteer_account_creation")
        }
        # The harness sets in_import=True (subscribers then early-return) and in_test=True
        # (Member.on_update then skips event emission). Production has neither.
        frappe.flags.in_import = False
        frappe.flags.in_bulk_import = False
        frappe.flags.bulk_member_operations = False
        frappe.flags.bulk_team_operations = False
        frappe.flags.in_test = False
        # Each create_test_volunteer() would otherwise leave an untracked test-volunteer-* User
        # behind (11 per run); this module builds its own User where it needs one.
        frappe.flags.skip_volunteer_account_creation = True
        # in_import=False also re-arms Frappe's throttle_user_creation() (>60 Users created in
        # the last hour raises "Throttled"), and these setUps insert a User. Raise the limit
        # instead, as enhanced_test_factory does; restore via addCleanup so it cannot leak.
        self._had_throttle_limit = "throttle_user_limit" in frappe.local.conf
        self._original_throttle_limit = frappe.local.conf.get("throttle_user_limit")
        self.addCleanup(self._restore_throttle_limit_2144)
        frappe.local.conf["throttle_user_limit"] = 1000000

    def _restore_throttle_limit_2144(self):
        if self._had_throttle_limit:
            frappe.local.conf["throttle_user_limit"] = self._original_throttle_limit
        else:
            frappe.local.conf.pop("throttle_user_limit", None)

    def tearDown(self):
        for k, v in self._saved_flags.items():
            setattr(frappe.flags, k, v)
        super().tearDown()

    def _capture_jobs_2144(self, action):
        jobs = []
        real_enqueue = frappe.enqueue

        def recording_enqueue(*args, **kwargs):
            # Only the event subscribers are of interest; other hooks enqueue too.
            if str(kwargs.get("method", "")).startswith("verenigingen.events.subscribers."):
                jobs.append(kwargs)
            # Mock justified: the boundary under test is the worker; the job is run
            # below by hand with the exact kwargs the worker would receive.

        frappe.enqueue = recording_enqueue
        try:
            action()
        finally:
            frappe.enqueue = real_enqueue
        return jobs

    def _run_jobs_2144(self, jobs, only=None):
        for job in jobs:
            if only and not job["method"].endswith(only):
                continue
            frappe.call(
                job["method"],
                **{k: v for k, v in job.items() if k in ("event_name", "event_data", "is_bulk_import")},
            )

    @contextmanager
    def _mail_boundary(self):
        """Replace the EmailService factory the notification path calls (the boundary)."""
        service = MagicMock(name="EmailService")
        with patch(self.MAIL_FACTORY, return_value=service):
            yield service

    def _rolled_back(self, action):
        """Run ``action`` inside a savepoint, roll it back, return the jobs it queued."""
        savepoint = f"t2144_{frappe.generate_hash(length=8)}"
        frappe.db.savepoint(savepoint)
        jobs = self._capture_jobs_2144(action)
        frappe.db.rollback(save_point=savepoint)
        return jobs


class TestMemberEventsRollback(_RollbackBase):
    MAIL_FACTORY = MEMBER_MAIL_FACTORY

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="Rollback",
            last_name="Evt",
            email=f"rollback.evt.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        self.user = frappe.get_doc(
            {
                "doctype": "User",
                "email": f"rollback.evt.user.{frappe.generate_hash(length=6)}@test.invalid",
                "first_name": "Rollback",
                "send_welcome_email": 0,
                "enabled": 1,
            }
        ).insert(ignore_permissions=True)
        self.track_doc("User", self.user.name)
        member = frappe.get_doc("Member", self.member.name)
        member.user = self.user.name
        member.save(ignore_permissions=True)

    def _user_enabled(self):
        return frappe.db.get_value("User", self.user.name, "enabled")

    def _set_2144(self, **values):
        member = frappe.get_doc("Member", self.member.name)
        member.update(values)
        member.save()

    def _suspend_2144(self):
        self._set_2144(status="Suspended")

    def _approve_2144(self):
        self._set_2144(application_status="Approved")

    def test_control_committed_suspension_mails_the_member(self):
        jobs = self._capture_jobs_2144(self._suspend_2144)
        self.assertEqual(frappe.db.get_value("Member", self.member.name, "status"), "Suspended")
        with self._mail_boundary() as service:
            self._run_jobs_2144(jobs, only="handle_lifecycle_notifications")
        service.send_notification.assert_called_once()

    def test_rolled_back_suspension_sends_no_mail(self):
        jobs = self._rolled_back(self._suspend_2144)
        self.assertEqual(frappe.db.get_value("Member", self.member.name, "status"), "Active")
        self.assertTrue(any(j["method"].endswith("handle_lifecycle_notifications") for j in jobs))
        with self._mail_boundary() as service:
            self._run_jobs_2144(jobs, only="handle_lifecycle_notifications")
        service.send_notification.assert_not_called()

    def test_control_committed_approval_mails_the_member(self):
        jobs = self._capture_jobs_2144(self._approve_2144)
        self.assertEqual(frappe.db.get_value("Member", self.member.name, "application_status"), "Approved")
        with self._mail_boundary() as service:
            self._run_jobs_2144(jobs, only="handle_status_change_notifications")
        service.send_notification.assert_called_once()

    def test_rolled_back_approval_sends_no_mail(self):
        before = frappe.db.get_value("Member", self.member.name, "application_status")
        jobs = self._rolled_back(self._approve_2144)
        self.assertEqual(frappe.db.get_value("Member", self.member.name, "application_status"), before)
        self.assertTrue(any(j["method"].endswith("handle_status_change_notifications") for j in jobs))
        with self._mail_boundary() as service:
            self._run_jobs_2144(jobs, only="handle_status_change_notifications")
        service.send_notification.assert_not_called()

    def test_user_account_job_ignores_a_status_the_member_does_not_have(self):
        """Probe shortcut: the payload is hand-built (old != new). A real save emits
        old_status == new_status (get_db_value runs after the write in on_update), so
        handle_user_account_updates never disables anyone from a real event today; the
        guard is for when that is fixed."""
        data = {"member": self.member.name, "old_status": "Active", "new_status": "Suspended"}
        self._run_jobs_2144(
            [
                {
                    "method": MEMBER_JOBS + "handle_user_account_updates",
                    "event_name": "member_lifecycle_changed",
                    "event_data": data,
                    "is_bulk_import": False,
                }
            ]
        )
        self.assertEqual(self._user_enabled(), 1)

    def test_control_user_account_job_disables_when_the_member_is_suspended(self):
        """Control for the test above: with the status really held, the user is disabled."""
        self._suspend_2144()
        data = {"member": self.member.name, "old_status": "Active", "new_status": "Suspended"}
        self._run_jobs_2144(
            [
                {
                    "method": MEMBER_JOBS + "handle_user_account_updates",
                    "event_name": "member_lifecycle_changed",
                    "event_data": data,
                    "is_bulk_import": False,
                }
            ]
        )
        self.assertEqual(self._user_enabled(), 0)

    def _seat_in_chapter(self):
        chapter = self.create_test_chapter(
            chapter_name=f"Rollback Seat {frappe.generate_hash(length=6)}",
            postal_codes="1000-9999",
            published=1,
        )
        doc = frappe.get_doc("Chapter", chapter.name)
        doc.append("members", {"member": self.member.name, "status": "Active", "enabled": 1})
        doc.save()
        return frappe.db.get_value(
            "Chapter Member", {"parent": chapter.name, "member": self.member.name}, "name"
        )

    def _chapter_row_status(self, row):
        return frappe.db.get_value("Chapter Member", row, "status")

    def test_rolled_back_suspension_leaves_the_chapter_membership_active(self):
        """Dead branch today; guards the path if it is wired. handle_chapter_assignment_updates
        deactivates chapter rows on Suspended, but production subscribes it only to
        member_status_changed, which carries application statuses, so this payload is
        hand-built (probe shortcut, same shape as the user-account pair)."""
        row = self._seat_in_chapter()
        jobs = self._rolled_back(self._suspend_2144)
        self.assertEqual(frappe.db.get_value("Member", self.member.name, "status"), "Active")
        job = {
            "method": MEMBER_JOBS + "handle_chapter_assignment_updates",
            "event_name": "member_lifecycle_changed",
            "event_data": {"member": self.member.name, "old_status": "Active", "new_status": "Suspended"},
            "is_bulk_import": False,
        }
        self.assertTrue(jobs)
        self._run_jobs_2144([job])
        self.assertEqual(self._chapter_row_status(row), "Active", "the member was never suspended")

    def test_control_committed_suspension_deactivates_the_chapter_membership(self):
        """Dead branch today; guards the path if it is wired (hand-built payload, see above)."""
        row = self._seat_in_chapter()
        self._suspend_2144()
        job = {
            "method": MEMBER_JOBS + "handle_chapter_assignment_updates",
            "event_name": "member_lifecycle_changed",
            "event_data": {"member": self.member.name, "old_status": "Active", "new_status": "Suspended"},
            "is_bulk_import": False,
        }
        self._run_jobs_2144([job])
        self.assertEqual(self._chapter_row_status(row), "Inactive")

    def _enable_chapter_assignment_2144(self):
        """A published chapter that covers the member's postal code, plus the setting the
        lookup requires. Probe shortcut: the member's primary_address is set directly."""
        settings = frappe.get_single("Verenigingen Settings")
        was_enabled = settings.enable_chapter_management
        settings.db_set("enable_chapter_management", 1)
        self.addCleanup(settings.db_set, "enable_chapter_management", was_enabled)
        area = 7000 + int(frappe.generate_hash(length=3), 16) % 900
        self.create_test_chapter(
            chapter_name=f"Rollback Assign {frappe.generate_hash(length=6)}",
            postal_codes=f"{area}-{area}",
            published=1,
        )
        # The chapter factory seats the newest Member in the chapter it builds; the test
        # needs the member unseated, so only the job under test can seat it.
        frappe.db.delete("Chapter Member", {"member": self.member.name})
        address = frappe.get_doc(
            {
                "doctype": "Address",
                "address_title": f"Rollback {frappe.generate_hash(length=6)}",
                "address_line1": "Teststraat 1",
                "city": "Rollbackstad",
                "pincode": f"{area}AB",
                "country": "Netherlands",
            }
        ).insert()
        self.track_doc("Address", address.name)
        frappe.db.set_value("Member", self.member.name, "primary_address", address.name)
        self._reset_chapter_lookup_2144()
        self.addCleanup(self._reset_chapter_lookup_2144)

    def _reset_chapter_lookup_2144(self):
        from verenigingen.services.chapter.optimized_chapter_lookup import get_lookup_instance

        get_lookup_instance().invalidate_cache()

    def _chapter_rows_2144(self):
        return frappe.db.count("Chapter Member", {"member": self.member.name})

    def _approval_chapter_job_2144(self, jobs):
        return [j for j in jobs if j["method"].endswith("handle_chapter_assignment_updates")]

    def test_control_committed_approval_assigns_the_member_to_a_chapter(self):
        """Real flow: a real approval save emits member_status_changed (application status)."""
        self._enable_chapter_assignment_2144()
        self.assertEqual(self._chapter_rows_2144(), 0, "precondition: member is unseated")
        jobs = self._capture_jobs_2144(self._approve_2144)
        self.assertEqual(self._chapter_rows_2144(), 0, "the approval save itself seats nobody")
        job_list = self._approval_chapter_job_2144(jobs)
        self.assertTrue(job_list, "approval must queue the chapter assignment job")
        self._run_jobs_2144(job_list)
        self.assertEqual(self._chapter_rows_2144(), 1)

    def test_rolled_back_approval_assigns_no_chapter(self):
        """Real flow: the approval is rolled back, then its chapter job runs. The member was
        never approved, so no Chapter Member row may appear."""
        self._enable_chapter_assignment_2144()
        self.assertEqual(self._chapter_rows_2144(), 0, "precondition: member is unseated")
        jobs = self._rolled_back(self._approve_2144)
        self.assertEqual(frappe.db.get_value("Member", self.member.name, "application_status"), "Pending")
        job_list = self._approval_chapter_job_2144(jobs)
        self.assertTrue(job_list, "the rolled-back save still queued the job")
        self._run_jobs_2144(job_list)
        self.assertEqual(self._chapter_rows_2144(), 0)

    def test_member_jobs_are_held_until_commit(self):
        jobs = self._capture_jobs_2144(self._suspend_2144) + self._capture_jobs_2144(self._approve_2144)
        self.assertEqual(len(jobs), 5)
        self.assertTrue(all(j["enqueue_after_commit"] is True for j in jobs), jobs)


class TestTeamEventsRollback(_RollbackBase):
    MAIL_FACTORY = TEAM_MAIL_FACTORY

    def setUp(self):
        super().setUp()
        self.volunteer = self.create_test_volunteer()
        # The volunteer factory makes its own Member; that is the one the team code reads.
        self.member = frappe.get_doc("Member", self.volunteer.member)
        self.member.db_set("email", f"teamroll.{frappe.generate_hash(length=6)}@test.invalid")
        self.user = frappe.get_doc(
            {
                "doctype": "User",
                "email": f"teamroll.user.{frappe.generate_hash(length=6)}@test.invalid",
                "first_name": "TeamRoll",
                "send_welcome_email": 0,
                "enabled": 1,
            }
        ).insert(ignore_permissions=True)
        self.track_doc("User", self.user.name)
        member = frappe.get_doc("Member", self.member.name)
        member.user = self.user.name
        member.save(ignore_permissions=True)
        suffix = frappe.generate_hash(length=6)
        self.team = self._insert_2144(
            {
                "doctype": "Team",
                "team_name": f"Rollback Team {suffix}",
                "status": "Active",
                "team_type": "Project Team",
                "start_date": frappe.utils.today(),
                "description": "#2144 rollback test",
            }
        )
        self.leader_role = self._team_role(f"Rollback Lead {suffix}", leader=1)
        self.member_role = self._team_role(f"Rollback Member {suffix}", leader=0)

    def _insert_2144(self, values):
        doc = frappe.get_doc(values).insert()
        self.track_doc(doc.doctype, doc.name)
        return doc

    def _team_role(self, name, leader):
        return self._insert_2144(
            {
                "doctype": "Team Role",
                "role_name": name,
                "permissions_level": "Leader" if leader else "Basic",
                "is_team_leader": leader,
                "is_unique": leader,
                "is_active": 1,
            }
        )

    def _join_2144(self, role):
        team = frappe.get_doc("Team", self.team.name)
        team.append(
            "team_members",
            {
                "volunteer": self.volunteer.name,
                "team_role": role.name,
                "from_date": frappe.utils.today(),
                "is_active": 1,
                "status": "Active",
            },
        )
        team.save()

    def _join_as_member_2144(self):
        self._join_2144(self.member_role)

    def _join_as_leader(self):
        self._join_2144(self.leader_role)

    def _history(self):
        return frappe.get_all(
            "Volunteer Assignment",
            filters={
                "parent": self.volunteer.name,
                "parenttype": "Volunteer",
                "reference_doctype": "Team",
                "reference_name": self.team.name,
            },
            pluck="name",
        )

    def _team_permission(self):
        return frappe.db.exists(
            "User Permission", {"user": self.user.name, "allow": "Team", "for_value": self.team.name}
        )

    def test_control_committed_join_writes_history_and_mails(self):
        jobs = self._capture_jobs_2144(self._join_as_member_2144)
        with self._mail_boundary() as service:
            self._run_jobs_2144(jobs)
        self.assertEqual(len(self._history()), 1, "a real join must still be recorded")
        service.send_templated_email.assert_called_once()

    def test_rolled_back_join_writes_no_history_and_sends_no_mail(self):
        jobs = self._rolled_back(self._join_as_member_2144)
        self.assertEqual(
            frappe.db.count("Team Member", {"parent": self.team.name, "volunteer": self.volunteer.name}), 0
        )
        methods = {j["method"] for j in jobs}
        self.assertIn(TEAM_JOBS + "handle_assignment_history_updates", methods)
        self.assertIn(TEAM_JOBS + "handle_membership_notifications", methods)
        with self._mail_boundary() as service:
            self._run_jobs_2144(jobs)
        self.assertEqual(self._history(), [], "no history for a team the volunteer is not in")
        service.send_templated_email.assert_not_called()

    def test_control_committed_leader_gets_the_team_permission(self):
        jobs = self._capture_jobs_2144(self._join_as_leader)
        self.assertEqual(frappe.db.get_value("Team", self.team.name, "team_lead"), self.user.name)
        with self._mail_boundary():
            self._run_jobs_2144(jobs, only="handle_team_lead_permissions")
        self.assertTrue(self._team_permission())

    def test_rolled_back_leader_gets_no_team_permission_and_no_mail(self):
        jobs = self._rolled_back(self._join_as_leader)
        self.assertFalse(frappe.db.get_value("Team", self.team.name, "team_lead"))
        self.assertTrue(any(j["method"].endswith("handle_team_lead_permissions") for j in jobs))
        with self._mail_boundary() as service:
            self._run_jobs_2144(jobs)
        self.assertFalse(self._team_permission(), "the volunteer never became lead")
        service.send_templated_email.assert_not_called()

    def test_team_jobs_are_held_until_commit(self):
        jobs = self._capture_jobs_2144(self._join_as_leader)
        self.assertGreaterEqual(len(jobs), 4)
        self.assertTrue(all(j["enqueue_after_commit"] is True for j in jobs), jobs)

    def _stale_job(self, **data):
        return {
            "method": TEAM_JOBS + "handle_membership_notifications",
            "event_name": "team_membership_changed",
            "event_data": {"team": self.team.name, "volunteer": self.volunteer.name, **data},
            "is_bulk_import": False,
        }

    def test_removal_job_is_skipped_while_the_volunteer_is_still_in_the_team(self):
        """Probe shortcut: hand-built 'removed' payload for a volunteer who is still active
        (a rolled-back removal). Control: the same job after a real deactivation mails."""
        self._join_as_member_2144()
        row = frappe.get_doc("Team", self.team.name).team_members[0]
        stale = self._stale_job(action="removed", from_date=str(row.from_date), old_role=row.team_role)
        with self._mail_boundary() as service:
            self._run_jobs_2144([stale])
        service.send_templated_email.assert_not_called()

        team = frappe.get_doc("Team", self.team.name)
        team.team_members[0].is_active = 0
        team.save()
        with self._mail_boundary() as service:
            self._run_jobs_2144([stale])
        service.send_templated_email.assert_called_once()

    def test_role_change_job_is_skipped_when_the_row_has_another_role(self):
        """Probe shortcut: hand-built payload naming a role the row does not hold."""
        self._join_as_member_2144()
        row = frappe.get_doc("Team", self.team.name).team_members[0]
        with self._mail_boundary() as service:
            self._run_jobs_2144(
                [self._stale_job(action="role_changed", role=self.leader_role.name, old_role=row.team_role)]
            )
        service.send_templated_email.assert_not_called()
        with self._mail_boundary() as service:
            self._run_jobs_2144(
                [self._stale_job(action="role_changed", role=row.team_role, old_role=self.leader_role.name)]
            )
        service.send_templated_email.assert_called_once()

    def test_rolled_back_role_change_leaves_the_history_alone(self):
        """A role change is reported as role_changed (#2181 normalised the emitter's from_date
        key, so it no longer arrives as removed + added). Rolled back, the row still has the
        old role, so no such job may touch the history."""
        self._join_and_record_history()
        before = self._history_roles()

        jobs = self._rolled_back(self._promote_to_leader)
        self.assertTrue(any(j["event_data"].get("action") == "role_changed" for j in jobs), jobs)
        self._run_jobs_2144(jobs, only="handle_assignment_history_updates")

        self.assertEqual(self._history_roles(), before)

    def test_control_committed_role_change_completes_the_old_role_and_adds_the_new(self):
        self._join_and_record_history()
        jobs = self._capture_jobs_2144(self._promote_to_leader)
        self._run_jobs_2144(jobs, only="handle_assignment_history_updates")

        statuses = {status for status, _ in self._history_roles()}
        self.assertEqual(statuses, {"Completed", "Active"}, self._history_roles())

    def _join_and_record_history(self):
        jobs = self._capture_jobs_2144(self._join_as_member_2144)
        self._run_jobs_2144(jobs, only="handle_assignment_history_updates")

    def _promote_to_leader(self):
        team = frappe.get_doc("Team", self.team.name)
        team.team_members[0].team_role = self.leader_role.name
        team.save()

    def _history_roles(self):
        return sorted(
            frappe.get_all(
                "Volunteer Assignment",
                filters={"parent": self.volunteer.name, "reference_name": self.team.name},
                fields=["status", "role"],
                as_list=True,
            )
        )

    def test_removal_of_an_old_role_holds_while_the_volunteer_keeps_another_role(self):
        """A removal naming a role the volunteer's row no longer holds is still processed.
        Probe shortcut: hand-built payload. Since #2181 Team no longer emits this shape for a
        role change (it is one role_changed), so this guards queued or foreign payloads only."""
        self._join_as_member_2144()
        row = frappe.get_doc("Team", self.team.name).team_members[0]
        with self._mail_boundary() as service:
            self._run_jobs_2144(
                [
                    self._stale_job(
                        action="removed", from_date=row.from_date, old_role=self.leader_role.name
                    )
                ]
            )
        service.send_templated_email.assert_called_once()

    def _row_2144(self, volunteer, from_date=None):
        return {
            "volunteer": volunteer.name,
            "team_role": self.member_role.name,
            "from_date": from_date or frappe.utils.today(),
            "is_active": 1,
            "status": "Active",
        }

    def _add_rows_in_one_save_2144(self, rows):
        def save():
            team = frappe.get_doc("Team", self.team.name)
            for row in rows:
                team.append("team_members", row)
            team.save()

        return [
            j
            for j in self._capture_jobs_2144(save)
            if j["method"].endswith("handle_membership_notifications")
        ]

    def test_two_volunteers_added_in_one_save_each_get_their_own_job(self):
        """Jobs deferred to commit with the same job_id overwrite each other, so the last
        volunteer's payload would run twice and the first never. Run what a worker would
        receive per distinct id: each volunteer is mailed exactly once."""
        other = self.create_test_volunteer()
        jobs = self._add_rows_in_one_save_2144([self._row_2144(self.volunteer), self._row_2144(other)])
        self.assertEqual(len(jobs), 2)
        ids = [j["job_id"] for j in jobs]
        self.assertEqual(len(set(ids)), 2, ids)
        for volunteer in (self.volunteer, other):
            self.assertEqual(sum(volunteer.name in i for i in ids), 1, ids)

        # A job queue keeps ONE job per id (the last enqueued wins), as deduplicate does.
        by_id = {j["job_id"]: j for j in jobs}
        with self._mail_boundary() as service:
            self._run_jobs_2144(list(by_id.values()))
        mailed = [call.kwargs["recipients"][0] for call in service.send_templated_email.call_args_list]
        expected = sorted(frappe.db.get_value("Member", v.member, "email") for v in (self.volunteer, other))
        self.assertEqual(sorted(mailed), expected)

    def test_one_volunteer_added_twice_in_one_save_gets_a_job_per_row(self):
        """Same volunteer, same action, different from_date: the id must tell the rows apart."""
        earlier = frappe.utils.add_days(frappe.utils.today(), -3)
        jobs = self._add_rows_in_one_save_2144(
            [self._row_2144(self.volunteer, earlier), self._row_2144(self.volunteer)]
        )
        self.assertEqual(len(jobs), 2)
        ids = [j["job_id"] for j in jobs]
        self.assertEqual(len(set(ids)), 2, ids)
