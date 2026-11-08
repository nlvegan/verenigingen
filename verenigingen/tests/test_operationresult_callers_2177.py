"""
Callers of EmailService must read its OperationResult as one, not as a dict (#2177).

``OperationResult`` has no ``get`` and no ``__getitem__``, and EmailService has no ``send_email``.
Three callers got that wrong, and each swallowed the crash, so an admin alert (or the test-email
button) reported failure while the mail was in fact queued, or never went out at all:

* ``ContributionAmendmentRequest.handle_mollie_sync_failure`` (``result.get("success")``)
* ``send_test_email`` (``result.get("success")`` / ``result.get("error")``)
* ``amendment_events.notify_administrators_of_sync_issue`` (``email_service.send_email(...)``)

Each is driven through its real code path against the REAL EmailService 
(nothing about EmailService is stubbed). The seams replaced are all BELOW it: ``frappe.sendmail``
(the harness captures it; the failure cases make it raise) and ``frappe.db.commit`` (the handlers
commit, which would make this setUp permanent).
A skip (master switch off, key disabled) must not be reported as sent (#2044, #2096).

Run:
    bench --site test_site_4 run-tests --app verenigingen --module verenigingen.tests.test_operationresult_callers_2177
"""

from unittest.mock import patch

import frappe

from verenigingen.setup.notification_registry_setup import DEFAULT_COOLDOWN_MINUTES
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.reminder_mail_state import (
    allow_reminder_sends,
    clear_email_cooldowns,
    ensure_outgoing_email_account,
)
from verenigingen.utils.constants import Roles

CONFIG = "Verenigingen Email Configuration"
SYNC_KEY = "contribution_amendment_sync_failed"
REQUEST_KEY = "contribution_sync_failed"
ROLES = [Roles.SYSTEM_MANAGER, Roles.VERENIGINGEN_ADMIN, Roles.FINANCIAL_MANAGER]


