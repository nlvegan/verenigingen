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
from verenigingen.verenigingen_payments.mollie.services.recurring_donation_charge import (
    RecurringChargeOriginMissing,
    ensure_donation_for_recurring_charge,
)

# `None` is a meaningful subscription_id in _charge() -- it is how "this payment
# has no subscription" is expressed -- so the default cannot be None.
_UNSET = object()


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


class TestEnsureDonationForRecurringCharge(EnhancedTestCase):
    """The service that gives a subscription charge a Donation of its own."""

    def setUp(self):
        super().setUp()
        # "Mollie" and "iDEAL" are not app fixtures; "SEPA Direct Debit" is the
        # mode the charge is expected to land on. Seed all three so the class
        # passes in isolation rather than on shard ordering.
        self.ensure_mode_of_payment("iDEAL")
        self.ensure_mode_of_payment("SEPA Direct Debit")
        # Every Mollie id in this class carries a per-test suffix. payment_id is
        # UNIQUE, so a leftover row from an interrupted run would make a fixed
        # literal fail forever on that site, and the subscription-id fallback
        # would join to it.
        self.tag = frappe.generate_hash(length=8)
        self.subscription_id = f"sub_book_{self.tag}"
        self.first_payment_id = f"tr_the_first_one_{self.tag}"

    # --- fixtures -------------------------------------------------------------------

    def _setup_donor(self):
        # self.factory.create_test_donor() does not exist on EnhancedTestCase's
        # factory (EnhancedTestDataFactory); build the donor the way
        # test_donation_subscription_activation.py does.
        donor = frappe.new_doc("Donor")
        donor.donor_name = f"Charge Donor {frappe.generate_hash(length=6)}"
        donor.donor_email = f"charge.{frappe.generate_hash(length=6)}@example.org"
        donor.donor_type = "Individual"
        donor.preferred_communication_method = "Email"
        donor.flags.ignore_validate = True
        donor.insert(ignore_permissions=True)
        self.track_test_record("Donor", donor.name)
        return donor.name

    def _setup_origin(self, donor=None, **overrides):
        values = {
            "doctype": "Donation",
            "donor": donor or self._setup_donor(),
            "donation_date": "2026-07-01",
            "amount": 25,
            "mode_of_payment": "iDEAL",
            "status": "Recurring",
            "paid": 1,
            "payment_id": self.first_payment_id,
            "mollie_subscription_id": self.subscription_id,
            "mollie_customer_id": "cst_book",
            "recurring_frequency": "Monthly",
        }
        values.update(overrides)
        origin = frappe.get_doc(values).insert()
        self.track_test_record("Donation", origin.name)
        return origin

    def _setup_agreement(self, donor):
        """An Active pledge agreement for `donor`.

        A non-ANBI duration keeps ANBIValidationService (BSN, consent, one
        active ANBI agreement per donor) out of the fixture. It is inserted as
        Draft and promoted with db.set_value so the Active-only after_insert /
        on_update notification paths never run.
        """
        agreement = frappe.get_doc(
            {
                "doctype": "Periodic Donation Agreement",
                "donor": donor,
                "agreement_type": "Private Written",
                "agreement_date": "2026-07-01",
                "start_date": "2026-07-01",
                "agreement_duration_years": "1 Year (Pledge - No ANBI benefits)",
                "anbi_eligible": 0,
                "annual_amount": 300,
                "payment_frequency": "Monthly",
                "payment_method": "SEPA Direct Debit",
                "status": "Draft",
            }
        ).insert(ignore_permissions=True)
        self.track_test_record("Periodic Donation Agreement", agreement.name)
        frappe.db.set_value("Periodic Donation Agreement", agreement.name, "status", "Active")
        agreement.reload()
        return agreement

    def _charge(self, origin_name=None, subscription_id=_UNSET, payment_id=None, **overrides):
        """A recurring charge in the shape Mollie actually sends.

        Measured on a real subscription payment: sequenceType 'recurring',
        subscriptionId, customerId, mandateId, method 'directdebit', and the
        subscription's metadata copied verbatim -- metadata.payment_id being the
        FIRST payment's id, not this charge's.
        """
        if subscription_id is _UNSET:
            subscription_id = self.subscription_id
        payload = {
            "id": payment_id or f"tr_charge_{frappe.generate_hash(length=8)}",
            "status": "paid",
            "sequenceType": "recurring",
            "subscriptionId": subscription_id,
            "customerId": "cst_book",
            "mandateId": "mdt_book",
            "method": "directdebit",
            "description": "Recurring donation",
            "amount": {"value": "25.00", "currency": "EUR"},
            "createdAt": "2026-08-01T00:10:00+00:00",
            "paidAt": "2026-08-03T09:00:00+00:00",
            "metadata": {"donation_id": origin_name, "payment_id": self.first_payment_id}
            if origin_name
            else None,
        }
        payload.update(overrides)
        return payload

    # --- what it declines to touch -------------------------------------------------

    def test_first_payment_is_not_a_charge(self):
        self.assertIsNone(ensure_donation_for_recurring_charge(self._charge(sequenceType="first")))

    def test_payment_without_a_subscription_is_not_a_charge(self):
        self.assertIsNone(ensure_donation_for_recurring_charge(self._charge(subscription_id=None)))

    def test_unpaid_charge_creates_nothing(self):
        # Charges are created 'pending' and settle days later; only a paid one books.
        origin = self._setup_origin()
        charge = self._charge(origin.name, status="pending")
        self.assertIsNone(ensure_donation_for_recurring_charge(charge))
        self.assertFalse(frappe.db.exists("Donation", {"payment_id": charge["id"]}))

    def test_failed_charge_creates_nothing_but_is_audited(self):
        origin = self._setup_origin()
        charge = self._charge(origin.name, status="failed")
        before = frappe.db.count("Mollie Audit Log")
        self.assertIsNone(ensure_donation_for_recurring_charge(charge))
        self.assertFalse(frappe.db.exists("Donation", {"payment_id": charge["id"]}))
        self.assertGreater(
            frappe.db.count("Mollie Audit Log"), before, "a failed charge must leave a trace"
        )

    # --- the happy path -------------------------------------------------------------

    def test_creates_a_donation_for_the_charge(self):
        origin = self._setup_origin()
        payload = self._charge(origin.name)
        charge = frappe.get_doc("Donation", ensure_donation_for_recurring_charge(payload))
        self.assertEqual(charge.payment_id, payload["id"])
        self.assertEqual(charge.recurring_origin_donation, origin.name)
        self.assertEqual(charge.donor, origin.donor)
        self.assertEqual(float(charge.amount), 25.00)
        self.assertEqual(str(charge.donation_date), "2026-08-03")
        self.assertEqual(charge.paid, 1)
        self.assertEqual(charge.status, "Recurring")
        self.assertEqual(charge.mollie_subscription_id, self.subscription_id)

    def test_mode_of_payment_reflects_the_charge_not_the_origin(self):
        # The origin was iDEAL; the charge is always a direct debit.
        origin = self._setup_origin(mode_of_payment="iDEAL")
        charge = frappe.get_doc(
            "Donation", ensure_donation_for_recurring_charge(self._charge(origin.name))
        )
        self.assertEqual(charge.mode_of_payment, "SEPA Direct Debit")

    def test_designation_fields_are_carried_over(self):
        origin = self._setup_origin(
            donation_purpose_type="Chapter",
            chapter_reference=self.factory.create_test_chapter().name,
            fund_designation="Sanctuary fund",
        )
        charge = frappe.get_doc(
            "Donation", ensure_donation_for_recurring_charge(self._charge(origin.name))
        )
        self.assertEqual(charge.donation_purpose_type, "Chapter")
        self.assertEqual(charge.chapter_reference, origin.chapter_reference)
        self.assertEqual(charge.fund_designation, "Sanctuary fund")

    def test_campaign_recorded_only_in_notes_still_validates(self):
        # validate_donation_purpose accepts purpose_type Campaign without a
        # campaign link only when "Campaign:" appears in the notes. Dropping
        # donation_notes would make every charge of such a donation throw.
        origin = self._setup_origin(
            donation_purpose_type="Campaign", donation_notes="Campaign: Zomeractie 2026"
        )
        charge = frappe.get_doc(
            "Donation", ensure_donation_for_recurring_charge(self._charge(origin.name))
        )
        self.assertIn("Campaign:", charge.donation_notes)

    def test_resolves_the_origin_by_subscription_when_metadata_is_null(self):
        origin = self._setup_origin()
        name = ensure_donation_for_recurring_charge(self._charge(origin_name=None))
        self.assertEqual(frappe.get_doc("Donation", name).recurring_origin_donation, origin.name)

    # --- idempotency ----------------------------------------------------------------

    def test_redelivery_does_not_create_a_second_donation(self):
        origin = self._setup_origin()
        payload = self._charge(origin.name)
        first = ensure_donation_for_recurring_charge(payload)
        second = ensure_donation_for_recurring_charge(payload)
        self.assertEqual(first, second)
        self.assertEqual(frappe.db.count("Donation", {"payment_id": payload["id"]}), 1)

    def test_a_lost_race_adopts_the_winner(self):
        # Simulates the interleaving the unique constraint exists for: the
        # existence check passes, then another worker inserts before we do.
        origin = self._setup_origin()
        payload = self._charge(origin.name)
        winner = ensure_donation_for_recurring_charge(payload)
        with patch(
            "verenigingen.verenigingen_payments.mollie.services.recurring_donation_charge"
            "._donation_for_charge",
            return_value=None,
        ):
            adopted = ensure_donation_for_recurring_charge(payload)
        self.assertEqual(adopted, winner)
        self.assertEqual(frappe.db.count("Donation", {"payment_id": payload["id"]}), 1)

    # --- failures -------------------------------------------------------------------

    def test_unknown_subscription_raises_so_mollie_retries(self):
        # severity="error" makes MollieAuditLogger mirror the row into Error Log.
        self.expectErrorLog("recurring_charge_origin_missing")
        with self.assertRaises(RecurringChargeOriginMissing):
            ensure_donation_for_recurring_charge(
                self._charge(subscription_id=f"sub_nobody_knows_{self.tag}")
            )

    def test_cancelled_agreement_does_not_block_the_booking(self):
        # validate_periodic_donation_agreement throws for a non-Active agreement.
        # A donor who cancels the agreement while Mollie keeps charging must not
        # turn every charge into an unbooked retry loop.
        donor = self._setup_donor()
        agreement = self._setup_agreement(donor)
        origin = self._setup_origin(donor=donor, periodic_donation_agreement=agreement.name)
        frappe.db.set_value("Periodic Donation Agreement", agreement.name, "status", "Cancelled")
        charge = frappe.get_doc(
            "Donation", ensure_donation_for_recurring_charge(self._charge(origin.name))
        )
        self.assertFalse(charge.periodic_donation_agreement)

    # --- the agreement total, which is the whole reason for Donation-per-charge ---

    def test_each_charge_is_counted_in_the_agreement_total(self):
        """The justification for the data model, asserted rather than assumed.

        update_donation_tracking sums the agreement's `donations` child table,
        and only link_donation appends to it -- setting
        Donation.periodic_donation_agreement does not. link_donation has no
        production callers, so if the service does not call it this number never
        moves and a Donation per charge buys nothing.
        """
        donor = self._setup_donor()
        agreement = self._setup_agreement(donor)
        origin = self._setup_origin(donor=donor, periodic_donation_agreement=agreement.name)
        frappe.get_doc("Periodic Donation Agreement", agreement.name).link_donation(origin.name)

        ensure_donation_for_recurring_charge(self._charge(origin.name, payment_id=f"tr_c1_{self.tag}"))
        ensure_donation_for_recurring_charge(self._charge(origin.name, payment_id=f"tr_c2_{self.tag}"))

        agreement.reload()
        self.assertEqual(agreement.donations_count, 3, "origin plus two charges")
        self.assertEqual(float(agreement.total_donated), 75.00)

    def test_a_redelivered_charge_is_not_counted_twice(self):
        donor = self._setup_donor()
        agreement = self._setup_agreement(donor)
        origin = self._setup_origin(donor=donor, periodic_donation_agreement=agreement.name)

        payload = self._charge(origin.name)
        ensure_donation_for_recurring_charge(payload)
        ensure_donation_for_recurring_charge(payload)

        agreement.reload()
        self.assertEqual(agreement.donations_count, 1)
        self.assertEqual(float(agreement.total_donated), 25.00)
