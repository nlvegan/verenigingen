"""
Regression test for verenigingen/verenigingen/web_form/periodic_donation_agreement_form/
periodic_donation_agreement_form.py (#744).

create_agreement_from_form() assigned form_data.get("payment_method") straight onto
Periodic Donation Agreement.payment_method, a Select declaring only "SEPA Direct
Debit"/"Bank Transfer"/"Other" (periodic_donation_agreement.json). This form's own
payment_method field happens to declare the same three options, so a submission made
through the rendered form can never carry anything else -- but
submit_periodic_agreement_form() is a plain @frappe.whitelist() endpoint
(process_agreement_form, called via frappe.parse_json on a fully caller-controlled
payload), so a request bypassing the browser widget can carry an arbitrary string.
Before the fix, Frappe's _validate_selects() rejected it on insert() and agreement
creation failed. This is the second of #744's two writer sites (the first,
create_periodic_agreement() in verenigingen/api/periodic_donation_operations.py, is
covered by verenigingen/tests/backend/portal/test_donation_web_form.py and
verenigingen/tests/api/test_periodic_donation_operations.py).
"""

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.dutch_validation_helpers import generate_valid_bsn
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.web_form.periodic_donation_agreement_form.periodic_donation_agreement_form import (
    create_agreement_from_form,
)


class TestPeriodicDonationAgreementFormPaymentMethod(EnhancedTestCase):
    def test_create_agreement_from_form_accepts_out_of_vocabulary_payment_method(self):
        """A crafted payload carrying a payment_method outside this doctype's
        declared options must not fail agreement creation; the value is
        coerced onto a declared option instead."""
        donor = self.create_test_donor(
            donor_type="Individual", anbi_consent=1, bsn_citizen_service_number=generate_valid_bsn()
        )

        form_data = {
            "agreement_type": "Private Written",
            "start_date": today(),
            "annual_amount": 600,
            "payment_frequency": "Monthly",
            # Not one of this form's own three options -- only reachable by a
            # caller bypassing the rendered widget.
            "payment_method": "Crypto",
        }

        agreement = create_agreement_from_form(donor.name, form_data)
        self.track_doc("Periodic Donation Agreement", agreement.name)

        self.assertIn(agreement.payment_method, ("SEPA Direct Debit", "Bank Transfer", "Other"))
        # Persisted document must be loadable -- insert() actually succeeded.
        reloaded = frappe.get_doc("Periodic Donation Agreement", agreement.name)
        self.assertEqual(reloaded.donor, donor.name)
