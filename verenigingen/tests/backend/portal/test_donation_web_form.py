"""
Regression tests for verenigingen/verenigingen/web_form/donation_form/donation_form.py (#755).

Covers two independent defects found in that module:

1. get_or_create_donor()/create_donation() called
   secure_document_operation(..., override_user="Administrator") — a keyword
   argument that does not exist on secure_document_operation's current signature
   (verenigingen/utils/secure_operations.py). Every call raised TypeError before
   any donor/donation was created. The fix must also work for Guest callers
   specifically: secure_document_operation(allow_system_user=True) is NOT a
   working substitute here because Guest holds no role in
   ESCALATION_ALLOWED_ROLES, so it raises PermissionError instead (see the
   guest-donation regression in test_guest_donation_flow.py). The working fix
   mirrors verenigingen/services/donation/{donor_service,public_donation_service}.py:
   switch to the configured system user via secure_user_context().

2. create_periodic_agreement_from_donation() read result.get("agreement") at the
   top level. create_periodic_agreement is @high_security_api-wrapped, which
   converts its OperationResult to the nested {"success", "data": {...}, "meta"}
   schema (verenigingen/utils/operation_result.py) before the caller ever sees
   it, so the real value is at result["data"]["agreement"]. The top-level read
   always resolved to None, which was then passed into
   frappe.get_doc("Periodic Donation Agreement", None) — raising
   DoesNotExistError, silently swallowed by send_periodic_agreement_info's own
   try/except.

3. create_donation() called donation.submit() for any payment method other than
   SEPA Direct Debit/Mollie. Donation is not a submittable DocType
   (is_submittable=0) and no role carries a "submit" DocPerm on it, so this
   always raised PermissionError — but only AFTER the donor and donation had
   already been inserted and committed, so the caller was told the donation
   failed while a real Donor+Donation already existed in the database. Fixed
   by removing the submit() call: a Donation from this form is created, and
   stays, as a draft — matching the live guest-donation path in
   public_donation_service.py, which never submits either.
"""

from unittest.mock import patch

import frappe
from frappe.utils import now_datetime

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.donation_form_data import make_donation_form_data


class TestDonationWebFormGuestSubmission(EnhancedTestCase):
    """REGRESSION (#755 bug 1): guests must be able to submit the donation form."""

    def setUp(self):
        self._original_user = frappe.session.user
        super().setUp()

    def tearDown(self):
        if hasattr(self, "_original_user"):
            frappe.set_user(self._original_user)
        super().tearDown()

    def _web_form_payload(self, **overrides):
        return make_donation_form_data(
            label="Web Form Donor",
            payment_key="mode_of_payment",
            payment_method="SEPA Direct Debit",
            **overrides,
        )

    def test_guest_can_submit_donation_via_donation_form(self):
        """REGRESSION: process_donation_form must not raise TypeError for Guests.

        Before the fix, every call to get_or_create_donor()/create_donation() hit
        secure_document_operation(override_user=...) and raised TypeError,
        immediately in donor creation, before any donor or donation was created.
        """
        from verenigingen.verenigingen.web_form.donation_form.donation_form import process_donation_form

        frappe.set_user("Guest")
        data = self._web_form_payload()
        result = process_donation_form(data)

        self.assertTrue(result.get("success"), f"Guest donation should succeed: {result}")
        self.assertIsNotNone(result.get("donation_id"))

        frappe.set_user(self._original_user)
        donation = frappe.get_doc("Donation", result["donation_id"])
        self.assertEqual(donation.mode_of_payment, "SEPA Direct Debit")
        self.assertEqual(float(donation.amount), 25.0)

        donor = frappe.get_doc("Donor", donation.donor)
        self.assertEqual(donor.donor_email, data["donor_email"])

    def test_guest_get_or_create_donor_does_not_raise(self):
        """REGRESSION: isolates the exact call that raised TypeError."""
        from verenigingen.verenigingen.web_form.donation_form.donation_form import get_or_create_donor

        frappe.set_user("Guest")
        data = self._web_form_payload()
        donor_name = get_or_create_donor(data)

        self.assertIsNotNone(donor_name)
        frappe.set_user(self._original_user)
        donor = frappe.get_doc("Donor", donor_name)
        self.assertEqual(donor.donor_email, data["donor_email"])

    def test_guest_bank_transfer_donation_succeeds_and_stays_draft(self):
        """REGRESSION (#755 bug 3): a non-SEPA/Mollie payment method must not
        call donation.submit() — Donation is not submittable and no role has
        submit rights, so the old code committed a real Donor+Donation and
        THEN told the guest the donation had failed. Bank Transfer is the
        default/most common payment method, so this was the common case, not
        an edge case.
        """
        from verenigingen.verenigingen.web_form.donation_form.donation_form import process_donation_form

        frappe.set_user("Guest")
        data = self._web_form_payload(mode_of_payment="Bank Transfer")
        result = process_donation_form(data)

        frappe.set_user(self._original_user)
        self.assertTrue(result.get("success"), f"Bank Transfer donation should succeed: {result}")
        donation = frappe.get_doc("Donation", result["donation_id"])
        self.assertEqual(donation.docstatus, 0, "Donation must remain a draft, not be submitted")


