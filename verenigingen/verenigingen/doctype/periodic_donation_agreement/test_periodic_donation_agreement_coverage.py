"""
Coverage-focused real-DB integration tests for the Periodic Donation Agreement
controller (``periodic_donation_agreement.py``).

These complement the existing workflow tests in
``verenigingen/tests/backend/workflows/test_periodic_donation_agreement.py`` by
driving the branches that were previously uncovered: lifetime/end-date
calculation, ANBI eligibility toggling against ``enable_anbi_functionality``,
the donation-tracking aggregation, the duration parser (incl. the previously
dead settings-default branch), commitment-type/tax-year derivation, the
next-donation-date cap, and the link/cancel whitelisted methods.

No business logic is mocked. The ANBI setting is toggled deterministically via
``frappe.db.set_single_value`` and relies on per-test rollback (EnhancedTestCase
/ FrappeTestCase) for restoration.
"""

import frappe
from frappe.utils import add_months, add_years, getdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPeriodicDonationAgreementCoverage(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        # A donor with an email so the after_insert confirmation path has a
        # recipient; the email service swallows delivery problems internally.
        self.donor = self.create_test_donor(
            donor_name=f"PDA Cov Donor {frappe.generate_hash(length=6)}",
            donor_email=f"pdacov.{frappe.generate_hash(length=6)}@example.invalid",
        )

    # ------------------------------------------------------------------ helpers

    def _set_anbi(self, enabled):
        frappe.db.set_single_value("Verenigingen Settings", "enable_anbi_functionality", 1 if enabled else 0)

    def _new_agreement(self, **kwargs):
        defaults = {
            "donor": self.donor.name,
            "agreement_type": "Private Written",
            "start_date": today(),
            "annual_amount": 1200,
            "payment_frequency": "Monthly",
            "payment_method": "Bank Transfer",
            "status": "Draft",
            "agreement_duration_years": "5 Years (ANBI Minimum)",
        }
        defaults.update(kwargs)
        agreement = frappe.new_doc("Periodic Donation Agreement")
        for k, v in defaults.items():
            setattr(agreement, k, v)
        return agreement

    # ------------------------------------------------------------------ end-date / payment amount

    def test_calculate_end_date_for_fixed_term(self):
        """A 5-year agreement gets end_date = start + 5 years."""
        self._set_anbi(True)
        agreement = self._new_agreement(start_date="2025-01-01")
        agreement.calculate_end_date()
        self.assertEqual(agreement.end_date, "2030-01-01")

    def test_calculate_end_date_lifetime_leaves_end_date_empty(self):
        """Lifetime agreements (duration -1) leave end_date unset."""
        self._set_anbi(True)
        agreement = self._new_agreement(agreement_duration_years="Lifetime (ANBI)")
        agreement.calculate_end_date()
        self.assertFalse(agreement.end_date)

    def test_calculate_payment_amount_quarterly(self):
        agreement = self._new_agreement(annual_amount=1200, payment_frequency="Quarterly")
        agreement.calculate_payment_amount()
        self.assertEqual(agreement.payment_amount, 300)

    def test_calculate_payment_amount_annually(self):
        agreement = self._new_agreement(annual_amount=900, payment_frequency="Annually")
        agreement.calculate_payment_amount()
        self.assertEqual(agreement.payment_amount, 900)

    # ------------------------------------------------------------------ validate_dates

    def test_end_before_start_throws(self):
        """End date must be after start date for a fixed-term, non-ANBI pledge."""
        self._set_anbi(False)
        agreement = self._new_agreement(
            agreement_duration_years="1 Year (Pledge - No ANBI benefits)",
            anbi_eligible=0,
            start_date="2025-06-01",
            end_date="2025-01-01",
        )
        with self.assertRaises(frappe.ValidationError):
            agreement.validate_dates()

    def test_non_anbi_under_one_year_throws(self):
        """A non-ANBI pledge spanning < 1 year is rejected."""
        self._set_anbi(False)
        agreement = self._new_agreement(
            agreement_duration_years="1 Year (Pledge - No ANBI benefits)",
            anbi_eligible=0,
            start_date="2025-01-01",
            end_date="2025-06-01",
        )
        with self.assertRaises(frappe.ValidationError):
            agreement.validate_dates()

    def test_anbi_under_five_years_throws(self):
        """An ANBI agreement spanning < 5 years is rejected."""
        self._set_anbi(True)
        agreement = self._new_agreement(
            agreement_duration_years="5 Years (ANBI Minimum)",
            anbi_eligible=1,
            start_date="2025-01-01",
            end_date="2027-01-01",  # only 2 years
        )
        with self.assertRaises(frappe.ValidationError):
            agreement.validate_dates()

    def test_validate_dates_lifetime_sets_anbi_eligible_when_enabled(self):
        """Lifetime + ANBI enabled -> validate_dates marks the agreement eligible."""
        self._set_anbi(True)
        agreement = self._new_agreement(agreement_duration_years="Lifetime (ANBI)", anbi_eligible=0)
        agreement.validate_dates()
        self.assertEqual(agreement.anbi_eligible, 1)

    # ------------------------------------------------------------------ validate_annual_amount

    def test_annual_amount_none_throws(self):
        agreement = self._new_agreement(annual_amount=None)
        with self.assertRaises(frappe.ValidationError):
            agreement.validate_annual_amount()

    def test_annual_amount_zero_throws(self):
        agreement = self._new_agreement(annual_amount=0)
        with self.assertRaises(frappe.ValidationError):
            agreement.validate_annual_amount()

    # ------------------------------------------------------------------ update_donation_tracking

    def test_update_donation_tracking_aggregates_paid_rows(self):
        """Only Paid child rows count; totals/count/last-date are computed."""
        agreement = self._new_agreement()
        agreement.append("donations", {"date": "2025-01-10", "amount": 100, "status": "Paid"})
        agreement.append("donations", {"date": "2025-03-10", "amount": 150, "status": "Paid"})
        agreement.append("donations", {"date": "2025-04-10", "amount": 999, "status": "Unpaid"})
        agreement.update_donation_tracking()
        self.assertEqual(agreement.total_donated, 250)
        self.assertEqual(agreement.donations_count, 2)
        self.assertEqual(getdate(agreement.last_donation_date), getdate("2025-03-10"))

    # ------------------------------------------------------------------ get_agreement_duration parser

    def test_get_agreement_duration_parses_years(self):
        agreement = self._new_agreement(agreement_duration_years="10 Years (ANBI)")
        self.assertEqual(agreement.get_agreement_duration(), 10)

    def test_get_agreement_duration_lifetime(self):
        agreement = self._new_agreement(agreement_duration_years="Lifetime (ANBI)")
        self.assertEqual(agreement.get_agreement_duration(), -1)

    def test_get_agreement_duration_default_uses_settings_when_not_anbi(self):
        """When no duration is set and the agreement is NOT ANBI-eligible, the
        duration falls back to the settings default (default 1) -- this branch
        was previously dead because the code referenced the bound method object
        (always truthy) instead of calling it."""
        agreement = self._new_agreement(agreement_duration_years=None, anbi_eligible=0)
        # default_agreement_duration is unset on Verenigingen Settings -> 1.
        self.assertEqual(agreement.get_agreement_duration(), 1)

    def test_get_agreement_duration_default_five_when_anbi(self):
        agreement = self._new_agreement(agreement_duration_years=None, anbi_eligible=1)
        self.assertEqual(agreement.get_agreement_duration(), 5)

    # ------------------------------------------------------------------ calculate_duration_years

    def test_calculate_duration_years(self):
        agreement = self._new_agreement(start_date="2025-01-01", end_date="2030-01-01")
        self.assertAlmostEqual(agreement.calculate_duration_years(), 5.0, places=2)

    def test_calculate_duration_years_zero_without_dates(self):
        agreement = self._new_agreement(start_date=None, end_date=None)
        self.assertEqual(agreement.calculate_duration_years(), 0)

    # ------------------------------------------------------------------ is_anbi_eligible

    def test_is_anbi_eligible_reflects_field(self):
        self.assertTrue(self._new_agreement(anbi_eligible=1).is_anbi_eligible())
        self.assertFalse(self._new_agreement(anbi_eligible=0).is_anbi_eligible())

    # ------------------------------------------------------------------ set_commitment_type

    def test_set_commitment_type_anbi(self):
        agreement = self._new_agreement(agreement_duration_years="5 Years (ANBI Minimum)", anbi_eligible=1)
        agreement.set_commitment_type()
        self.assertEqual(agreement.commitment_type, "ANBI Periodic Donation Agreement")

    def test_set_commitment_type_pledge(self):
        agreement = self._new_agreement(
            agreement_duration_years="2 Years (Pledge - No ANBI benefits)", anbi_eligible=0
        )
        agreement.set_commitment_type()
        self.assertEqual(agreement.commitment_type, "Donation Pledge (No ANBI Tax Benefits)")

    # ------------------------------------------------------------------ set_default_tax_year

    def test_set_default_tax_year_from_start_year(self):
        agreement = self._new_agreement(anbi_eligible=1, start_date=f"{getdate(today()).year}-03-01")
        agreement.tax_year_applicable = None
        agreement.set_default_tax_year()
        self.assertEqual(agreement.tax_year_applicable, getdate(today()).year)

    def test_set_default_tax_year_skipped_when_not_anbi(self):
        agreement = self._new_agreement(anbi_eligible=0)
        agreement.tax_year_applicable = None
        agreement.set_default_tax_year()
        self.assertIsNone(agreement.tax_year_applicable)

    # ------------------------------------------------------------------ update_anbi_eligibility

    def test_update_anbi_eligibility_fails_closed_when_disabled(self):
        """ANBI functionality off -> eligibility forced to 0 regardless of claim."""
        self._set_anbi(False)
        agreement = self._new_agreement(anbi_eligible=1)
        agreement.update_anbi_eligibility()
        self.assertEqual(agreement.anbi_eligible, 0)

    def test_update_anbi_eligibility_grants_for_five_year_when_enabled(self):
        self._set_anbi(True)
        agreement = self._new_agreement(agreement_duration_years="5 Years (ANBI Minimum)", anbi_eligible=0)
        agreement.update_anbi_eligibility()
        self.assertEqual(agreement.anbi_eligible, 1)

    def test_update_anbi_eligibility_denies_short_term_even_when_enabled(self):
        self._set_anbi(True)
        agreement = self._new_agreement(
            agreement_duration_years="2 Years (Pledge - No ANBI benefits)", anbi_eligible=1
        )
        agreement.update_anbi_eligibility()
        self.assertEqual(agreement.anbi_eligible, 0)

    # ------------------------------------------------------------------ validate_anbi_eligibility basic guards

    def test_validate_anbi_eligibility_requires_donor(self):
        agreement = self._new_agreement(anbi_eligible=0)
        agreement.donor = None
        with self.assertRaises(frappe.ValidationError):
            agreement.validate_anbi_eligibility()

    def test_validate_anbi_eligibility_requires_amount(self):
        agreement = self._new_agreement(anbi_eligible=0, annual_amount=0)
        with self.assertRaises(frappe.ValidationError):
            agreement.validate_anbi_eligibility()

    def test_validate_anbi_eligibility_non_anbi_passes(self):
        """A non-ANBI agreement with donor+amount returns without invoking the
        full ANBI validation service."""
        agreement = self._new_agreement(anbi_eligible=0)
        # Should simply not raise.
        agreement.validate_anbi_eligibility()

    # ------------------------------------------------------------------ _validate_anbi_claim_against_system_rules

    def test_validate_anbi_claim_disabled_throws(self):
        self._set_anbi(False)
        agreement = self._new_agreement(anbi_eligible=1)
        with self.assertRaises(frappe.ValidationError):
            agreement._validate_anbi_claim_against_system_rules()

    def test_validate_anbi_claim_short_duration_throws(self):
        self._set_anbi(True)
        agreement = self._new_agreement(
            agreement_duration_years="2 Years (Pledge - No ANBI benefits)", anbi_eligible=1
        )
        with self.assertRaises(frappe.ValidationError):
            agreement._validate_anbi_claim_against_system_rules()

    # ------------------------------------------------------------------ generate_agreement_number

    def test_generate_agreement_number_format(self):
        self._set_anbi(True)
        agreement = self._new_agreement()
        number = agreement.generate_agreement_number()
        year = getdate(today()).year
        self.assertTrue(number.startswith(f"PDA-{year}-"))
        # 5-digit zero-padded sequence
        self.assertRegex(number, rf"^PDA-{year}-\d{{5}}$")

    # ------------------------------------------------------------------ calculate_next_donation_date

    def test_next_donation_date_first_is_start_date(self):
        agreement = self._new_agreement()
        agreement.last_donation_date = None
        agreement.calculate_next_donation_date()
        self.assertEqual(getdate(agreement.next_expected_donation), getdate(agreement.start_date))

    def test_next_donation_date_monthly_increment(self):
        agreement = self._new_agreement(payment_frequency="Monthly", end_date=None)
        agreement.last_donation_date = "2025-01-15"
        agreement.calculate_next_donation_date()
        self.assertEqual(getdate(agreement.next_expected_donation), add_months(getdate("2025-01-15"), 1))

    def test_next_donation_date_capped_by_end_date(self):
        """If the computed next date is past end_date, next_expected is cleared."""
        agreement = self._new_agreement(payment_frequency="Annually", end_date="2025-06-01")
        agreement.last_donation_date = "2025-01-15"
        agreement.calculate_next_donation_date()
        self.assertIsNone(agreement.next_expected_donation)

    # ------------------------------------------------------------------ full validate() chain via insert

    def test_full_insert_active_anbi_agreement(self):
        """Insert exercises validate()+before_insert()+after_insert(); the
        derived fields are persisted and no error is logged. Requires a fully
        ANBI-compliant donor (consent + BSN) since validate_anbi_eligibility
        delegates to the real ANBIValidationService."""
        self._set_anbi(True)
        # Make THIS donor ANBI-compliant: consent + tax identifier.
        self.donor.db_set("anbi_consent", 1)
        self.donor.db_set("anbi_consent_date", frappe.utils.now())
        self.donor.db_set("bsn_citizen_service_number", "111222333")
        self.donor.reload()
        with self.assertNoErrorLog():
            agreement = self._new_agreement(status="Active", anbi_eligible=1)
            agreement.insert()
        self.track_doc("Periodic Donation Agreement", agreement.name)
        agreement.reload()
        self.assertEqual(agreement.payment_amount, 100)  # 1200 / 12
        self.assertEqual(agreement.end_date and getdate(agreement.end_date).year, getdate(today()).year + 5)
        self.assertEqual(agreement.commitment_type, "ANBI Periodic Donation Agreement")
        self.assertTrue(agreement.agreement_number)

    # ------------------------------------------------------------------ link_donation

    def test_link_donation_appends_row_and_links_back(self):
        self._set_anbi(False)
        agreement = self._new_agreement(status="Active", anbi_eligible=0)
        agreement.insert()
        self.track_doc("Periodic Donation Agreement", agreement.name)

        donation = self.create_test_donation(donor=self.donor.name, amount=100, paid=1)
        self.track_doc("Donation", donation.name)

        result = agreement.link_donation(donation.name)
        self.assertTrue(result)
        agreement.reload()
        self.assertTrue(any(d.donation == donation.name for d in agreement.donations))
        row = next(d for d in agreement.donations if d.donation == donation.name)
        self.assertEqual(getdate(row.date), getdate(donation.donation_date))
        self.assertEqual(row.status, "Paid")
        donation.reload()
        self.assertEqual(donation.periodic_donation_agreement, agreement.name)

    def test_link_donation_donor_mismatch_throws(self):
        self._set_anbi(False)
        agreement = self._new_agreement(status="Active", anbi_eligible=0)
        agreement.insert()
        self.track_doc("Periodic Donation Agreement", agreement.name)

        other_donor = self.create_test_donor(donor_name=f"Other {frappe.generate_hash(length=6)}")
        donation = self.create_test_donation(donor=other_donor.name, amount=50, paid=1)
        self.track_doc("Donation", donation.name)

        with self.assertRaises(frappe.ValidationError):
            agreement.link_donation(donation.name)

    def test_link_donation_already_linked_throws(self):
        self._set_anbi(False)
        agreement = self._new_agreement(status="Active", anbi_eligible=0)
        agreement.insert()
        self.track_doc("Periodic Donation Agreement", agreement.name)
        donation = self.create_test_donation(donor=self.donor.name, amount=100, paid=1)
        self.track_doc("Donation", donation.name)

        agreement.link_donation(donation.name)
        agreement.reload()
        with self.assertRaises(frappe.ValidationError):
            agreement.link_donation(donation.name)

    # ------------------------------------------------------------------ cancel_agreement

    def test_cancel_agreement_sets_fields(self):
        self._set_anbi(False)
        agreement = self._new_agreement(status="Active", anbi_eligible=0)
        agreement.insert()
        self.track_doc("Periodic Donation Agreement", agreement.name)

        result = agreement.cancel_agreement(reason="No longer able to donate")
        self.assertTrue(result)
        agreement.reload()
        self.assertEqual(agreement.status, "Cancelled")
        self.assertEqual(getdate(agreement.cancellation_date), getdate(today()))
        self.assertEqual(agreement.cancellation_reason, "No longer able to donate")
        self.assertEqual(agreement.cancellation_processed_by, frappe.session.user)

    def test_cancel_agreement_default_reason(self):
        self._set_anbi(False)
        agreement = self._new_agreement(status="Active", anbi_eligible=0)
        agreement.insert()
        self.track_doc("Periodic Donation Agreement", agreement.name)
        agreement.cancel_agreement()
        agreement.reload()
        self.assertTrue(agreement.cancellation_reason)

    def test_cancel_already_cancelled_throws(self):
        self._set_anbi(False)
        agreement = self._new_agreement(status="Active", anbi_eligible=0)
        agreement.insert()
        self.track_doc("Periodic Donation Agreement", agreement.name)
        agreement.cancel_agreement()
        agreement.reload()
        with self.assertRaises(frappe.ValidationError):
            agreement.cancel_agreement()
