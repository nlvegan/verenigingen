"""A caller that ignores the EmailService result must not claim a send (#2178, #2096 class).

EmailService reports a cooldown, a disabled key or an opt-out as a *successful* result carrying
``data["skipped"]``, and a missing outgoing account as ``success=False``. Each test drives the
caller through the real EmailService (no stub of the result): a CONTROL run with the key enabled
must really queue a mail and be recorded as sent, then the key is disabled (or the outgoing
account made unusable) and the same call must queue nothing and record nothing as sent.

Probe shortcuts, stated: the Membership's ``renewal_date`` is set with ``db.set_value`` to move it
into the 15-day reminder window (how a renewal date is derived is not under test); the SEPA
manager's private ``_send_email`` is called directly with the content/context dicts its caller
builds.
"""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from verenigingen.setup.notification_registry_setup import ensure_notification_registry_rows
from verenigingen.tests.fixtures.dutch_validation_helpers import generate_valid_bsn
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.utils.notification_state import own_notification_keys, queued_mail_count
from verenigingen.tests.utils.reminder_mail_state import (
    clear_email_cooldowns,
    configure_notification_key,
    ensure_outgoing_email_account,
)
from verenigingen.tests.utils.stock_email_templates import ensure_stock_email_template
from verenigingen.verenigingen.doctype.membership import scheduler

PDA_KEY = "periodic_donation_cancellation"
RENEWAL_KEY = "membership_renewal_reminder"
SEPA_KEY = "sepa_member_pre_notification"
NO_ACCOUNT = "verenigingen.services.communication.email_service.EmailService._has_active_email_account"