class TestOperationResultCallers2177(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        ensure_outgoing_email_account(self)
        allow_reminder_sends(keys=(SYNC_KEY, REQUEST_KEY))
        self.holder = f"holder-2177-{frappe.generate_hash(length=5)}@example.org"
        self.create_test_user(self.holder, roles=ROLES)

    # -- helpers -------------------------------------------------------------------------------

    def _amendment(self):
        token = frappe.generate_hash(length=8)
        member = self.create_test_member(
            first_name="Opr", last_name=f"T{token}", email=f"opr-{token}@example.com", birth_date="1990-01-01"
        )
        membership = self.create_test_membership(member_name=member.name)
        return frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": membership.name,
                "member": member.name,
                "amendment_type": "Fee Change",
                "requested_amount": 30.0,
                "reason": "operation result 2177",
                "status": "Applied",
            }
        ).insert()

    # The harness replaces frappe.sendmail (the boundary below EmailService) with a capture, so the
    # mail EmailService hands to it is read from captured_emails; EmailService itself is real.
    def _queued_recipients(self, reference_name):
        out = []
        for mail in self.captured_emails:
            if mail["kwargs"].get("reference_name") == reference_name:
                out.extend(mail["recipients"])
        return out

    def _queued_to(self, recipient):
        return any(recipient in mail["recipients"] for mail in self.captured_emails)

    def _disable(self, key=None, master=True):
        config = frappe.get_single(CONFIG)
        if master:
            config.master_email_enabled = 0
        for row in config.notification_types:
            if row.notification_key == key:
                row.enabled = 0
        config.save()

    def _log_lines(self, logger_mock):
        return " | ".join(str(c.args[0]) for c in logger_mock.return_value.info.call_args_list)

    # -- send_test_email -----------------------------------------------------------------------

    def test_test_email_button_reports_a_queued_mail_as_success(self):
        from verenigingen.verenigingen.doctype.verenigingen_email_configuration.verenigingen_email_configuration import (
            send_test_email,
        )

        target = f"test-2177-{frappe.generate_hash(length=5)}@example.org"
        result = send_test_email(target)
        self.assertTrue(self._queued_to(target), "the mail really was queued")
        self.assertTrue(result["success"], result)
        self.assertIn(target, result["message"])

    def test_test_email_button_does_not_call_a_skipped_mail_sent(self):
        from verenigingen.verenigingen.doctype.verenigingen_email_configuration.verenigingen_email_configuration import (
            send_test_email,
        )

        self._disable()  # master switch off: EmailService answers success + skipped
        target = f"test-2177-{frappe.generate_hash(length=5)}@example.org"
        result = send_test_email(target)
        self.assertFalse(self._queued_to(target))
        self.assertFalse(result["success"], result)
        self.assertNotIn("queued", result.get("message", ""))
        self.assertIn("Email disabled in configuration", result["error"])

    def test_test_email_button_reports_the_queueing_error(self):
        from verenigingen.verenigingen.doctype.verenigingen_email_configuration.verenigingen_email_configuration import (
            send_test_email,
        )

        # Mock justified: External Service - the SMTP queueing boundary below EmailService, to force an error
        with patch("frappe.sendmail", side_effect=RuntimeError("smtp boom")):
            result = send_test_email(f"test-2177-{frappe.generate_hash(length=5)}@example.org")
        self.assertFalse(result["success"], result)
        self.assertIn("smtp boom", result["error"])  # the real error, not "Unknown error"

    # -- ContributionAmendmentRequest.handle_mollie_sync_failure ---------------------------------

    def _fail_sync(self, amendment):
        from verenigingen.verenigingen.doctype.contribution_amendment_request.contribution_amendment_request import (
            ContributionAmendmentRequest,
        )

        self.expectErrorLog("Mollie Sync Failed")  # the handler logs the failure it reports, by design
        with patch("frappe.logger") as logger, patch.object(frappe.db, "commit"):
            ContributionAmendmentRequest.handle_mollie_sync_failure(amendment, "boom")
        return logger

    def test_sync_failure_alert_is_queued_and_logged_without_a_notification_error(self):
        amendment = self._amendment()
        with self.assertNoErrorLog(ignore=("Mollie Sync Failed",)):
            logger = self._fail_sync(amendment)
        self.assertIn(self.holder, self._queued_recipients(amendment.name))
        self.assertIn("Sent failure notification", self._log_lines(logger))

    def test_sync_failure_alert_skipped_is_not_logged_as_sent(self):
        amendment = self._amendment()
        self._disable(key=REQUEST_KEY, master=False)
        with self.assertNoErrorLog(ignore=("Mollie Sync Failed",)):  # a skip is not an error
            logger = self._fail_sync(amendment)
        self.assertEqual(self._queued_recipients(amendment.name), [])
        self.assertNotIn("Sent failure notification", self._log_lines(logger))

    def test_sync_failure_alert_send_error_is_logged_with_its_message(self):
        amendment = self._amendment()
        self.expectErrorLog("smtp boom")
        with self.assertErrorLog("smtp boom"):
            # Mock justified: External Service - the SMTP queueing boundary below EmailService, to force an error
            with patch("frappe.sendmail", side_effect=RuntimeError("smtp boom")):
                logger = self._fail_sync(amendment)
        self.assertNotIn("Sent failure notification", self._log_lines(logger))

    # -- amendment_events.notify_administrators_of_sync_issue ----------------------------------

    def _notify(self, amendment):
        from verenigingen.verenigingen_payments.mollie.events import amendment_events

        with patch("frappe.logger") as logger:
            amendment_events.notify_administrators_of_sync_issue(
                amendment, {"status": "error", "message": "x"}
            )
        return logger

    def test_amendment_sync_issue_mail_is_queued_through_the_real_service(self):
        amendment = self._amendment()
        with self.assertNoErrorLog():
            logger = self._notify(amendment)
        self.assertIn(self.holder, self._queued_recipients(amendment.name))
        self.assertIn("Sent Mollie subscription sync issue notification", self._log_lines(logger))

    def test_amendment_sync_issue_honours_its_notification_key(self):
        amendment = self._amendment()
        self._disable(key=SYNC_KEY, master=False)
        logger = self._notify(amendment)
        self.assertEqual(self._queued_recipients(amendment.name), [])
        self.assertNotIn("Sent Mollie subscription sync issue", self._log_lines(logger))

    def test_amendment_sync_issue_send_error_is_recorded(self):
        amendment = self._amendment()
        self.expectErrorLog("smtp boom")
        with self.assertErrorLog("smtp boom"):
            # Mock justified: External Service - the SMTP queueing boundary below EmailService, to force an error
            with patch("frappe.sendmail", side_effect=RuntimeError("smtp boom")):
                logger = self._notify(amendment)
        self.assertNotIn("Sent Mollie subscription sync issue", self._log_lines(logger))

    # -- the key's cooldown is per recipient per key: it must be scoped per amendment ------------

    def _seeded_cooldown(self):
        """The cooldown a migrated site really has (the registry default), not the 0 setUp forces."""
        config = frappe.get_single(CONFIG)
        for row in config.notification_types:
            if row.notification_key in (SYNC_KEY, REQUEST_KEY):
                row.cooldown_minutes = DEFAULT_COOLDOWN_MINUTES
        config.save()
        clear_email_cooldowns()
        self.assertGreater(DEFAULT_COOLDOWN_MINUTES, 0, "control: the default cooldown is not zero")

    def test_a_second_amendments_sync_issue_alert_is_not_silenced_by_the_first(self):
        self._seeded_cooldown()
        first, second = self._amendment(), self._amendment()
        self._notify(first)
        self._notify(second)
        self.assertIn(self.holder, self._queued_recipients(first.name))
        self.assertIn(self.holder, self._queued_recipients(second.name))

    def test_the_same_amendments_sync_issue_alert_is_throttled_within_the_cooldown(self):
        self._seeded_cooldown()
        amendment = self._amendment()
        self._notify(amendment)
        self._notify(amendment)
        self.assertEqual(self._queued_recipients(amendment.name).count(self.holder), 1)

    def test_a_second_amendments_sync_failure_alert_is_not_silenced_by_the_first(self):
        self._seeded_cooldown()
        first, second = self._amendment(), self._amendment()
        self._fail_sync(first)
        self._fail_sync(second)
        self.assertIn(self.holder, self._queued_recipients(first.name))
        self.assertIn(self.holder, self._queued_recipients(second.name))

    def test_the_same_amendments_sync_failure_alert_is_throttled_within_the_cooldown(self):
        self._seeded_cooldown()
        amendment = self._amendment()
        self._fail_sync(amendment)
        self._fail_sync(amendment)
        self.assertEqual(self._queued_recipients(amendment.name).count(self.holder), 1)
