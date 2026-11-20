"""#2735: a rolled-back status change must not burn the member's status-mail cooldown.

``Member.on_update`` mailed the member synchronously. EmailService sets the Redis cooldown key
right after queueing the mail; the Email Queue row rolls back with the savepoint but the Redis key
does not, so the later genuine suspension was suppressed as "in cooldown". The send now runs in an
after-commit job that re-checks the member still holds the new status (#2144's shape).

Real Member saves in a real savepoint. The boundary is ``frappe.sendmail`` (recorded). CI has no RQ
workers, so ``frappe.enqueue`` is wrapped to capture the job for this module's method and the job is
run by hand with the kwargs a worker would receive. Probe shortcut: the member is moved back to
Active with ``db.set_value`` between two suspensions (a real reactivation would send its own mail).
"""

from contextlib import contextmanager
from unittest.mock import patch

import frappe

from verenigingen.services.communication.email_service import EmailService
from verenigingen.tests.fixtures.singleton_backup import singleton_backup
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.utils.reminder_mail_state import clear_email_cooldowns, ensure_outgoing_email_account

JOB = (
    "verenigingen.services.member.lifecycle.member_status_notification_service."
    "send_status_change_notification_job"
)
CONFIG = "Verenigingen Email Configuration"
SUSPENDED_SUBJECT = "Membership Suspended"
# Active -> <status> for each key the notification service can pick (#2735 class sweep).
KEYS_BY_TARGET_STATUS = {
    "Suspended": "member_suspended",
    "Quit": "member_terminated",
    "Expired": "member_status_change",
}
FLAGS = ("in_import", "in_bulk_import", "bulk_member_operations", "in_test")


