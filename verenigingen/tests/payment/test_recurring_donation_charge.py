"""Booking a recurring Mollie donation charge — issue #345 part A.

Mollie charges a recurring donor every period and posts the subscription's
webhookUrl with a NEW payment id. Nothing matched that id to a donation, so
every charge after the first went unbooked. A charge now gets its own Donation,
carrying payment_id = the charge's id, and the existing webhook pipeline books
it from there.

Run with:
    cd ~/frappe-bench && PYTHONPATH=<worktree> bench --site test_site_1 \\
      run-tests --app verenigingen \\
      --module verenigingen.tests.payment.test_recurring_donation_charge
"""

from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestChargeDonationEmails(EnhancedTestCase):
    """A charge must not re-thank the donor for donating."""

    def _create_donor(self):
        # self.factory.create_test_donor() does not exist on EnhancedTestCase's
        # factory (EnhancedTestDataFactory) -- confirmed by an AttributeError at
        # runtime, not by reading. Build the donor the same way
        # test_donation_subscription_activation.py does instead of inventing a
        # new shared fixture helper.
        donor = frappe.new_doc("Donor")
        donor.donor_name = f"Charge Donor {frappe.generate_hash(length=6)}"
        donor.donor_email = f"charge.{frappe.generate_hash(length=6)}@example.org"
        donor.donor_type = "Individual"
        donor.preferred_communication_method = "Email"
        donor.flags.ignore_validate = True
        donor.insert(ignore_permissions=True)
        self.track_test_record("Donor", donor.name)
        return donor.name

    def _donation(self, **overrides):
        donor_name = self._create_donor()
        values = {
            "doctype": "Donation",
            "donor": donor_name,
            "donation_date": frappe.utils.nowdate(),
            "amount": 25,
            "mode_of_payment": "Mollie",
            "paid": 0,
            "status": "One-time",
        }
        values.update(overrides)
        return frappe.get_doc(values)

    def test_recurring_origin_donation_field_exists(self):
        meta = frappe.get_meta("Donation")
        field = meta.get_field("recurring_origin_donation")
        self.assertIsNotNone(field, "Donation.recurring_origin_donation is missing")
        self.assertEqual(field.fieldtype, "Link")
        self.assertEqual(field.options, "Donation")

    def test_origin_donation_sends_the_donation_confirmation(self):
        # Control. Without this, the next test passes even if the email was
        # never sent for any donation at all.
        with patch("frappe.enqueue") as enqueued:
            self._donation().insert()
        methods = [c.args[0] if c.args else c.kwargs.get("method") for c in enqueued.call_args_list]
        self.assertIn(
            "verenigingen.verenigingen.doctype.donation.donation.send_donation_confirmation_email",
            methods,
        )

    def test_charge_donation_does_not_send_the_donation_confirmation(self):
        origin = self._donation().insert()
        with patch("frappe.enqueue") as enqueued:
            self._donation(recurring_origin_donation=origin.name, status="Recurring").insert()
        methods = [c.args[0] if c.args else c.kwargs.get("method") for c in enqueued.call_args_list]
        self.assertNotIn(
            "verenigingen.verenigingen.doctype.donation.donation.send_donation_confirmation_email",
            methods,
        )

    def test_charge_donation_still_sends_the_payment_confirmation(self):
        # The donor keeps a receipt per period; only the "welcome" mail is dropped.
        origin = self._donation().insert()
        with patch("frappe.enqueue") as enqueued:
            self._donation(recurring_origin_donation=origin.name, status="Recurring", paid=1).insert()
        methods = [c.args[0] if c.args else c.kwargs.get("method") for c in enqueued.call_args_list]
        self.assertIn(
            "verenigingen.verenigingen.doctype.donation.donation.send_payment_confirmation_email",
            methods,
        )