class TestDonationWebFormCampaignField(EnhancedTestCase):
    """create_donation() previously assigned a Campaign donation's reference to
    donation.campaign_reference — a field that does not exist on Donation
    (frappe.get_meta("Donation") confirms only "campaign" exists, a Link to
    Donation Campaign). Assigning a nonexistent field on a Document is a
    silent no-op, so every Campaign-purpose donation from this form silently
    lost its campaign attribution."""

    def test_campaign_reference_matching_real_campaign_sets_campaign_link(self):
        from verenigingen.verenigingen.web_form.donation_form.donation_form import create_donation

        campaign = frappe.new_doc("Donation Campaign")
        campaign.campaign_name = f"Test Campaign {now_datetime().strftime('%H%M%S%f')}"
        campaign.campaign_type = "Annual Giving"
        campaign.status = "Active"
        campaign.start_date = frappe.utils.today()
        campaign.insert()
        self.track_doc("Donation Campaign", campaign.name)

        donor = self.create_test_donor(donor_type="Individual")
        data = {
            "amount": "10.00",
            "mode_of_payment": "SEPA Direct Debit",
            "donation_purpose_type": "Campaign",
            "campaign_reference": campaign.name,
        }
        donation = create_donation(donor.name, data)
        self.track_doc("Donation", donation.name)

        self.assertEqual(donation.campaign, campaign.name)

    def test_campaign_reference_without_matching_campaign_falls_back_to_notes(self):
        from verenigingen.verenigingen.web_form.donation_form.donation_form import create_donation

        donor = self.create_test_donor(donor_type="Individual")
        data = {
            "amount": "10.00",
            "mode_of_payment": "SEPA Direct Debit",
            "donation_purpose_type": "Campaign",
            "campaign_reference": "Nonexistent Campaign XYZ",
        }
        donation = create_donation(donor.name, data)
        self.track_doc("Donation", donation.name)

        self.assertFalse(donation.campaign)
        self.assertIn("Nonexistent Campaign XYZ", donation.donation_notes or "")


class TestDonationWebFormPeriodicAgreementNesting(EnhancedTestCase):
    """REGRESSION (#755 bug 2): agreement name must be read from the nested
    OperationResult schema, not a non-existent top-level key."""

    def test_create_periodic_agreement_from_donation_passes_real_agreement_name(self):
        """REGRESSION: create_periodic_agreement_from_donation must forward the
        actual agreement name (result["data"]["agreement"]) to
        send_periodic_agreement_info, not None (result.get("agreement"), which
        does not exist in the nested schema).
        """
        from verenigingen.verenigingen.web_form.donation_form.donation_form import (
            create_periodic_agreement_from_donation,
        )

        donor = self.create_test_donor(donor_type="Individual", anbi_consent=1)
        data = {
            "amount": "25.00",
            "recurring_frequency": "Monthly",
            "mode_of_payment": "Bank Transfer",
        }

        with patch(
            "verenigingen.verenigingen.web_form.donation_form.donation_form.send_periodic_agreement_info"
        ) as mock_send:
            create_periodic_agreement_from_donation(donor.name, data)

        mock_send.assert_called_once()
        called_donor, called_agreement_name = mock_send.call_args[0]
        self.assertEqual(called_donor, donor.name)
        self.assertIsNotNone(called_agreement_name, "agreement name must not be None")

        # A bogus name would raise DoesNotExistError here, exactly as it did
        # (silently, inside send_periodic_agreement_info's own try/except)
        # before the fix.
        agreement = frappe.get_doc("Periodic Donation Agreement", called_agreement_name)
        self.assertEqual(agreement.donor, donor.name)
        self.track_doc("Periodic Donation Agreement", agreement.name)

    def test_send_periodic_agreement_info_swallows_email_failure(self):
        """send_periodic_agreement_info wraps its email send in its own
        try/except so a broken email service cannot take down agreement
        creation. Induce a REAL failure inside send_periodic_agreement_info
        (not by mocking the function itself, which would bypass its own
        try/except entirely) and confirm: no exception escapes
        create_periodic_agreement_from_donation, the agreement still exists,
        and the failure was actually logged (not just silently skipped).
        """
        from verenigingen.verenigingen.web_form.donation_form.donation_form import (
            create_periodic_agreement_from_donation,
        )

        self.expectErrorLog("Agreement Email Error")

        donor = self.create_test_donor(donor_type="Individual", anbi_consent=1)
        data = {
            "amount": "25.00",
            "recurring_frequency": "Monthly",
            "mode_of_payment": "Bank Transfer",
        }

        before = now_datetime()
        with patch(
            "verenigingen.verenigingen.web_form.donation_form.donation_form.get_email_service",
            side_effect=Exception("smtp down"),
        ):
            # Should not raise even though sending the confirmation email fails.
            create_periodic_agreement_from_donation(donor.name, data)

        agreements = frappe.get_all("Periodic Donation Agreement", filters={"donor": donor.name})
        self.assertEqual(len(agreements), 1)
        self.track_doc("Periodic Donation Agreement", agreements[0].name)

        errors = frappe.get_all(
            "Error Log",
            filters={"method": "Agreement Email Error", "creation": [">", before]},
        )
        self.assertTrue(errors, "the induced email failure should have been logged, not silently lost")
