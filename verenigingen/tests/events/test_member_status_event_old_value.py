"""#2180: member status events must carry the status the member HAD, not the new one.

``Member.on_update`` runs after the row is written, so ``get_db_value`` already returned
the new value and every payload read ``old_status == new_status``. The saves here are real
``Member.save()`` calls with ``in_test`` off (production has it off); the queued subscriber
jobs are captured at ``frappe.enqueue`` and run by hand with the kwargs a worker receives.

Maintainer ruling (#2180, option 1): the event path does NOT enable/disable the member's
User (the suspension and termination services own that) and sends no reactivation mail
(``member_activated`` already covers it). Those consumers are deleted; the tests below
prove the real event path no longer does either.
"""

from unittest.mock import MagicMock, patch

import frappe

from verenigingen.events import member_events
from verenigingen.events.subscribers import member_subscribers
from verenigingen.tests.utils.base import VereningingenTestCase

MAIL_FACTORY = "verenigingen.services.communication.compatibility.get_email_service"
STATUS_MAIL = (
    "verenigingen.services.member.lifecycle.member_status_notification_service."
    "MemberStatusNotificationService._send_email"
)


class TestMemberStatusEventOldValue(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self._saved_flags = {
            k: getattr(frappe.flags, k, None)
            for k in (
                "in_import",
                "in_bulk_import",
                "bulk_member_operations",
                "in_test",
                "skip_volunteer_account_creation",
            )
        }
        # The harness sets in_import / in_test, which make events skip or subscribers
        # early-return. Production has neither.
        frappe.flags.in_import = False
        frappe.flags.in_bulk_import = False
        frappe.flags.bulk_member_operations = False
        frappe.flags.in_test = False
        frappe.flags.skip_volunteer_account_creation = True
        self._had_throttle = "throttle_user_limit" in frappe.local.conf
        self._throttle = frappe.local.conf.get("throttle_user_limit")
        self.addCleanup(self._restore_throttle)
        frappe.local.conf["throttle_user_limit"] = 1000000

        self.member = self.create_test_member(
            first_name="OldValue",
            last_name="Evt",
            email=f"oldvalue.evt.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        self.user = frappe.get_doc(
            {
                "doctype": "User",
                "email": f"oldvalue.user.{frappe.generate_hash(length=6)}@test.invalid",
                "first_name": "OldValue",
                "send_welcome_email": 0,
                "enabled": 1,
            }
        ).insert(ignore_permissions=True)
        self.track_doc("User", self.user.name)
        member = frappe.get_doc("Member", self.member.name)
        member.user = self.user.name
        member.save(ignore_permissions=True)

    def _restore_throttle(self):
        if self._had_throttle:
            frappe.local.conf["throttle_user_limit"] = self._throttle
        else:
            frappe.local.conf.pop("throttle_user_limit", None)

    def tearDown(self):
        for k, v in self._saved_flags.items():
            setattr(frappe.flags, k, v)
        super().tearDown()

    def _field(self, fieldname):
        return frappe.db.get_value("Member", self.member.name, fieldname)

    def _save(self, **values):
        member = frappe.get_doc("Member", self.member.name)
        member.update(values)
        member.save()

    def _capture(self, **values):
        """Real save; returns the subscriber jobs it queued (mail boundary stubbed out)."""
        jobs = []
        real_enqueue = frappe.enqueue

        def recording_enqueue(*args, **kwargs):
            if str(kwargs.get("method", "")).startswith("verenigingen.events.subscribers."):
                jobs.append(kwargs)
            # Mock justified: the boundary is the worker; jobs are run by hand below.

        frappe.enqueue = recording_enqueue
        try:
            with patch(STATUS_MAIL):
                self._save(**values)
        finally:
            frappe.enqueue = real_enqueue
        return jobs

    def _payload(self, jobs, event_name):
        payloads = [j["event_data"] for j in jobs if j["event_name"] == event_name]
        self.assertTrue(payloads, f"the save queued no {event_name} job: {jobs}")
        return payloads[0]

    def _run(self, jobs):
        for job in jobs:
            frappe.call(
                job["method"],
                **{k: v for k, v in job.items() if k in ("event_name", "event_data", "is_bulk_import")},
            )

    def test_membership_status_event_carries_the_previous_status(self):
        before = self._field("status")
        self.assertEqual(before, "Active", "precondition")
        payload = self._payload(self._capture(status="Suspended"), "member_lifecycle_changed")
        self.assertEqual(payload["new_status"], "Suspended")
        self.assertEqual(payload["old_status"], before)

    def test_application_status_event_carries_the_previous_status(self):
        before = self._field("application_status")
        new = "Approved" if before != "Approved" else "Rejected"
        payload = self._payload(self._capture(application_status=new), "member_status_changed")
        self.assertEqual(payload["new_status"], new)
        self.assertEqual(payload["old_status"], before)

    def test_status_mail_context_names_the_previous_status(self):
        sent = []
        with patch(STATUS_MAIL, side_effect=lambda **kw: sent.append(kw["context"])):
            self._save(status="Suspended")
        self.assertEqual(len(sent), 1, sent)
        self.assertEqual((sent[0]["old_status"], sent[0]["new_status"]), ("Active", "Suspended"))

    def test_suspension_through_the_event_path_leaves_the_user_enabled(self):
        """The user is disabled by the suspension/termination services, not by an event."""
        jobs = self._capture(status="Suspended")
        self.assertEqual(self._field("status"), "Suspended")
        with patch(MAIL_FACTORY, return_value=MagicMock()):
            self._run(jobs)
        self.assertEqual(frappe.db.get_value("User", self.user.name, "enabled"), 1)

    def test_reactivation_through_the_event_path_leaves_a_disabled_user_alone(self):
        self._save(status="Suspended")
        frappe.db.set_value("User", self.user.name, "enabled", 0)  # probe shortcut: staff disabled it
        jobs = self._capture(status="Active")
        with patch(MAIL_FACTORY, return_value=MagicMock()):
            self._run(jobs)
        self.assertEqual(frappe.db.get_value("User", self.user.name, "enabled"), 0)

    def test_reactivation_sends_no_event_driven_mail(self):
        """``member_activated`` (status notification service) already covers it."""
        self._save(status="Suspended")
        jobs = self._capture(status="Active")
        service = MagicMock(name="EmailService")
        with patch(MAIL_FACTORY, return_value=service):
            self._run(jobs)
        service.send_notification.assert_not_called()

    def test_control_suspension_still_mails_through_the_event_path(self):
        """Control: the lifecycle job still mails for Suspended (real row for the guard)."""
        jobs = self._capture(status="Suspended")
        service = MagicMock(name="EmailService")
        with patch(MAIL_FACTORY, return_value=service):
            self._run(jobs)
        service.send_notification.assert_called_once()

    def test_the_user_account_subscriber_is_gone(self):
        self.assertFalse(hasattr(member_subscribers, "handle_user_account_updates"))
        registered = member_events._get_member_event_subscribers("member_lifecycle_changed")
        self.assertFalse([s for s in registered if s.endswith("handle_user_account_updates")])
