# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

"""
Supplementary coverage tests for the Donation DocType controller.

These complement test_donation.py and target previously-uncovered branches in
verenigingen/verenigingen/doctype/donation/donation.py:
  - validate_payment_method (SEPA/Bank Transfer recommendation paths)
  - validate_periodic_donation_agreement (non-active/non-completed status throw)
  - validate_donation_purpose (guest Specific-Goal fallback to General)
  - module funcs: create_donor_from_donation (defaults), create_mode_of_payment,
    update_campaign_progress hook, get_company_for_donations,
    generate_anbi_agreement_number sequence edge cases, get_donor_by_email
    deprecation, send_donation_confirmation_email / send_payment_confirmation_email.

All real-DB integration tests. No business logic is mocked. External email
delivery (frappe.sendmail) is the only thing patched, matching the existing
test_donation.py convention.
"""

from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestDonationCoverage(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        companies = frappe.get_all("Company", limit=1)
        self.test_company = companies[0].name if companies else "_Test Company"
        self.test_donor = self._make_donor()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _ensure_mode_of_payment(self, name="Test Payment"):
        if not frappe.db.exists("Mode of Payment", name):
            mode = frappe.new_doc("Mode of Payment")
            mode.mode_of_payment = name
            mode.insert()
        return name

    def _make_donor(self, **overrides):
        donor = frappe.new_doc("Donor")
        donor.donor_name = overrides.pop(
            "donor_name", f"Cov Donor {self.test_run_id} {frappe.generate_hash()[:6]}"
        )
        donor.donor_type = overrides.pop("donor_type", "Individual")
        donor.donor_email = overrides.pop(
            "donor_email", f"cov-{self.test_run_id}-{frappe.generate_hash()[:6]}@example.com"
        )
        for key, value in overrides.items():
            setattr(donor, key, value)
        donor.insert()
        return donor

    def _make_donation(self, **overrides):
        donation = frappe.new_doc("Donation")
        donation.donor = overrides.pop("donor", self.test_donor.name)
        donation.amount = overrides.pop("amount", 100)
        donation.donation_date = overrides.pop("donation_date", frappe.utils.today())
        donation.company = overrides.pop("company", self.test_company)
        donation.mode_of_payment = overrides.pop("mode_of_payment", self._ensure_mode_of_payment())
        for key, value in overrides.items():
            setattr(donation, key, value)
        return donation

    def _insert_donation(self, **overrides):
        donation = self._make_donation(**overrides)
        with patch("frappe.sendmail"):
            donation.insert()
        return donation

    # ------------------------------------------------------------------
    # validate_payment_method()
    # ------------------------------------------------------------------
    def test_sepa_recurring_without_mandate_msgprints_but_saves(self):
        """SEPA Direct Debit on a Recurring donation with no mandate is a soft
        recommendation (msgprint), not a hard failure: the donation still saves."""
        self._ensure_mode_of_payment("SEPA Direct Debit")
        donation = self._insert_donation(
            mode_of_payment="SEPA Direct Debit",
            status="Recurring",
        )
        donation.reload()
        self.assertEqual(donation.mode_of_payment, "SEPA Direct Debit")
        self.assertEqual(donation.status, "Recurring")

    def test_bank_transfer_paid_without_reference_saves(self):
        """A paid Bank Transfer donation without a bank_reference is a soft
        recommendation only and still persists."""
        self._ensure_mode_of_payment("Bank Transfer")
        donation = self._insert_donation(
            mode_of_payment="Bank Transfer",
            paid=1,
        )
        donation.reload()
        self.assertEqual(donation.paid, 1)
        self.assertEqual(donation.mode_of_payment, "Bank Transfer")

    # ------------------------------------------------------------------
    # validate_periodic_donation_agreement() — status branch
    # ------------------------------------------------------------------
    def _create_active_agreement(self, donor):
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.donor = donor.name
        agreement.start_date = frappe.utils.today()
        agreement.agreement_duration_years = "5 Years (ANBI Minimum)"
        agreement.annual_amount = 1200
        agreement.payment_frequency = "Monthly"
        agreement.payment_method = "Bank Transfer"
        agreement.insert()
        return agreement

    def test_periodic_agreement_draft_status_throws(self):
        """Linking a donation to a non-Active/non-Completed (Draft) agreement is rejected."""
        donor = self._make_donor(
            anbi_consent=1,
            anbi_consent_date=frappe.utils.today(),
            identification_verified=1,
            identification_verification_date=frappe.utils.today(),
            identification_verification_method="DigiD",
            bsn_citizen_service_number="123456782",
        )
        agreement = self._create_active_agreement(donor)
        # Leave it in its default (Draft) status — do not activate.
        self.assertNotIn(agreement.status, ["Active", "Completed"])

        donation = self._make_donation(
            donor=donor.name,
            periodic_donation_agreement=agreement.name,
        )
        with self.assertRaises(frappe.ValidationError):
            with patch("frappe.sendmail"):
                donation.insert()

    # ------------------------------------------------------------------
    # validate_donation_purpose() — guest Specific-Goal fallback
    # ------------------------------------------------------------------
    def test_specific_goal_without_description_falls_back_to_general_for_guest(self):
        """For a user without write permission, a Specific Goal donation with no
        description gracefully falls back to General instead of throwing."""
        donation = self._make_donation(donation_purpose_type="Specific Goal")
        # Exercise the guest fallback branch: when the session user is Guest (no
        # Donation write permission), validate_donation_purpose() coerces the
        # purpose to General instead of throwing. Call the method directly under
        # the Guest user rather than inserting (Guest cannot insert Donation).
        original_user = frappe.session.user
        try:
            frappe.set_user("Guest")
            donation.validate_donation_purpose()
        finally:
            frappe.set_user(original_user)
        self.assertEqual(donation.donation_purpose_type, "General")

    # ------------------------------------------------------------------
    # get_earmarking_summary() — Campaign + fallback branches
    # ------------------------------------------------------------------
    def test_earmarking_summary_campaign(self):
        """Campaign donations summarize with the campaign link value."""
        campaign = self._make_campaign()
        donation = self._insert_donation(donation_purpose_type="Campaign", campaign=campaign.name)
        self.assertEqual(donation.get_earmarking_summary(), f"Campaign: {campaign.name}")

    def _make_campaign(self):
        campaign = frappe.new_doc("Donation Campaign")
        campaign.campaign_name = f"Cov Campaign {self.test_run_id} {frappe.generate_hash()[:6]}"
        campaign.campaign_type = "Project Funding"
        campaign.status = "Active"
        campaign.start_date = frappe.utils.today()
        campaign.insert()
        return campaign

    # ------------------------------------------------------------------
    # create_donor_from_donation() — phone default empty
    # ------------------------------------------------------------------
    def test_create_donor_from_donation_phone_defaults_empty(self):
        """Omitting phone stores an empty string, not None."""
        from verenigingen.verenigingen.doctype.donation.donation import create_donor_from_donation

        email = f"nophone-{self.test_run_id}-{frappe.generate_hash()[:6]}@example.com"
        donor = create_donor_from_donation(donor_name="No Phone Donor", email=email, donor_type="Individual")
        self.assertEqual(donor.phone, "")

    # ------------------------------------------------------------------
    # create_mode_of_payment()
    # ------------------------------------------------------------------
    def test_create_mode_of_payment_creates_when_missing(self):
        """create_mode_of_payment inserts a Mode of Payment that does not exist."""
        from verenigingen.verenigingen.doctype.donation.donation import create_mode_of_payment

        name = f"Cov MoP {frappe.generate_hash()[:8]}"
        self.assertFalse(frappe.db.exists("Mode of Payment", name))
        create_mode_of_payment(name)
        self.assertTrue(frappe.db.exists("Mode of Payment", name))

    def test_create_mode_of_payment_noop_when_exists(self):
        """create_mode_of_payment is a no-op (does not raise) when it already exists."""
        from verenigingen.verenigingen.doctype.donation.donation import create_mode_of_payment

        name = self._ensure_mode_of_payment("Test Payment")
        # Should not raise on a duplicate.
        create_mode_of_payment(name)
        self.assertTrue(frappe.db.exists("Mode of Payment", name))

    # ------------------------------------------------------------------
    # get_company_for_donations()
    # ------------------------------------------------------------------
    def test_get_company_for_donations(self):
        from verenigingen.verenigingen.doctype.donation.donation import get_company_for_donations

        company = get_company_for_donations()
        self.assertTrue(company)
        self.assertTrue(frappe.db.exists("Company", company))

    # ------------------------------------------------------------------
    # generate_anbi_agreement_number() — malformed-latest fallback
    # ------------------------------------------------------------------
    def test_generate_anbi_agreement_number_fallback_on_malformed_latest(self):
        """When the latest stored ANBI number is malformed (no -NNN suffix), the
        generator falls back to the current year sequence 001."""
        from frappe.utils import getdate

        from verenigingen.verenigingen.doctype.donation.donation import generate_anbi_agreement_number

        # Persist a donation whose ANBI number cannot be split into 3 parts.
        self._insert_donation(
            anbi_agreement_number="MALFORMED",
            anbi_agreement_date=frappe.utils.today(),
        )
        number = generate_anbi_agreement_number()
        self.assertEqual(number, f"ANBI-{getdate().year}-001")

    # ------------------------------------------------------------------
    # get_donor_by_email() — deprecation wrapper
    # ------------------------------------------------------------------
    def test_get_donor_by_email_deprecated_returns_donor(self):
        """The deprecated module-level get_donor_by_email warns but still resolves
        an existing donor by email."""
        import warnings

        from verenigingen.verenigingen.doctype.donation.donation import get_donor_by_email

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = get_donor_by_email(self.test_donor.donor_email)

        self.assertTrue(any(issubclass(w.category, DeprecationWarning) for w in caught))
        self.assertIsNotNone(result)
        self.assertEqual(result.name, self.test_donor.name)

    # ------------------------------------------------------------------
    # update_campaign_progress(doc, method) hook
    # ------------------------------------------------------------------
    def test_update_campaign_progress_hook_updates_campaign(self):
        """The donation-side update_campaign_progress hook recalculates the linked
        campaign's totals from its paid donations."""
        from verenigingen.verenigingen.doctype.donation.donation import update_campaign_progress

        campaign = self._make_campaign()
        donation = self._insert_donation(
            donation_purpose_type="Campaign", campaign=campaign.name, paid=1, amount=75
        )
        with self.assertNoErrorLog():
            update_campaign_progress(donation, "on_update")

        campaign.reload()
        self.assertEqual(campaign.total_donations, 1)
        self.assertEqual(campaign.total_raised, 75)

    def test_update_campaign_progress_hook_noop_when_unpaid(self):
        """The hook does nothing when the donation is not paid."""
        from verenigingen.verenigingen.doctype.donation.donation import update_campaign_progress

        campaign = self._make_campaign()
        donation = self._insert_donation(
            donation_purpose_type="Campaign", campaign=campaign.name, paid=0, amount=75
        )
        update_campaign_progress(donation, "on_update")
        campaign.reload()
        # Campaign was never recomputed by the hook (unpaid short-circuit).
        self.assertEqual(campaign.total_raised or 0, 0)

    # ------------------------------------------------------------------
    # send_donation_confirmation_email() / send_payment_confirmation_email()
    # ------------------------------------------------------------------
    def test_send_donation_confirmation_false_for_missing_donation(self):
        """Returns False for a non-existent donation id (no Error Log)."""
        from verenigingen.verenigingen.doctype.donation.donation import send_donation_confirmation_email

        with self.assertNoErrorLog():
            self.assertFalse(send_donation_confirmation_email(f"NOPE-{frappe.generate_hash()[:8]}"))

    def test_send_donation_confirmation_false_when_donor_has_no_email(self):
        """Returns False and logs an error when the donor has no email address."""
        from verenigingen.verenigingen.doctype.donation.donation import send_donation_confirmation_email

        donor = self._make_donor()
        # Strip the email so the no-email branch (which logs) is exercised.
        frappe.db.set_value("Donor", donor.name, "donor_email", "")
        donation = self._insert_donation(donor=donor.name)

        # The no-email branch intentionally logs an Error Log row; mark it
        # expected so the automatic tearDown check does not fail the test.
        self.expectErrorLog("No email address for donor")
        result = send_donation_confirmation_email(donation.name)
        self.assertFalse(result)

    def test_send_payment_confirmation_false_for_missing_donation(self):
        """Payment confirmation returns False for a non-existent donation id."""
        from verenigingen.verenigingen.doctype.donation.donation import send_payment_confirmation_email

        with self.assertNoErrorLog():
            self.assertFalse(send_payment_confirmation_email(f"NOPE-{frappe.generate_hash()[:8]}"))

    def test_send_payment_confirmation_false_when_donor_has_no_email(self):
        """Payment confirmation returns False (no Error Log) when donor has no email."""
        from verenigingen.verenigingen.doctype.donation.donation import send_payment_confirmation_email

        donor = self._make_donor()
        frappe.db.set_value("Donor", donor.name, "donor_email", "")
        donation = self._insert_donation(donor=donor.name)

        # send_payment_confirmation_email returns False on no-email WITHOUT logging.
        with self.assertNoErrorLog():
            result = send_payment_confirmation_email(donation.name)
        self.assertFalse(result)
