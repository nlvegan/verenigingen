"""A cooldown/disabled skip is not a send: ANBI consent + renewal reminders (#2044).

EmailService reports a skip as a *successful* OperationResult carrying
``data["skipped"]``. Every test here produces its skip through the real EmailService
path (send once, re-send inside the cooldown window; or disable the key) and reads what
really went out from the Email Queue, never from ``result.success``.
"""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from verenigingen.api.anbi_operations import send_consent_requests
from verenigingen.api.periodic_donation_operations import send_renewal_reminders
from verenigingen.setup.notification_registry_setup import ensure_notification_registry_rows
from verenigingen.tests.fixtures.dutch_validation_helpers import generate_valid_bsn
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.utils.reminder_mail_state import (
    clear_email_cooldowns,
    configure_notification_key,
    ensure_outgoing_email_account,
)
from verenigingen.tests.utils.stock_email_templates import _load_fixture_rows

CONSENT_KEY = "anbi_consent_request"
EXPIRY_KEY = "periodic_donation_expiry"
CONSENT_LOG = "ANBI consent request email sent"
EXPIRY_LOG = "Renewal reminder sent"


class TestSkippedMailNotCountedSent(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self._baseline = {}
        frappe.set_user("Administrator")
        ensure_outgoing_email_account()
        ensure_notification_registry_rows()
        self._ensure_template(CONSENT_KEY)
        self._configure_master(1)
        configure_notification_key(CONSENT_KEY, 1, 43200)
        configure_notification_key(EXPIRY_KEY, 1, 1440)
        clear_email_cooldowns()
        self.addCleanup(clear_email_cooldowns)

    # ---- helpers -------------------------------------------------------

    def _ensure_template(self, name):
        if frappe.db.exists("Email Template", name):
            return
        row = {k: v for k, v in _load_fixture_rows()[name].items() if k != "modified"}
        doc = frappe.get_doc(row)
        doc.flags.ignore_links = True
        doc.insert()

    def _configure_master(self, master):
        config = frappe.get_single("Verenigingen Email Configuration")
        config.master_email_enabled = master
        config.save()

    def _new_mail(self, email):
        """Mails queued for this address SINCE the fixture was built.

        Email Queue is written by frappe.sendmail. Activating an agreement already mails
        its donor (a confirmation), so the count is taken relative to a baseline recorded
        after the fixture exists.
        """
        return frappe.db.count("Email Queue Recipient", {"recipient": email}) - self._baseline[email]

    def _mark_baseline(self, email):
        self._baseline[email] = frappe.db.count("Email Queue Recipient", {"recipient": email})

    def _comments(self, doctype, name, marker):
        return frappe.get_all(
            "Comment",
            filters={"reference_doctype": doctype, "reference_name": name, "content": ["like", f"%{marker}%"]},
        )

    def _consent_donor(self):
        donor = self.create_test_donor(donor_type="Individual", anbi_consent=0)
        donation = self.create_test_donation(donor=donor.name, amount=40.0, paid=1)
        donation.reload()
        if donation.docstatus == 0:
            donation.submit()
        self._mark_baseline(donor.donor_email)
        return donor

    def _expiring_agreement(self):
        donor = self.create_test_donor(
            donor_type="Individual", anbi_consent=1, bsn_citizen_service_number=generate_valid_bsn()
        )
        agreement = self.create_anbi_compliant_agreement(donor=donor.name, status="Active")
        frappe.db.set_value("Periodic Donation Agreement", agreement.name, "end_date", add_days(today(), 30))
        self._mark_baseline(donor.donor_email)
        return donor, agreement

    # ---- ANBI consent requests -------------------------------------------

    def test_consent_request_inside_cooldown_is_not_logged_or_counted_as_sent(self):
        donor = self._consent_donor()

        first = send_consent_requests()
        self.assertEqual(self._new_mail(donor.donor_email), 1, "the first run must really send")
        self.assertEqual(len(self._comments("Donor", donor.name, CONSENT_LOG)), 1)
        self.assertGreaterEqual(first["data"]["sent_count"], 1)

        second = send_consent_requests()
        self.assertEqual(self._new_mail(donor.donor_email), 1, "the re-run must queue nothing new")
        self.assertEqual(
            len(self._comments("Donor", donor.name, CONSENT_LOG)),
            1,
            "a cooldown-skipped request must not be logged as sent",
        )
        self.assertGreaterEqual(second["data"]["skipped_count"], 1)
        self.assertIn("All recipients in cooldown", second["data"]["skipped_reasons"])
        self.assertEqual(second["data"]["sent_count"], 0, "nothing went out, so none can be 'sent'")
        self.assertNotIn(" 1 consent request emails sent", second["meta"]["message"])

    def test_consent_request_with_disabled_key_is_skipped_not_sent(self):
        donor = self._consent_donor()
        configure_notification_key(CONSENT_KEY, 0, 0)

        result = send_consent_requests()

        self.assertEqual(self._new_mail(donor.donor_email), 0)
        self.assertEqual(self._comments("Donor", donor.name, CONSENT_LOG), [])
        self.assertEqual(result["data"]["sent_count"], 0)
        self.assertGreaterEqual(result["data"]["skipped_count"], 1)

    def test_consent_request_not_queued_is_failed_not_sent(self):
        donor = self._consent_donor()
        # Mock justified: infrastructure absence (no usable outgoing Email Account).
        with patch(
            "verenigingen.services.communication.email_service.EmailService._has_active_email_account",
            return_value=False,
        ):
            result = send_consent_requests()

        self.assertEqual(self._new_mail(donor.donor_email), 0)
        self.assertEqual(self._comments("Donor", donor.name, CONSENT_LOG), [])
        self.assertEqual(result["data"]["sent_count"], 0)
        self.assertGreaterEqual(result["data"]["failed_count"], 1)

    # ---- periodic donation renewal reminders -----------------------------

    def test_renewal_reminder_inside_cooldown_is_not_logged_or_counted_as_sent(self):
        donor, agreement = self._expiring_agreement()

        first = send_renewal_reminders(days_before_expiry=90)
        self.assertEqual(self._new_mail(donor.donor_email), 1, "the first run must really send")
        self.assertEqual(len(self._comments("Periodic Donation Agreement", agreement.name, EXPIRY_LOG)), 1)
        self.assertGreaterEqual(first["data"]["sent_count"], 1)

        second = send_renewal_reminders(days_before_expiry=90)
        self.assertEqual(self._new_mail(donor.donor_email), 1, "the re-run must queue nothing new")
        self.assertEqual(
            len(self._comments("Periodic Donation Agreement", agreement.name, EXPIRY_LOG)),
            1,
            "a cooldown-skipped reminder must not be logged as sent",
        )
        self.assertGreaterEqual(second["data"]["skipped_count"], 1)
        self.assertIn("All recipients in cooldown", second["data"]["skipped_reasons"])
        self.assertEqual(second["data"]["sent_count"], 0)

    def test_renewal_reminder_with_disabled_key_is_skipped_not_sent(self):
        donor, agreement = self._expiring_agreement()
        configure_notification_key(EXPIRY_KEY, 0, 0)

        result = send_renewal_reminders(days_before_expiry=90)

        self.assertEqual(self._new_mail(donor.donor_email), 0)
        self.assertEqual(self._comments("Periodic Donation Agreement", agreement.name, EXPIRY_LOG), [])
        self.assertEqual(result["data"]["sent_count"], 0)
        self.assertGreaterEqual(result["data"]["skipped_count"], 1)

    def test_renewal_reminder_not_queued_is_failed_not_sent(self):
        donor, agreement = self._expiring_agreement()
        # Mock justified: infrastructure absence (no usable outgoing Email Account).
        with patch(
            "verenigingen.services.communication.email_service.EmailService._has_active_email_account",
            return_value=False,
        ):
            result = send_renewal_reminders(days_before_expiry=90)

        self.assertEqual(self._new_mail(donor.donor_email), 0)
        self.assertEqual(self._comments("Periodic Donation Agreement", agreement.name, EXPIRY_LOG), [])
        self.assertEqual(result["data"]["sent_count"], 0)
        self.assertGreaterEqual(result["data"]["failed_count"], 1)
