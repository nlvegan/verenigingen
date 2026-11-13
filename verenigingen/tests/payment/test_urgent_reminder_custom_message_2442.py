"""#2442: the message staff type for an Urgent Notice reaches the mail on the stock-template path.

The shipped `payment_reminder_urgent` template had no `custom_message` block, so the text was dropped
(the friendly/final/bulk templates and the fallback HTML printed it). Driven through the REAL endpoint
(`send_overdue_payment_reminders`, decorator included) and the real sender; only the overdue report query
is patched (its rows are the endpoint's input). The DB row is first reset to the shipped fixture, as a
migrate's fixture sync does on an existing site (Frappe re-imports fixtures/*.json on every migrate).

Run:
    bench --site test_site_6 run-tests --app verenigingen --module verenigingen.tests.payment.test_urgent_reminder_custom_message_2442
"""

import html
import json
import re
from pathlib import Path
from unittest.mock import patch

import frappe

from verenigingen.api.payment_processing import send_overdue_payment_reminders
from verenigingen.tests.test_mail_body_escaping_2307 import MailBodyEscapingBase
from verenigingen.tests.utils.stock_email_templates import _cleanup_stock_email_templates

MESSAGE = "Call the office today & don't <i>ignore</i> this"
ESCAPED_ONCE = "Call the office today &amp; don't &lt;i&gt;ignore&lt;/i&gt; this"
REPORT = "verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.get_data"
# Every shipped reminder template a staff-typed message can be sent through.
REMINDERS = {
    "Friendly Reminder": "payment_reminder_friendly",
    "Urgent Notice": "payment_reminder_urgent",
    "Final Notice": "payment_reminder_final",
    "Bulk Reminder": "payment_reminder_bulk",
}
# send_payment_reminder_email's notification_key_map
NOTIFICATION_KEY = {
    "Friendly Reminder": "payment_reminder_friendly",
    "Urgent Notice": "payment_reminder_urgent",
    "Final Notice": "payment_reminder_urgent",
    "Bulk Reminder": "payment_reminder_friendly",
}


class TestUrgentReminderCustomMessage(MailBodyEscapingBase):
    def _send(self, reminder_type):
        template = REMINDERS[reminder_type]
        _cleanup_stock_email_templates([template])
        self.addCleanup(_cleanup_stock_email_templates, [template])
        slug = reminder_type.split()[0].lower()
        email_addr = f"msg-2442-{slug}-{self.token}@example.org"
        member = self.create_test_member(
            first_name="Msg", last_name=f"Msg{slug}{self.token}", email=email_addr, birth_date="1990-01-01"
        )
        # the notification key the sender uses for this reminder type (Final/Urgent share one)
        self.key(NOTIFICATION_KEY[reminder_type], "Document-Field")
        row = {
            "member_name": member.name,
            "overdue_count": 1,
            "total_overdue": 10,
            "days_overdue": 3,
            "membership_type": "Regular",
        }
        with patch(REPORT, return_value=[row]):
            result = send_overdue_payment_reminders(
                reminder_type=reminder_type, include_payment_link=False, custom_message=MESSAGE
            )
        self.assertEqual(result.get("count"), 1, f"one reminder must really be sent: {result}")
        return self.html_to(email_addr)

    def _assert_message_once(self, body):
        self.assertIn(ESCAPED_ONCE, body)
        self.assertNotIn("&amp;amp;", body)
        self.assertNotIn("<i>ignore", body, "markup typed by staff must stay inert")
        self.assertIn(MESSAGE, html.unescape(body))

    def test_urgent_notice_prints_the_typed_message_escaped_once(self):
        self._assert_message_once(self._send("Urgent Notice"))

    def test_every_reminder_type_prints_the_typed_message(self):
        """Class sweep: no reminder template may drop the message its sender passes."""
        for reminder_type in REMINDERS:
            with self.subTest(reminder_type):
                self._assert_message_once(self._send(reminder_type))

    def test_urgent_fixture_guards_and_escapes_the_message(self):
        """The block is conditional (no message, no empty box) and escaped, like its siblings."""
        template = "payment_reminder_urgent"
        path = Path(frappe.get_app_path("verenigingen", "fixtures", "email_template.json"))
        fixture = json.loads(path.read_text())
        body = next(t for t in fixture if t["name"] == template)["response_html"]
        guarded = (
            r"\{%\s*if custom_message\s*%\}[\s\S]*\{\{\s*custom_message\s*\|\s*e\s*\}\}"
            r"[\s\S]*\{%\s*endif\s*%\}"
        )
        self.assertRegex(body, guarded)
        self.assertIsNone(re.search(r"\{\{\s*custom_message\s*\}\}", body))
