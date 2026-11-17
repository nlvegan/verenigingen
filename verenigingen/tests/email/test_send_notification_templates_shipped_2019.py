"""#2019: every template the deprecated ``EmailService.send_notification`` map names is shipped.

Four map entries named Email Templates no fixture ships (``Member Suspension Notification``,
``Member Termination Notification``, ``SEPA Mandate Created``, ``Board Member Added``). Two had
no caller; the other two were reached on every Suspended / Quit transition through
``handle_lifecycle_notifications``, where the send failed with TEMPLATE_NOT_FOUND and the failure
went to a bare ``frappe.logger().warning`` (dropped). The same transition is already mailed by
``MemberStatusNotificationService`` through the shipped ``member_lifecycle_notification``.
"""

import ast
import json
import os
from unittest.mock import patch

import frappe

from verenigingen.events.subscribers import member_subscribers
from verenigingen.services.communication import email_service as email_service_module
from verenigingen.services.communication.email_service import EmailService
from verenigingen.utils.operation_result import OperationResult
from verenigingen.services.member.lifecycle.member_status_notification_service import (
    MemberStatusNotificationService,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.notification_state import own_notification_keys
from verenigingen.tests.utils.reminder_mail_state import ensure_outgoing_email_account

APP_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURE = os.path.join(APP_ROOT, "fixtures", "email_template.json")


def _shipped_template_names():
    with open(FIXTURE, encoding="utf-8") as f:
        return {row["name"] for row in json.load(f)}


def _template_mapping_values(source):
    """String values of the ``template_mapping`` dict literal in ``source``."""
    values = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "template_mapping" for t in node.targets
        ):
            values += [v.value for v in node.value.values if isinstance(v, ast.Constant)]
    return values


class TestSendNotificationMapNamesShippedTemplates(EnhancedTestCase):
    def test_every_mapped_template_is_a_fixture_row(self):
        with open(email_service_module.__file__, encoding="utf-8") as f:
            mapped = _template_mapping_values(f.read())
        shipped = _shipped_template_names()
        self.assertIn("membership_application_approved", mapped, "control: the scan reads the real map")
        self.assertEqual(
            [name for name in mapped if name not in shipped],
            [],
            "send_notification maps these types to Email Templates no fixture ships",
        )

    def test_the_scan_flags_a_name_the_fixture_does_not_ship(self):
        planted = "def f():\n    template_mapping = {'a': 'membership_application_approved', 'b': 'Nope 2019'}\n"
        shipped = _shipped_template_names()
        self.assertEqual(
            [n for n in _template_mapping_values(planted) if n not in shipped], ["Nope 2019"]
        )


class TestSuspendedAndQuitAreMailedThroughAShippedTemplate(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        ensure_outgoing_email_account(self)
        self.member = self.create_test_member(
            first_name="Lifecycle2019",
            last_name="Member",
            email=f"lifecycle2019.{frappe.generate_hash(length=6)}@example.invalid",
        )

    def _spy_templates(self):
        """Record (template, result) of every real send_templated_email call."""
        calls = []
        original = EmailService.send_templated_email

        def spy(service, template_name, *args, **kwargs):
            result = original(service, template_name, *args, **kwargs)
            calls.append((template_name, result))
            return result

        patcher = patch.object(EmailService, "send_templated_email", spy)
        patcher.start()
        self.addCleanup(patcher.stop)
        return calls

    def test_lifecycle_handler_attempts_no_unshipped_template(self):
        calls = self._spy_templates()
        shipped = _shipped_template_names()
        guard_verdicts = []
        original_guard = member_subscribers._member_state_still_holds

        def recording_guard(*args, **kwargs):
            guard_verdicts.append(original_guard(*args, **kwargs))
            return guard_verdicts[-1]

        with patch.object(member_subscribers, "_member_state_still_holds", recording_guard):
            for new_status in ("Suspended", "Quit"):
                # Probe shortcut: db_set stands in for the status save, because the handler drops
                # a job whose status is no longer the member's (#2144).
                self.member.db_set("status", new_status, update_modified=False)
                self.member.reload()
                member_subscribers.handle_lifecycle_notifications(
                    "member_lifecycle_changed",
                    {"member": self.member.name, "old_status": "Active", "new_status": new_status},
                )
        self.assertEqual(guard_verdicts, [True, True], "control: the handler got past the stale-job guard")
        self.assertEqual([name for name, _ in calls if name not in shipped], [])

    def test_status_service_mails_suspended_and_quit_with_a_shipped_template(self):
        own_notification_keys(self, "member_suspended", "member_terminated")
        calls = self._spy_templates()
        shipped = _shipped_template_names()
        for new_status in ("Suspended", "Quit"):
            with patch("frappe.sendmail") as sendmail:  # external: SMTP delivery
                MemberStatusNotificationService().send_status_change_notification(
                    self.member, "Active", new_status
                )
            self.assertEqual(sendmail.call_count, 1, new_status)
        self.assertEqual(len(calls), 2)
        for name, result in calls:
            self.assertIn(name, shipped)
            self.assertTrue(result.success, result.errors)
            self.assertFalse((result.data or {}).get("skipped"), result.data)


class TestFailedStatusNotificationIsVisible(EnhancedTestCase):
    def test_a_failed_send_leaves_an_error_log_row(self):
        member = self.create_test_member(
            first_name="Visible2019", last_name="Member", email="visible2019@example.invalid"
        )
        failed = OperationResult.fail("boom 2019", errors=["TEMPLATE_NOT_FOUND 2019"])
        # real failure signal is injected: the unit under test is what the subscriber does with it
        with patch(
            "verenigingen.services.communication.compatibility.send_member_notification",
            return_value=failed,
        ):
            member_subscribers._send_member_status_notification(member, "approval")
        rows = frappe.get_all(
            "Error Log", filters={"error": ["like", f"%{member.name}%TEMPLATE_NOT_FOUND 2019%"]}, limit=1
        )
        self.assertTrue(rows, "a refused member status mail must reach the Error Log, not a dropped logger")
