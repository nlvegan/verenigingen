"""process_member_post_creation really queues the welcome mail (#2176).

It used to read ``System Settings.company`` (no such field), which raised inside the
welcome block, so nothing was ever built or queued. Every assertion reads the Email Queue
(what really went out), never the function's own log line.

Production reach: ``MemberPerformanceOptimizer.create_member_optimized`` enqueues this
function on the short queue; it is also whitelisted (Verenigingen Staff / System Manager
via its Critical Operation Rule).
"""

from unittest.mock import patch

import frappe

from verenigingen.setup.notification_registry_setup import ensure_notification_registry_rows
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.utils.reminder_mail_state import (
    clear_email_cooldowns,
    configure_notification_key,
    ensure_outgoing_email_account,
)
from verenigingen.utils.member_performance_optimizer import process_member_post_creation

KEY = "member_activated"


class TestPostCreationWelcomeMail2176(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        ensure_outgoing_email_account(self)
        ensure_notification_registry_rows()
        config = frappe.get_single("Verenigingen Email Configuration")
        config.master_email_enabled = 1
        config.save()
        configure_notification_key(KEY, 1, 0)
        clear_email_cooldowns()
        self.addCleanup(clear_email_cooldowns)
        self.member = self.create_test_member()
        self._before = self._queued()

    def _queued(self):
        return frappe.db.count("Email Queue Recipient", {"recipient": self.member.email})

    def _run(self):
        # Mock justified: execution-context probe of the log line (nothing else records it).
        with patch("verenigingen.utils.member_performance_optimizer.frappe.logger") as logger:
            process_member_post_creation(self.member.name)
        return [str(c.args[0]) for c in logger.return_value.info.call_args_list]

    def _welcome_errors(self):
        return frappe.db.count("Error Log", {"method": ["like", f"%Welcome email failed for {self.member.name}%"]})

    def test_welcome_mail_is_queued_with_key_enabled(self):
        errors_before = self._welcome_errors()
        lines = self._run()
        self.assertEqual(self._queued() - self._before, 1, "the welcome mail must really be queued")
        self.assertEqual(self._welcome_errors(), errors_before, "no 'Welcome email failed' Error Log")
        self.assertTrue(any("Welcome email sent" in line for line in lines))

    def test_welcome_mail_not_queued_and_not_claimed_sent_with_key_disabled(self):
        configure_notification_key(KEY, 0, 0)
        lines = self._run()
        self.assertEqual(self._queued() - self._before, 0, "a disabled key must queue nothing")
        self.assertFalse(
            any("Welcome email sent" in line for line in lines),
            "a skipped mail must not be logged as sent",
        )
