"""#2425: the staff-typed custom_message of send_overdue_payment_reminders is HTML-escaped exactly ONCE.

The @critical_api wrapper already escapes every string argument, the endpoint ran `sanitize_text` on it
again, and the mail body escapes it a last time at render (stock templates `|e`, fallback `escape_html`).
An apostrophe or ampersand therefore reached the member as `&amp;#x27;` / `&amp;amp;`.

Driven through the REAL endpoint (decorator included) and the REAL senders; only the overdue report query
is patched (its rows are the endpoint's input, not the behaviour under test). Both mail paths are covered:
the stock Email Template and the fallback HTML used when the template is missing.

Run:
    bench --site test_site_5 run-tests --app verenigingen --module verenigingen.tests.test_payment_reminder_message_escaped_once_2425
"""

import html
import json
import re
from pathlib import Path
from unittest.mock import patch

import frappe

from verenigingen.api.payment_processing import send_overdue_payment_reminders
from verenigingen.tests.test_mail_body_escaping_2307 import MailBodyEscapingBase

MESSAGE = "Don't ignore this & pay <i>now</i>"
# The mail pipeline renders the apostrophe back as a plain character; `&` and `<` stay escaped, once.
ESCAPED_ONCE = "Don't ignore this &amp; pay &lt;i&gt;now&lt;/i&gt;"


class TestReminderMessageEscapedOnce(MailBodyEscapingBase):
    def _run(self, drop_template):
        email_addr = f"msg-2425-{self.token}@example.org"
        member = self.create_test_member(
            first_name="Msg", last_name=f"Msg{self.token}", email=email_addr, birth_date="1990-01-01"
        )
        self.key("payment_reminder_friendly", "Document-Field")
        template_exists = frappe.db.exists("Email Template", "payment_reminder_friendly")
        if drop_template and template_exists:
            frappe.delete_doc("Email Template", "payment_reminder_friendly", force=True)
        elif not drop_template:
            self.assertTrue(template_exists, "the stock template path needs the shipped template")
        row = {
            "member_name": member.name,
            "overdue_count": 1,
            "total_overdue": 10,
            "days_overdue": 3,
            "membership_type": "Regular",
        }
        target = "verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.get_data"
        with patch(target, return_value=[row]):
            result = send_overdue_payment_reminders(
                reminder_type="Friendly Reminder", include_payment_link=False, custom_message=MESSAGE
            )
        self.assertEqual(result.get("count"), 1, f"one reminder must really be sent: {result}")
        return self.html_to(email_addr)

    def _assert_once(self, body):
        self.assertIn(ESCAPED_ONCE, body)
        self.assertNotIn("&amp;#x27;", body)
        self.assertNotIn("&amp;amp;", body)
        self.assertNotIn("&amp;lt;", body)
        self.assertNotIn("<i>now", body, "markup typed by staff must stay inert")
        self.assertIn(MESSAGE, html.unescape(body), "the message must read back exactly")

    def test_stock_template_path(self):
        self._assert_once(self._run(drop_template=False))

    def test_fallback_html_path(self):
        self._assert_once(self._run(drop_template=True))


class TestShippedTemplatesEscapeCustomMessage(MailBodyEscapingBase):
    """custom_message is passed RAW, so every shipped template that prints it must escape it itself."""

    def test_every_fixture_printing_custom_message_pipes_it_through_e(self):
        fixture = Path(frappe.get_app_path("verenigingen", "fixtures", "email_template.json"))
        printed = 0
        for template in json.loads(fixture.read_text()):
            body = template.get("response_html") or template.get("response") or ""
            for expr in re.findall(r"\{\{(.*?)\}\}", body, flags=re.S):
                if "custom_message" in expr:
                    printed += 1
                    self.assertRegex(
                        expr, r"\|\s*e\b", f"{template['name']} prints custom_message without |e: {expr!r}"
                    )
        self.assertGreaterEqual(printed, 3, "control: the friendly, final and bulk templates print it")
