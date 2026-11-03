"""Payment reminder outcomes: sent / skipped / failed (#2015, #2006, #2008).

Every "sent" assertion reads the mail handed to frappe.sendmail (the harness captures
it; EnhancedTestCase writes no Email Queue row), never ``result.success``. A skipped or
failed reminder must leave no queued mail, no reminder log comment, and must be
reported as such (never counted as sent) by the member helper and by both bulk
loops.
"""

from unittest.mock import patch

import frappe

from verenigingen.api.payment_processing import (
    execute_bulk_payment_action,
    send_chapter_notification,
    send_overdue_payment_reminders,
    send_payment_reminder_email,
)
from verenigingen.setup.notification_registry_setup import ensure_notification_registry_rows
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.reminder_mail_state import clear_email_cooldowns
from verenigingen.tests.utils.stock_email_templates import _cleanup_stock_email_templates, _load_fixture_rows

NEW_TEMPLATES = [
    "payment_reminder_final",
    "payment_reminder_bulk",
    "payment_failure_generic",
    "Payment Failure Notification",
]
KEYS = ["payment_reminder_friendly", "payment_reminder_urgent", "payment_failure"]
LOG_MARKER = "Payment reminder sent"
FINAL_MARKER = "Final Payment Notice"
BULK_MARKER = "You have outstanding membership payments"
CHAPTER_MARKER = "Overdue Member Payment"


