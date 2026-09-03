"""
Regression tests for
verenigingen/verenigingen/web_form/periodic_donation_agreement_form/periodic_donation_agreement_form.py
(#744, #762).

Covers two independent defects:

1. (#744) Periodic Donation Agreement.payment_method is a Select with exactly
   three options ("SEPA Direct Debit", "Bank Transfer", "Other").
   create_agreement_from_form() assigned form_data.get("payment_method")
   straight into that field with no check. This form's own dropdown only
   offers the three valid options, but the endpoint (process_agreement_form,
   @self_service_api) is reachable directly with any string, so the same
   fix applied to the API sibling (periodic_donation_operations.py) is
   applied here too.

2. (#762) create_sepa_mandate_for_agreement() could not work as written: its
   dedupe guard compared an unspaced IBAN against SEPAMandate's
   space-formatted stored value (never matches), it put a Donor name into a
   Member-only Link field, used a non-existent "Pending" status, and set a
   nonexistent "valid_from" field. Reachability check (verified live on
   test_site_1 and veg11): both Verenigingen web forms exist but are
   unpublished (published=0), and zero Periodic Donation Agreement on veg11
   has ever had a sepa_mandate set -- so this path has never actually been
   used in production. Even a spec-compliant, memberless SEPA Mandate would
   still be inert: the SEPA collection pipeline (sepa_batch_processor.py,
   mandate_candidates.py) resolves every mandate by Member, never by Donor,
   so nothing would ever collect on it. Rather than build a mandate the rest
   of the system cannot act on, SEPA Direct Debit is now refused loudly,
   before any donor/agreement side effects run.
"""

import frappe

from verenigingen.tests.fixtures.dutch_validation_helpers import generate_valid_bsn
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPeriodicDonationAgreementFormPaymentMethodMapping(EnhancedTestCase):
    """REGRESSION (#744): payment_method must be validated/mapped, not
    assigned unchecked into the agreement's 3-option Select."""

    def test_create_agreement_from_form_maps_mollie_to_other(self):
        from verenigingen.verenigingen.web_form.periodic_donation_agreement_form.periodic_donation_agreement_form import (
            create_agreement_from_form,
        )

        donor = self.create_test_donor(
            donor_type="Individual", anbi_consent=1, bsn_citizen_service_number=generate_valid_bsn()
        )
        form_data = {
            "agreement_type": "Private Written",
            "start_date": frappe.utils.today(),
            "annual_amount": 600,
            "payment_frequency": "Monthly",
            "payment_method": "Mollie",
        }

        agreement = create_agreement_from_form(donor.name, form_data)
        self.track_doc("Periodic Donation Agreement", agreement.name)

        self.assertEqual(agreement.payment_method, "Other")

    def test_create_agreement_from_form_rejects_unrecognized_payment_method(self):
        from verenigingen.verenigingen.web_form.periodic_donation_agreement_form.periodic_donation_agreement_form import (
            create_agreement_from_form,
        )

        donor = self.create_test_donor(donor_type="Individual")
        form_data = {
            "agreement_type": "Private Written",
            "start_date": frappe.utils.today(),
            "annual_amount": 600,
            "payment_frequency": "Monthly",
            "payment_method": "Bitcoin",
        }

        with self.assertRaises(frappe.ValidationError):
            create_agreement_from_form(donor.name, form_data)

        self.assertFalse(frappe.db.exists("Periodic Donation Agreement", {"donor": donor.name}))

    def test_create_agreement_from_form_accepts_valid_select_option_unchanged(self):
        from verenigingen.verenigingen.web_form.periodic_donation_agreement_form.periodic_donation_agreement_form import (
            create_agreement_from_form,
        )

        donor = self.create_test_donor(
            donor_type="Individual", anbi_consent=1, bsn_citizen_service_number=generate_valid_bsn()
        )
        form_data = {
            "agreement_type": "Private Written",
            "start_date": frappe.utils.today(),
            "annual_amount": 600,
            "payment_frequency": "Monthly",
            "payment_method": "Bank Transfer",
        }

        agreement = create_agreement_from_form(donor.name, form_data)
        self.track_doc("Periodic Donation Agreement", agreement.name)

        self.assertEqual(agreement.payment_method, "Bank Transfer")


class TestPeriodicDonationAgreementFormSepaRefusal(EnhancedTestCase):
    """REGRESSION (#762): SEPA Direct Debit must be refused loudly, before
    any donor/agreement/mandate side effects, not attempt a broken mandate
    creation."""

    def _sepa_form_data(self, **overrides):
        data = {
            "agreement_type": "Private Written",
            "start_date": frappe.utils.today(),
            "annual_amount": 600,
            "payment_frequency": "Monthly",
            "payment_method": "SEPA Direct Debit",
            "sepa_iban": "NL91 ABNA 0417 1643 00",
            "sepa_account_holder": "Test Donor",
            "accept_five_year_term": 1,
            "accept_terms": 1,
        }
        data.update(overrides)
        return data

    def test_validate_agreement_form_data_rejects_sepa_direct_debit(self):
        from verenigingen.verenigingen.web_form.periodic_donation_agreement_form.periodic_donation_agreement_form import (
            validate_agreement_form_data,
        )

        with self.assertRaises(frappe.ValidationError):
            validate_agreement_form_data(self._sepa_form_data())

    def test_validate_agreement_form_data_still_accepts_bank_transfer(self):
        from verenigingen.verenigingen.web_form.periodic_donation_agreement_form.periodic_donation_agreement_form import (
            validate_agreement_form_data,
        )

        # Must not raise.
        validate_agreement_form_data(self._sepa_form_data(payment_method="Bank Transfer"))

    def test_process_agreement_form_rejects_sepa_with_no_side_effects(self):
        """Full endpoint: a SEPA Direct Debit submission must fail cleanly,
        with no Donor, Agreement, or SEPA Mandate left behind.

        process_agreement_form is @self_service_api(implicit_allowed=True),
        which requires the calling user to resolve to a Member record (see
        self_service_access_controller.get_user_member) -- so the test user
        needs a linked Member, even though the endpoint itself operates on a
        Donor derived separately via get_or_create_donor_for_user().
        """
        from verenigingen.verenigingen.web_form.periodic_donation_agreement_form.periodic_donation_agreement_form import (
            process_agreement_form,
        )

        # process_agreement_form's own except-block logs every rejection
        # (including this expected one) via frappe.log_error.
        self.expectErrorLog("Agreement Form Error")

        user_email = f"pda.sepa.test.{frappe.generate_hash(length=8)}@example.com"
        self.create_test_user(user_email, roles=["Verenigingen Member"])
        self.create_test_member(email=user_email)

        original_user = frappe.session.user
        try:
            frappe.set_user(user_email)
            result = process_agreement_form(self._sepa_form_data())
        finally:
            frappe.set_user(original_user)

        self.assertFalse(result.get("success"), f"SEPA submission should be rejected: {result}")
        self.assertIn("SEPA Direct Debit", result.get("message", ""))

        # No side effects: validate_agreement_form_data raises before
        # get_or_create_donor_for_user ever runs, so no Donor -- and
        # therefore no Agreement referencing one -- was created for this user.
        self.assertFalse(frappe.db.exists("Donor", {"donor_email": user_email}))
