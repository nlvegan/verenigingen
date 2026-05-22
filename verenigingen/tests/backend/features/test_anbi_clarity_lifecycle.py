"""
ANBI Clarity Lifecycle Tests
Tests the complete lifecycle of ANBI agreements vs pledges with clear distinction
"""

import frappe
from frappe.utils import today, add_years
from verenigingen.tests.fixtures.dutch_validation_helpers import generate_valid_bsn
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
import unittest

# Donor donor_name prefix unique to this file — _cleanup_test_data filters on it
# so cleanup never touches donors created by sibling test files.
_DONOR_PREFIX = "ANBICLARITY"


class TestANBIClarityLifecycle(EnhancedTestCase):
    """Test the ANBI clarity features through complete lifecycles"""
    
    def setUp(self):
        """Set up test environment"""
        super().setUp()
        self.test_company = frappe.db.get_single_value("Verenigingen Settings", "company") or "Test Company"
        # Donation.mode_of_payment is a mandatory Link to Mode of Payment.
        if not frappe.db.exists("Mode of Payment", "Test Payment"):
            mode = frappe.new_doc("Mode of Payment")
            mode.mode_of_payment = "Test Payment"
            mode.insert()
        # Clear residue from any prior errored run BEFORE the body runs — see
        # _cleanup_test_data for why this can't wait for tearDown.
        self._cleanup_test_data()

    def tearDown(self):
        """Clean up test data"""
        self._cleanup_test_data()
        super().tearDown()

    def _cleanup_test_data(self):
        """Delete every Donor this file creates and the agreements + donations
        linked to them.

        Run from BOTH setUp and tearDown. A prior errored run can leave
        *committed* orphan Periodic Donation Agreements behind: the agreement
        controller's after_insert hook fires for an Active agreement, and the
        old teardown (a) only swept the TEST-ANBI-/TEST-PLEDGE- prefixes,
        missing TEST-UPGRADE-/TEST-DURATION-CHANGE-, and (b) filtered
        agreements by ``donor like '%TEST-%'`` — but the agreement's ``donor``
        field holds the Donor *name* (a ``DN-YY-#####`` series id), so that
        filter never matched. Orphan ANBI agreements then trip the
        "one active ANBI agreement per donor" validation on later runs.

        The donor_name filter uses the file-specific ``_DONOR_PREFIX`` so
        cleanup only ever touches this file's donors — sibling test files
        (e.g. test_periodic_donation_agreement*) also create ``TEST-``-prefixed
        donors and must not be collateral.

        Cleaning in setUp (not just tearDown) makes each test independent of
        prior-run residue. The commit is required so the deletes persist past
        this test's transaction rollback.
        """
        test_donors = frappe.get_all(
            "Donor", filters={"donor_name": ["like", f"{_DONOR_PREFIX}-%"]}, pluck="name"
        )
        if not test_donors:
            return
        # Delete children before parents: Donation + agreement link to Donor.
        for doctype in ("Donation", "Periodic Donation Agreement"):
            for name in frappe.get_all(doctype, filters={"donor": ["in", test_donors]}, pluck="name"):
                frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
        for donor in test_donors:
            frappe.delete_doc("Donor", donor, force=True, ignore_permissions=True)
        frappe.db.commit()

    def create_test_donor(self, name_prefix="TEST"):
        """Create a test donor.

        Individual donors need a valid BSN: the ANBI agreement validation
        (anbi_validation_service.validate_donor_tax_identifier) rejects an
        Individual donor without one. ``generate_valid_bsn`` produces a BSN
        that passes Donor.validate_bsn_eleven_proof.

        donor_name carries ``_DONOR_PREFIX`` so _cleanup_test_data can find
        and remove it without touching other files' test donors.
        """
        donor = frappe.new_doc("Donor")
        donor.donor_name = f"{_DONOR_PREFIX}-{name_prefix}-{frappe.utils.random_string(5)}"
        donor.donor_email = f"test-{frappe.utils.random_string(5)}@example.com"
        donor.donor_type = "Individual"
        donor.bsn_citizen_service_number = generate_valid_bsn()
        donor.anbi_consent = 1
        donor.anbi_consent_date = today()
        donor.insert()
        return donor
    
    def test_anbi_agreement_lifecycle(self):
        """Test complete lifecycle of an ANBI agreement (5+ years)"""
        # Step 1: Create donor with ANBI consent
        donor = self.create_test_donor("TEST-ANBI")
        
        # Step 2: Create ANBI agreement (5 years)
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.donor = donor.name
        agreement.start_date = today()
        agreement.agreement_duration_years = "5 Years (ANBI Minimum)"
        agreement.annual_amount = 1200
        agreement.payment_frequency = "Monthly"
        agreement.payment_method = "Bank Transfer"
        agreement.insert()
        
        # Verify ANBI attributes
        self.assertEqual(agreement.anbi_eligible, 1)
        self.assertEqual(agreement.commitment_type, "ANBI Periodic Donation Agreement")
        self.assertEqual(agreement.get_agreement_duration(), 5)
        
        # Step 3: Activate agreement
        agreement.status = "Active"
        agreement.donor_signature_received = 1
        agreement.signed_date = today()
        agreement.save()
        
        # Step 4: Create donations linked to agreement
        donation = frappe.new_doc("Donation")
        donation.donor = donor.name
        donation.donation_date = today()
        donation.amount = 100
        donation.mode_of_payment = "Test Payment"
        donation.periodic_donation_agreement = agreement.name
        donation.company = self.test_company
        donation.insert()
        
        # Verify ANBI fields are populated
        self.assertEqual(donation.anbi_agreement_number, agreement.agreement_number)
        self.assertEqual(donation.belastingdienst_reportable, 1)
        self.assertEqual(donation.status, "Recurring")
        
        # Step 5: Test tax receipt generation readiness
        self.assertTrue(agreement.anbi_eligible)
        self.assertTrue(donor.anbi_consent)
        self.assertIsNotNone(agreement.agreement_number)
    
    def test_pledge_lifecycle(self):
        """Test complete lifecycle of a pledge (< 5 years, no ANBI benefits)"""
        # Step 1: Create donor
        donor = self.create_test_donor("TEST-PLEDGE")
        
        # Step 2: Create pledge (2 years)
        # anbi_eligible defaults to 1 on the DocType. For a <5-year pledge the
        # form JS (periodic_donation_agreement.js update_anbi_eligibility_message)
        # sets it to 0 on the duration change, so a Desk user never hits this.
        # But validate_dates() (5-year ANBI minimum) runs BEFORE
        # update_anbi_eligibility() server-side — so ANY non-Desk caller (this
        # test, a REST client, a data import) that builds a sub-5-year
        # agreement without explicitly setting anbi_eligible=0 gets the ANBI
        # error. That server-side ordering gap is a latent product concern
        # (tracked in the PR's out-of-scope notes); the test conforms to
        # current server behaviour by setting the flag the way the JS would.
        pledge = frappe.new_doc("Periodic Donation Agreement")
        pledge.donor = donor.name
        pledge.start_date = today()
        pledge.agreement_duration_years = "2 Years (Pledge - No ANBI benefits)"
        pledge.anbi_eligible = 0
        pledge.annual_amount = 600
        pledge.payment_frequency = "Quarterly"
        pledge.payment_method = "Bank Transfer"
        pledge.insert()
        
        # Verify non-ANBI attributes
        self.assertEqual(pledge.anbi_eligible, 0)
        self.assertEqual(pledge.commitment_type, "Donation Pledge (No ANBI Tax Benefits)")
        self.assertEqual(pledge.get_agreement_duration(), 2)
        
        # Step 3: Activate pledge
        pledge.status = "Active"
        pledge.save()
        
        # Step 4: Create donation linked to pledge
        donation = frappe.new_doc("Donation")
        donation.donor = donor.name
        donation.donation_date = today()
        donation.amount = 150  # Quarterly payment
        donation.mode_of_payment = "Test Payment"
        donation.periodic_donation_agreement = pledge.name
        donation.company = self.test_company
        donation.insert()
        
        # Verify standard donation handling (no special ANBI benefits)
        self.assertEqual(donation.status, "Recurring")
        # Still reportable for standard tax purposes
        self.assertEqual(donation.belastingdienst_reportable, 1)
    
    def test_upgrade_pledge_to_anbi(self):
        """Test upgrading a pledge to ANBI agreement"""
        # Create initial 2-year pledge
        donor = self.create_test_donor("TEST-UPGRADE")
        
        pledge = frappe.new_doc("Periodic Donation Agreement")
        pledge.donor = donor.name
        pledge.start_date = today()
        pledge.agreement_duration_years = "2 Years (Pledge - No ANBI benefits)"
        # See test_pledge_lifecycle: <5-year pledges created without the form
        # JS must set anbi_eligible=0 explicitly.
        pledge.anbi_eligible = 0
        pledge.annual_amount = 1200
        pledge.payment_frequency = "Monthly"
        pledge.payment_method = "Bank Transfer"
        pledge.status = "Active"
        pledge.insert()
        
        # Verify it's a pledge
        self.assertEqual(pledge.anbi_eligible, 0)
        self.assertEqual(pledge.commitment_type, "Donation Pledge (No ANBI Tax Benefits)")
        
        # Cancel the pledge
        pledge.status = "Cancelled"
        pledge.cancellation_date = today()
        pledge.cancellation_reason = "Upgrading to ANBI agreement"
        pledge.save()
        
        # Create new ANBI agreement
        anbi_agreement = frappe.new_doc("Periodic Donation Agreement")
        anbi_agreement.donor = donor.name
        anbi_agreement.start_date = today()
        anbi_agreement.agreement_duration_years = "5 Years (ANBI Minimum)"
        anbi_agreement.annual_amount = 1200
        anbi_agreement.payment_frequency = "Monthly"
        anbi_agreement.payment_method = "Bank Transfer"
        anbi_agreement.status = "Active"
        anbi_agreement.insert()
        
        # Verify it's now ANBI eligible
        self.assertEqual(anbi_agreement.anbi_eligible, 1)
        self.assertEqual(anbi_agreement.commitment_type, "ANBI Periodic Donation Agreement")
    
    def test_anbi_vs_pledge_reporting(self):
        """Test reporting differences between ANBI agreements and pledges"""
        # Create ANBI agreement
        anbi_donor = self.create_test_donor("TEST-ANBI-REPORT")
        anbi_agreement = frappe.new_doc("Periodic Donation Agreement")
        anbi_agreement.donor = anbi_donor.name
        anbi_agreement.start_date = today()
        anbi_agreement.agreement_duration_years = "5 Years (ANBI Minimum)"
        anbi_agreement.annual_amount = 1200
        anbi_agreement.payment_frequency = "Monthly"
        anbi_agreement.payment_method = "Bank Transfer"
        anbi_agreement.status = "Active"
        anbi_agreement.insert()
        
        # Create pledge
        pledge_donor = self.create_test_donor("TEST-PLEDGE-REPORT")
        pledge = frappe.new_doc("Periodic Donation Agreement")
        pledge.donor = pledge_donor.name
        pledge.start_date = today()
        pledge.agreement_duration_years = "2 Years (Pledge - No ANBI benefits)"
        # See test_pledge_lifecycle: <5-year pledges created without the form
        # JS must set anbi_eligible=0 explicitly.
        pledge.anbi_eligible = 0
        pledge.annual_amount = 600
        pledge.payment_frequency = "Monthly"
        pledge.payment_method = "Bank Transfer"
        pledge.status = "Active"
        pledge.insert()
        
        # Query ANBI agreements only
        anbi_agreements = frappe.get_all(
            "Periodic Donation Agreement",
            filters={
                "anbi_eligible": 1,
                "status": "Active"
            }
        )
        
        # Query pledges only
        pledges = frappe.get_all(
            "Periodic Donation Agreement",
            filters={
                "anbi_eligible": 0,
                "status": "Active"
            }
        )
        
        # Verify filtering works correctly
        anbi_names = [a.name for a in anbi_agreements]
        pledge_names = [p.name for p in pledges]
        
        self.assertIn(anbi_agreement.name, anbi_names)
        self.assertNotIn(pledge.name, anbi_names)
        
        self.assertIn(pledge.name, pledge_names)
        self.assertNotIn(anbi_agreement.name, pledge_names)
    
    def test_duration_change_validation(self):
        """Test validation when changing duration affects ANBI eligibility"""
        donor = self.create_test_donor("TEST-DURATION-CHANGE")
        
        # Create 5-year ANBI agreement
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.donor = donor.name
        agreement.start_date = today()
        agreement.agreement_duration_years = "5 Years (ANBI Minimum)"
        agreement.annual_amount = 1200
        agreement.payment_frequency = "Monthly"
        agreement.payment_method = "Bank Transfer"
        agreement.insert()
        
        # Verify ANBI eligible
        self.assertEqual(agreement.anbi_eligible, 1)
        
        # Try to change to 3 years while keeping ANBI eligible
        agreement.agreement_duration_years = "3 Years (Pledge - No ANBI benefits)"
        agreement.end_date = add_years(agreement.start_date, 3)
        
        # This should trigger validation error if anbi_eligible is still 1
        if agreement.anbi_eligible == 1:
            with self.assertRaises(frappe.ValidationError) as cm:
                agreement.save()
            
            error_message = str(cm.exception)
            self.assertIn("ANBI", error_message)
            self.assertIn("5 years", error_message)
    
    @unittest.skip("requires web form submission simulation — not yet implemented")
    def test_web_form_clarity(self):
        """Test that web forms properly handle ANBI vs pledge distinction"""
        # This would test the web form processing functions
        # but requires actual web form submission simulation
        pass


def run_tests():
    """Run the ANBI clarity lifecycle tests"""
    frappe.connect()
    unittest.main(module=__name__, exit=False, verbosity=2)


if __name__ == "__main__":
    run_tests()