class TestPaymentReminderOutcomes(EnhancedTestCase):
    @classmethod
    def tearDownClass(cls):
        _cleanup_stock_email_templates(NEW_TEMPLATES + ["payment_reminder_friendly", "payment_reminder_urgent"])
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self._ensure_outgoing_account()
        ensure_notification_registry_rows()
        self._ensure_shipped_templates()
        self._configure_email_master(master=1, respect_prefs=1)
        for key in KEYS:
            self._set_key(key, enabled=1, cooldown=0)

        self.member = self._new_reminder_member("Outcome")
        self.info = {
            "total_overdue": 125.0,
            "overdue_count": 2,
            "days_overdue": 31,
            "membership_type": "Regular",
        }
        clear_email_cooldowns()

    # ---- helpers -------------------------------------------------------

    def _new_reminder_member(self, first):
        return self.create_test_member(
            first_name=first,
            last_name=frappe.generate_hash(length=6),
            email=f"{first.lower()}.{frappe.generate_hash(length=8)}@example.com",
        )

    def _ensure_outgoing_account(self):
        if frappe.db.exists("Email Account", {"enable_outgoing": 1, "default_outgoing": 1}):
            return
        account = frappe.get_doc(
            {
                "doctype": "Email Account",
                "email_account_name": "Test Outgoing",
                "email_id": "test-outgoing@example.com",
                "enable_outgoing": 1,
                "default_outgoing": 1,
                "smtp_server": "localhost",
                "smtp_port": 25,
                "login_id_is_different": 0,
            }
        )
        account.flags.ignore_validate = True
        account.flags.ignore_mandatory = True
        account.insert()

    def _ensure_shipped_templates(self):
        """CI sites install the fixture; a site that predates it gets the shipped rows here."""
        fixture = _load_fixture_rows()
        for name in NEW_TEMPLATES + ["payment_reminder_friendly", "payment_reminder_urgent"]:
            if name in fixture and not frappe.db.exists("Email Template", name):
                row = {k: v for k, v in fixture[name].items() if k != "modified"}
                doc = frappe.get_doc(row)
                doc.flags.ignore_links = True
                doc.insert()

    def _configure_email_master(self, master=1, respect_prefs=1):
        config = frappe.get_single("Verenigingen Email Configuration")
        config.master_email_enabled = master
        config.respect_user_preferences = respect_prefs
        config.save()

    def _set_key(self, key, enabled, cooldown):
        config = frappe.get_single("Verenigingen Email Configuration")
        row = next(nt for nt in config.notification_types if nt.notification_key == key)
        row.enabled = enabled
        row.cooldown_minutes = cooldown
        config.save()

    def _mail_for(self, member, marker=None):
        """Mails handed to frappe.sendmail for this member.

        EnhancedTestCase replaces frappe.sendmail with a capture (no Email Queue row is
        written under the harness), so the captured call is the observable "queued" mail.
        """
        rows = [
            frappe._dict(message=e["kwargs"].get("message") or "", recipients=e["kwargs"].get("recipients"))
            for e in self.captured_emails
            if e["kwargs"].get("reference_name") == member.name
        ]
        if marker:
            rows = [r for r in rows if marker in r.message]
        return rows

    def _logs(self, member):
        return frappe.get_all(
            "Comment",
            filters={
                "reference_doctype": "Member",
                "reference_name": member.name,
                "content": ["like", f"%{LOG_MARKER}%"],
            },
        )

    def _send_reminder(self, member, reminder_type):
        return send_payment_reminder_email(
            member_name=member.name, reminder_type=reminder_type, payment_info=self.info
        )

    def _assert_nothing_went_out(self, member):
        self.assertEqual(self._mail_for(member), [], "no mail may be queued")
        self.assertEqual(self._logs(member), [], "no reminder log comment may exist")

    # ---- #2008: templates exist, the keyed path is taken ----------------

    def test_final_notice_goes_through_the_shipped_template(self):
        outcome = self._send_reminder(self.member, "Final Notice")
        rows = self._mail_for(self.member, FINAL_MARKER)
        self.assertEqual(len(rows), 1, "Final Notice must render the shipped template body")
        self.assertIn("31 days", rows[0].message)
        self.assertEqual(outcome.status, "sent")
        self.assertEqual(len(self._logs(self.member)), 1)

    def test_bulk_reminder_goes_through_the_shipped_template(self):
        outcome = self._send_reminder(self.member, "Bulk Reminder")
        self.assertEqual(len(self._mail_for(self.member, BULK_MARKER)), 1)
        self.assertEqual(outcome.status, "sent")

    def test_disabled_urgent_key_silences_final_notice(self):
        self._set_key("payment_reminder_urgent", enabled=0, cooldown=0)
        outcome = self._send_reminder(self.member, "Final Notice")
        self._assert_nothing_went_out(self.member)
        self.assertEqual(outcome.status, "skipped")
        self.assertIn("payment_reminder_urgent", outcome.reason)

    def test_disabled_friendly_key_silences_bulk_reminder(self):
        self._set_key("payment_reminder_friendly", enabled=0, cooldown=0)
        outcome = self._send_reminder(self.member, "Bulk Reminder")
        self._assert_nothing_went_out(self.member)
        self.assertEqual(outcome.status, "skipped")

    def test_fallback_path_honours_disabled_key(self):
        # Template removed -> TEMPLATE_NOT_FOUND -> HTML fallback. It must still obey the key.
        frappe.delete_doc("Email Template", "payment_reminder_final", force=True)
        self._set_key("payment_reminder_urgent", enabled=0, cooldown=0)
        outcome = self._send_reminder(self.member, "Final Notice")
        self._assert_nothing_went_out(self.member)
        self.assertEqual(outcome.status, "skipped")

    def test_fallback_path_honours_cooldown(self):
        frappe.delete_doc("Email Template", "payment_reminder_final", force=True)
        self._set_key("payment_reminder_urgent", enabled=1, cooldown=1440)
        first = self._send_reminder(self.member, "Final Notice")
        second = self._send_reminder(self.member, "Final Notice")
        self.assertEqual(len(self._mail_for(self.member)), 1, "fallback must record and honour the cooldown")
        self.assertEqual(first.status, "sent")
        self.assertEqual(second.status, "skipped")
        self.assertEqual(len(self._logs(self.member)), 1)

    def test_fallback_path_honours_opt_out(self):
        frappe.delete_doc("Email Template", "payment_reminder_final", force=True)
        self._unsubscribe(self.member)
        outcome = self._send_reminder(self.member, "Final Notice")
        self._assert_nothing_went_out(self.member)
        self.assertEqual(outcome.status, "skipped")

    def _unsubscribe(self, member):
        frappe.get_doc(
            {"doctype": "Email Unsubscribe", "email": member.email, "global_unsubscribe": 1}
        ).insert()

    # ---- #2015: outcomes ------------------------------------------------

    def test_cooldown_skip_is_not_logged_or_reported_as_sent(self):
        self._set_key("payment_reminder_friendly", enabled=1, cooldown=1440)
        first = self._send_reminder(self.member, "Friendly Reminder")
        second = self._send_reminder(self.member, "Friendly Reminder")
        self.assertEqual(len(self._mail_for(self.member)), 1)
        self.assertEqual(len(self._logs(self.member)), 1, "a skipped reminder must not be logged as sent")
        self.assertEqual(first.status, "sent")
        self.assertEqual(second.status, "skipped")
        self.assertIn("cooldown", second.reason.lower())
        self.assertFalse(second)

    def test_opted_out_member_is_skipped(self):
        self._unsubscribe(self.member)
        outcome = self._send_reminder(self.member, "Friendly Reminder")
        self._assert_nothing_went_out(self.member)
        self.assertEqual(outcome.status, "skipped")
        self.assertIn("opted out", outcome.reason.lower())

    def test_missing_outgoing_account_is_failed_not_sent(self):
        # Mock justified: infrastructure absence (no outgoing Email Account), as in CI-less sites.
        with patch(
            "verenigingen.services.communication.email_service.EmailService._has_active_email_account",
            return_value=False,
        ):
            outcome = self._send_reminder(self.member, "Friendly Reminder")
        self._assert_nothing_went_out(self.member)
        self.assertEqual(outcome.status, "failed")
        self.assertFalse(outcome)

    def test_member_without_email_is_failed(self):
        frappe.db.set_value("Member", self.member.name, "email", "")
        outcome = self._send_reminder(self.member, "Friendly Reminder")
        self.assertEqual(outcome.status, "failed")
        self.assertFalse(outcome)

    # ---- bulk loops -----------------------------------------------------

    def _bulk_rows(self):
        """one fresh member, one already in cooldown, one with no email"""
        self._set_key("payment_reminder_friendly", enabled=1, cooldown=1440)
        fresh = self._new_reminder_member("Fresh")
        cooled = self._new_reminder_member("Cooled")
        no_email = self._new_reminder_member("Noemail")
        self.assertEqual(self._send_reminder(cooled, "Friendly Reminder").status, "sent")
        frappe.db.set_value("Member", no_email.name, "email", "")
        rows = [{"member_name": m.name, **self.info} for m in (fresh, cooled, no_email)]
        return fresh, cooled, no_email, rows

    GET_DATA = "verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.get_data"

    def test_overdue_run_counts_only_real_sends(self):
        fresh, cooled, no_email, rows = self._bulk_rows()
        # Mock justified: the report's data source is imported locally per call; fixes the member set.
        with patch(self.GET_DATA, return_value=rows):
            result = send_overdue_payment_reminders(reminder_type="Friendly Reminder")
        self.assertEqual(len(self._mail_for(fresh)), 1)
        self.assertEqual(len(self._mail_for(cooled)), 1, "the cooled member keeps only its first mail")
        self.assertEqual(result.get("count"), 1, result)
        self.assertEqual(result.get("skipped"), 1, result)
        self.assertEqual(result.get("failed"), 1, result)
        self.assertIn("1 skipped", result.get("message"))

    def test_bulk_action_counts_only_real_sends(self):
        fresh, cooled, no_email, rows = self._bulk_rows()
        with patch(self.GET_DATA, return_value=rows):
            result = execute_bulk_payment_action(action="Send Payment Reminders")
        self.assertEqual(len(self._mail_for(fresh)), 1)
        self.assertEqual(len(self._mail_for(cooled)), 1)
        self.assertEqual(result.get("count"), 1, result)
        self.assertEqual(result.get("skipped"), 1, result)
        self.assertEqual(result.get("failed"), 1, result)

    # ---- #2006: chapter board mail --------------------------------------

    def _make_reminder_chapter(self):
        chapter = self.create_chapter()
        return frappe.get_doc("Chapter", chapter.name if hasattr(chapter, "name") else chapter)

    def _board_patch(self, email):
        # Mock justified: board resolution (volunteer linkage) is not under test; the send is.
        return patch(
            "verenigingen.verenigingen.doctype.chapter.chapter.Chapter.get_board_member_emails",
            return_value=[email],
        )

    def test_chapter_board_mail_is_queued_with_the_shipped_template(self):
        chapter = self._make_reminder_chapter()
        board_email = f"board.{frappe.generate_hash(length=8)}@example.com"
        with self._board_patch(board_email):
            outcome = send_chapter_notification(chapter.name, self.member.name, self.info)
        rows = self._mail_for(self.member, CHAPTER_MARKER)
        self.assertEqual(len(rows), 1, "the board mail must be queued from the shipped template")
        self.assertEqual(outcome.status, "sent")

    def test_chapter_mail_failure_is_reported_not_counted(self):
        chapter = self._make_reminder_chapter()
        frappe.delete_doc("Email Template", "Payment Failure Notification", force=True)
        board_email = f"board.{frappe.generate_hash(length=8)}@example.com"
        with self._board_patch(board_email), patch(
            self.GET_DATA, return_value=[{"member_name": self.member.name, "chapter": chapter.name, **self.info}]
        ):
            result = send_overdue_payment_reminders(send_to_chapters=True)
        self.assertEqual(self._mail_for(self.member, CHAPTER_MARKER), [])
        self.assertEqual(result.get("count"), 1, "the member reminder itself was sent")
        chapter_counts = result.get("chapter_notifications")
        self.assertEqual(chapter_counts, {"sent": 0, "skipped": 0, "failed": 1}, result)

    # ---- fixtures -------------------------------------------------------

    def test_shipped_templates_render_a_body(self):
        context = {
            "member": self.member,
            "chapter": frappe._dict(name="Test Chapter"),
            "payment_info": self.info,
            "total_overdue": "125", "days_overdue": 31, "overdue_count": 2,
            "failure_count": 1, "payment_status": "failed", "amount": 25, "next_payment_date": "2026-12-01",
            "base_url": "https://example.org",
        }
        fixture = _load_fixture_rows()
        for name in NEW_TEMPLATES:
            row = fixture[name]
            self.assertEqual(row["use_html"], 1, name)
            self.assertTrue(row["response_html"], f"{name}: body must be in response_html")
            body = frappe.render_template(row["response_html"], context)
            expected = "Test Chapter" if name == "Payment Failure Notification" else self.member.first_name
            self.assertIn(expected, body, name)
            self.assertGreater(len(body.strip()), 200, name)
