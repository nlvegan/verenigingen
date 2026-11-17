"""send_payment_link must not tell the user a skipped or failed mail was sent (#2178).

EmailService reports a disabled key as success=True with ``skip_reason`` and a missing outgoing
account as success=False. Each test drives the real EmailService (no stubbed result): a control
run with the key enabled queues a mail and shows the green "sent" message; the same call with the
key disabled, or with no usable outgoing account, queues nothing and must not show it.

Probe shortcut, stated: the link is only inserted (never submitted), so no Ponto API is involved;
``redirect_link`` is set directly so ``get_payment_url`` is not needed.
"""

from unittest.mock import patch

import frappe

from verenigingen.setup.notification_registry_setup import ensure_notification_registry_rows
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.utils.notification_state import own_notification_keys, queued_mail_count
from verenigingen.tests.utils.reminder_mail_state import (
    clear_email_cooldowns,
    configure_notification_key,
    ensure_outgoing_email_account,
)
from verenigingen.tests.utils.stock_email_templates import ensure_stock_email_template

PONTO_LINK_KEY = "ponto_payment_link_request"
PONTO_LINK_NO_ACCOUNT = (
    "verenigingen.services.communication.email_service.EmailService._has_active_email_account"
)
PONTO_LINK_RECIPIENT = "pontolinkresult@example.com"


class TestPontoPaymentLinkMailResult(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        ensure_outgoing_email_account(self)
        ensure_notification_registry_rows()
        ensure_stock_email_template("payment_notification")
        clear_email_cooldowns()
        self.addCleanup(clear_email_cooldowns)
        own_notification_keys(self, PONTO_LINK_KEY)

    def _ponto_link_doc(self):
        link = frappe.new_doc("Ponto Payment Link")
        link.payment_type = "One-Time"
        link.amount = 25.0
        link.currency = "EUR"
        link.description = "Mail result"
        link.creditor_name = "Test Association"
        link.creditor_iban = "NL91ABNA0417164300"
        link.insert()
        link.redirect_link = "https://myponto.example/authorize/abc"
        return link

    def _ponto_link_messages(self, link):
        before = len(frappe.local.message_log)
        link.send_payment_link(email=PONTO_LINK_RECIPIENT)
        return [str(m) for m in frappe.local.message_log[before:]]

    def _ponto_link_refusal(self, link):
        """The user-facing refusal text; it must not be the green "sent" message."""
        before = len(frappe.local.message_log)
        with self.assertRaises(frappe.ValidationError) as cm:
            link.send_payment_link(email=PONTO_LINK_RECIPIENT)
        logged = [str(m) for m in frappe.local.message_log[before:]]
        self.assertFalse(any("Payment link sent to" in m for m in logged), logged)
        return str(cm.exception)

    def test_queued_mail_is_reported_sent(self):
        link = self._ponto_link_doc()
        before = queued_mail_count(PONTO_LINK_RECIPIENT)
        messages = self._ponto_link_messages(link)
        self.assertEqual(queued_mail_count(PONTO_LINK_RECIPIENT), before + 1, "control: mail must go out")
        self.assertTrue(any("Payment link sent to" in m for m in messages), messages)

    def test_skipped_mail_is_not_reported_sent(self):
        link = self._ponto_link_doc()
        configure_notification_key(PONTO_LINK_KEY, 0, 0)
        before = queued_mail_count(PONTO_LINK_RECIPIENT)
        refusal = self._ponto_link_refusal(link)
        self.assertEqual(queued_mail_count(PONTO_LINK_RECIPIENT), before)
        self.assertIn("not sent", refusal)

    def test_failed_mail_is_not_reported_sent(self):
        link = self._ponto_link_doc()
        # Mock justified: infrastructure absence (no usable outgoing Email Account).
        with patch(PONTO_LINK_NO_ACCOUNT, return_value=False):
            refusal = self._ponto_link_refusal(link)
        self.assertIn("not sent", refusal)