class TestMemberStatusMailCooldownRollback2735(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self._saved_flags_2735 = {k: getattr(frappe.flags, k, None) for k in FLAGS}
        # Harness sets in_test=True (Member.on_update then skips event emission); production has neither.
        for flag in FLAGS:
            setattr(frappe.flags, flag, False)
        ensure_outgoing_email_account(self)
        clear_email_cooldowns()
        self.addCleanup(clear_email_cooldowns)
        self._backup_2735 = singleton_backup(CONFIG)
        self._backup_2735.__enter__()
        self._enable_suspended_key_with_cooldown_2735()
        self.member = self.create_test_member(
            first_name="Cooldown",
            last_name="Rollback",
            email=f"cooldown.rollback.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )

    def tearDown(self):
        # Flags first: super().tearDown() drains with them in place (lesson from #2019).
        for flag, value in self._saved_flags_2735.items():
            setattr(frappe.flags, flag, value)
        self._backup_2735.__exit__(None, None, None)
        super().tearDown()

    def _enable_suspended_key_with_cooldown_2735(self):
        config = frappe.get_single(CONFIG)
        for key in KEYS_BY_TARGET_STATUS.values():
            row = next((r for r in config.notification_types if r.notification_key == key), None)
            if row is None:
                row = config.append("notification_types", {"notification_key": key})
            row.enabled = 1
            row.cooldown_minutes = 60
        config.save()

    @contextmanager
    def _boundary_2735(self):
        """Record ``frappe.sendmail`` and capture this module's job instead of enqueueing it."""
        jobs, real_enqueue = [], frappe.enqueue

        def capturing_enqueue(*args, **kwargs):
            if kwargs.get("method") == JOB:
                jobs.append(kwargs)
                return None
            return real_enqueue(*args, **kwargs)

        with patch("frappe.sendmail") as sendmail, patch("frappe.enqueue", capturing_enqueue):
            self.sendmail, self.jobs = sendmail, jobs
            yield

    def _run_jobs_2735(self, jobs):
        for job in jobs:
            frappe.call(job["method"], **{k: v for k, v in job.items() if k in ("member_name", "old_status", "new_status")})

    def _suspend_2735(self, status="Suspended"):
        member = frappe.get_doc("Member", self.member.name)
        member.status = status
        member.save()

    def _suspend_and_roll_back_2735(self):
        savepoint = f"t2735_{frappe.generate_hash(length=8)}"
        frappe.db.savepoint(savepoint)
        self._suspend_2735()
        frappe.db.rollback(save_point=savepoint)

    def _reactivate_2735(self):
        frappe.db.set_value("Member", self.member.name, "status", "Active")

    def _cooldown_key_2735(self, notification_key="member_suspended"):
        recipient = EmailService._cooldown_id(self.member.email)
        return self._config_service()._get_cooldown_cache_key(notification_key, recipient)

    def _config_service(self):
        from verenigingen.services.communication.email_configuration_service import (
            get_email_configuration_service,
        )

        return get_email_configuration_service()

    def _key_is_set_2735(self, notification_key="member_suspended"):
        return bool(frappe.cache().get_value(self._cooldown_key_2735(notification_key)))

    def _suspension_mails_2735(self):
        return [c for c in self.sendmail.call_args_list if c.kwargs.get("subject") == SUSPENDED_SUBJECT]

    def test_rolled_back_suspension_leaves_no_key_and_no_mail(self):
        with self._boundary_2735():
            self._suspend_and_roll_back_2735()
            self.assertEqual(frappe.db.get_value("Member", self.member.name, "status"), "Active")
            self._run_jobs_2735(self.jobs)
            self.assertFalse(self._key_is_set_2735(), "the rolled-back change burned the cooldown")
            self.assertEqual(self._suspension_mails_2735(), [])

    def test_genuine_suspension_after_a_rolled_back_one_sends_exactly_one_mail(self):
        with self._boundary_2735():
            self._suspend_and_roll_back_2735()
            self._run_jobs_2735(self.jobs)
            del self.jobs[:]
            # A mock does not roll back: count only the mails the genuine suspension itself sends.
            before = len(self._suspension_mails_2735())
            self._suspend_2735()
            self._run_jobs_2735(self.jobs)
            self.assertEqual(len(self._suspension_mails_2735()) - before, 1)

    def test_committed_suspension_sends_one_mail_and_sets_the_key(self):
        with self._boundary_2735():
            self._suspend_2735()
            self._run_jobs_2735(self.jobs)
            mails = self._suspension_mails_2735()
            self.assertEqual(len(mails), 1)
            self.assertEqual(mails[0].kwargs["recipients"], [self.member.email])
            self.assertTrue(self._key_is_set_2735())

    def test_second_suspension_inside_the_window_is_still_suppressed(self):
        """Control: the cooldown still works for two real, committed suspensions."""
        with self._boundary_2735():
            self._suspend_2735()
            self._run_jobs_2735(self.jobs)
            self._reactivate_2735()
            del self.jobs[:]
            self._suspend_2735()
            self.assertTrue(self.jobs, "control: the second suspension did queue its own job")
            self._run_jobs_2735(self.jobs)
            self.assertEqual(len(self._suspension_mails_2735()), 1)

    def test_every_status_key_leaves_no_cooldown_when_rolled_back_and_sets_it_when_committed(self):
        """Class sweep: member_terminated and member_status_change share the path."""
        for status, key in KEYS_BY_TARGET_STATUS.items():
            with self.subTest(status=status, key=key), self._boundary_2735():
                savepoint = f"t2735_{frappe.generate_hash(length=8)}"
                frappe.db.savepoint(savepoint)
                self._suspend_2735(status)
                frappe.db.rollback(save_point=savepoint)
                self._run_jobs_2735(self.jobs)
                self.assertFalse(self._key_is_set_2735(key), "rolled back: key burned")
                del self.jobs[:]
                self._suspend_2735(status)
                self._run_jobs_2735(self.jobs)
                self.assertTrue(self._key_is_set_2735(key), "control: a committed change sets the key")
                self._reactivate_2735()