class TestUnreadEmailResultClaimsSent(VereningingenTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._accounts_before = set(frappe.db.sql_list("select name from `tabEmail Account`"))

    @classmethod
    def tearDownClass(cls):
        leaked = set(frappe.db.sql_list("select name from `tabEmail Account`")) - cls._accounts_before
        super().tearDownClass()
        if leaked:
            raise AssertionError(f"Email Account(s) leaked by this module: {sorted(leaked)}")

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        ensure_outgoing_email_account(self)
        ensure_notification_registry_rows()
        clear_email_cooldowns()
        self.addCleanup(clear_email_cooldowns)

    # ---- STATE: Periodic Donation Agreement cancellation_confirmation_sent ----

    def _active_agreement(self):
        ensure_stock_email_template("periodic_agreement_cancellation")
        donor = self.create_test_donor(
            donor_type="Individual", anbi_consent=1, bsn_citizen_service_number=generate_valid_bsn()
        )
        agreement = self.create_test_periodic_donation_agreement(donor=donor.name, status="Active")
        return donor, agreement

    def _sent_flag(self, agreement):
        return frappe.db.get_value("Periodic Donation Agreement", agreement.name, "cancellation_confirmation_sent")

    def test_cancellation_confirmation_is_recorded_sent_when_mail_queued(self):
        own_notification_keys(self, PDA_KEY)
        donor, agreement = self._active_agreement()
        before = queued_mail_count(donor.donor_email)

        agreement.cancel_agreement(reason="control", send_email=True)

        self.assertEqual(queued_mail_count(donor.donor_email), before + 1, "control: the mail must go out")
        self.assertEqual(self._sent_flag(agreement), 1)

    def test_cancellation_confirmation_skipped_is_not_recorded_sent(self):
        own_notification_keys(self, PDA_KEY)
        configure_notification_key(PDA_KEY, 0, 0)
        donor, agreement = self._active_agreement()
        before = queued_mail_count(donor.donor_email)

        agreement.cancel_agreement(reason="disabled key", send_email=True)

        self.assertEqual(queued_mail_count(donor.donor_email), before)
        self.assertEqual(self._sent_flag(agreement), 0, "a skipped mail must not be recorded as sent")

    def test_cancellation_confirmation_not_queued_is_not_recorded_sent(self):
        own_notification_keys(self, PDA_KEY)
        donor, agreement = self._active_agreement()
        # Mock justified: infrastructure absence (no usable outgoing Email Account).
        with patch(NO_ACCOUNT, return_value=False):
            agreement.cancel_agreement(reason="no account", send_email=True)

        self.assertEqual(self._sent_flag(agreement), 0, "a failed mail must not be recorded as sent")

    # ---- COUNT: membership renewal reminders ----------------------------------

    def _windowed_membership(self):
        if not frappe.db.exists("Email Template", "membership_renewal_reminder"):
            tmpl = frappe.get_doc(
                {
                    "doctype": "Email Template",
                    "name": "membership_renewal_reminder",
                    "subject": "Renewal reminder",
                    "response": "<p>Please renew {{ days_to_expiry }}</p>",
                    "response_html": "<p>Please renew {{ days_to_expiry }}</p>",
                    "use_html": 1,
                }
            )
            tmpl.insert()
            self.track_doc("Email Template", tmpl.name)
        member = self.create_test_member(
            first_name="Unread",
            last_name="Result",
            email=f"unread.result.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        mtype = self.create_test_membership_type(
            membership_type_name=f"UnreadType{frappe.generate_hash(length=6)}"
        )
        membership = self.create_test_membership(member=member.name, membership_type=mtype.name)
        membership.submit()
        frappe.db.set_value(
            "Membership", membership.name, "renewal_date", add_days(today(), 15), update_modified=False
        )
        return frappe.db.get_value("Membership", membership.name, "email")

    def test_renewal_reminder_is_counted_when_mail_queued(self):
        own_notification_keys(self, RENEWAL_KEY)
        email = self._windowed_membership()
        before = queued_mail_count(email)

        count = scheduler._send_renewal_reminders_impl()

        self.assertEqual(queued_mail_count(email), before + 1, "control: the mail must go out")
        self.assertGreaterEqual(count, 1)

    def test_renewal_reminder_skipped_is_not_counted(self):
        own_notification_keys(self, RENEWAL_KEY)
        configure_notification_key(RENEWAL_KEY, 0, 0)
        email = self._windowed_membership()
        before = queued_mail_count(email)

        count = scheduler._send_renewal_reminders_impl()

        self.assertEqual(queued_mail_count(email), before)
        self.assertEqual(count, 0, "every send was skipped, so nothing may be counted")

    def test_renewal_reminder_not_queued_is_not_counted(self):
        own_notification_keys(self, RENEWAL_KEY)
        self._windowed_membership()
        # Mock justified: infrastructure absence (no usable outgoing Email Account).
        with patch(NO_ACCOUNT, return_value=False):
            count = scheduler._send_renewal_reminders_impl()

        self.assertEqual(count, 0)

    # ---- RETURN VALUE: SEPA notification manager delivery claim ----------------

    def _manager_send(self):
        from verenigingen.verenigingen_payments.utils.sepa_notification_manager import SEPANotificationManager

        return SEPANotificationManager()._send_email(
            {"subject": "Unread result probe", "message": "<p>probe</p>"},
            ["unread-result-probe@example.org"],
            {"notification_key": SEPA_KEY},
        )

    def test_sepa_manager_email_channel_reports_success_when_queued(self):
        own_notification_keys(self, SEPA_KEY)
        before = queued_mail_count("unread-result-probe@example.org")

        result = self._manager_send()

        self.assertEqual(queued_mail_count("unread-result-probe@example.org"), before + 1)
        self.assertTrue(result["success"])

    def test_sepa_manager_email_channel_skipped_is_not_a_delivery(self):
        own_notification_keys(self, SEPA_KEY)
        configure_notification_key(SEPA_KEY, 0, 0)

        result = self._manager_send()

        self.assertFalse(result["success"], "a skipped mail must not mark the notification delivered")

    def test_sepa_manager_email_channel_not_queued_is_not_a_delivery(self):
        own_notification_keys(self, SEPA_KEY)
        with patch(NO_ACCOUNT, return_value=False):
            result = self._manager_send()

        self.assertFalse(result["success"])

    # ---- RETURN VALUE: SEPA test_notification_system endpoint ------------------

    def _test_notification_endpoint(self, enabled):
        from verenigingen.tests.payment.test_sepa_literal_recipients import (
            _put_key_row,
            _restore_rows,
            _snapshot_rows,
        )
        from verenigingen.verenigingen_payments.api.sepa_batch_notifications import test_notification_system

        ensure_stock_email_template("payment_notification")
        rows = _snapshot_rows()
        self.addCleanup(_restore_rows, rows)
        own_notification_keys(self, "email_template_test")
        _put_key_row("email_template_test", "Fixed", fixed_recipients="probe-2178@example.org", enabled=enabled)
        before = queued_mail_count("probe-2178@example.org")
        result = test_notification_system()
        return result, queued_mail_count("probe-2178@example.org") - before

    def test_notification_endpoint_reports_success_when_queued(self):
        result, queued = self._test_notification_endpoint(enabled=1)
        self.assertEqual(queued, 1, "control: the test mail must go out")
        self.assertTrue(result["success"], result)

    def test_notification_endpoint_skipped_mail_is_not_reported_sent(self):
        result, queued = self._test_notification_endpoint(enabled=0)
        self.assertEqual(queued, 0)
        self.assertFalse(result["success"], "nothing was sent, so the endpoint must not say so")
