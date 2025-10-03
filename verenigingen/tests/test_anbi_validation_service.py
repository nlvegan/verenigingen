"""
Integration tests for ANBI Validation Service

Tests comprehensive Dutch tax law validation for ANBI periodic donation agreements.
"""

import unittest

import frappe
from frappe.utils import add_years, today

from verenigingen.services.anbi_validation_service import ANBIValidationService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestANBIValidationService(EnhancedTestCase):
    """Test ANBI validation service with realistic Dutch tax scenarios"""

    def setUp(self):
        """Set up test environment"""
        super().setUp()
        self.validator = ANBIValidationService()

        # Enable ANBI functionality in settings
        # Note: enable_anbi_functionality serves dual purpose - enables feature
        # and indicates organization has valid ANBI registration
        settings = frappe.get_single("Verenigingen Settings")
        settings.enable_anbi_functionality = 1
        settings.anbi_minimum_reportable_amount = 500
        settings.save()

    def test_system_anbi_enabled_validation(self):
        """Test ANBI functionality enabled check"""
        is_valid, error = self.validator.validate_system_anbi_enabled()
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_system_anbi_disabled(self):
        """Test validation fails when ANBI disabled"""
        settings = frappe.get_single("Verenigingen Settings")
        settings.enable_anbi_functionality = 0
        settings.save()

        is_valid, error = self.validator.validate_system_anbi_enabled()
        self.assertFalse(is_valid)
        self.assertIn("disabled", error.lower())

    def test_organization_anbi_status_validation(self):
        """Test organization ANBI registration check"""
        is_valid, error = self.validator.validate_organization_anbi_status()
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_organization_no_anbi_status(self):
        """Test validation fails when org lacks ANBI status (ANBI disabled)"""
        # When ANBI functionality is disabled, it implies org doesn't have ANBI status
        settings = frappe.get_single("Verenigingen Settings")
        settings.enable_anbi_functionality = 0  # Disabling implies no ANBI registration
        settings.save()

        is_valid, error = self.validator.validate_organization_anbi_status()
        self.assertFalse(is_valid)
        self.assertIn("registration", error.lower())

    def test_donor_consent_validation_success(self):
        """Test donor with valid ANBI consent"""
        donor = self.create_test_donor(
            donor_name="Test ANBI Donor",
            donor_email="anbi@example.com",
            donor_type="Individual",
            anbi_consent=1
        )

        is_valid, error = self.validator.validate_donor_consent(donor)
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_donor_consent_validation_failure(self):
        """Test donor without ANBI consent fails"""
        donor = self.create_test_donor(
            donor_name="No Consent Donor",
            donor_email="noconsent@example.com",
            donor_type="Individual",
            anbi_consent=0
        )

        is_valid, error = self.validator.validate_donor_consent(donor)
        self.assertFalse(is_valid)
        self.assertIn("consent", error.lower())

    def test_individual_donor_bsn_required(self):
        """Test individual donor requires BSN"""
        from verenigingen.utils.secure_operations import secure_document_operation

        # Create donor without BSN to test validation
        donor = frappe.get_doc({
            "doctype": "Donor",
            "donor_name": "Individual No BSN",
            "donor_email": "nobsn@example.com",
            "donor_type": "Individual",
            "anbi_consent": 1,
            "currency": "EUR"
            # Explicitly no BSN field
        })
        donor.flags.ignore_validate = True  # Skip BSN validation during insert

        result = secure_document_operation(
            operation="insert",
            doc=donor,
            justification="Test ANBI validation for donor without BSN",
            required_permissions=["Donor:create"]
        )

        self.assertTrue(result.success, "Failed to create test donor for validation")
        donor = result.doc

        is_valid, error = self.validator.validate_donor_tax_identifier(donor)
        self.assertFalse(is_valid)
        self.assertIn("BSN", error)

    def test_individual_donor_with_bsn_valid(self):
        """Test individual donor with BSN passes"""
        from verenigingen.tests.fixtures.dutch_validation_helpers import get_test_bsn_numbers

        donor = self.create_test_donor(
            donor_name="Individual With BSN",
            donor_email="withbsn@example.com",
            donor_type="Individual",
            anbi_consent=1,
            bsn_citizen_service_number=get_test_bsn_numbers()[0]
        )

        is_valid, error = self.validator.validate_donor_tax_identifier(donor)
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_organization_donor_rsin_required(self):
        """Test organization donor requires RSIN"""
        from verenigingen.utils.secure_operations import secure_document_operation

        # Create donor without RSIN to test validation
        donor = frappe.get_doc({
            "doctype": "Donor",
            "donor_name": "Organization No RSIN",
            "donor_email": "norsin@example.com",
            "donor_type": "Organization",
            "anbi_consent": 1,
            "currency": "EUR"
            # Explicitly no RSIN field
        })
        donor.flags.ignore_validate = True  # Skip RSIN validation during insert

        result = secure_document_operation(
            operation="insert",
            doc=donor,
            justification="Test ANBI validation for donor without RSIN",
            required_permissions=["Donor:create"]
        )

        self.assertTrue(result.success, "Failed to create test donor for validation")
        donor = result.doc

        is_valid, error = self.validator.validate_donor_tax_identifier(donor)
        self.assertFalse(is_valid)
        self.assertIn("RSIN", error)

    def test_organization_donor_with_rsin_valid(self):
        """Test organization donor with RSIN passes"""
        from verenigingen.tests.fixtures.dutch_validation_helpers import get_test_rsin_numbers

        donor = self.create_test_donor(
            donor_name="Organization With RSIN",
            donor_email="withrsin@example.com",
            donor_type="Organization",
            anbi_consent=1,
            rsin_organization_tax_number=get_test_rsin_numbers()[0]
        )

        is_valid, error = self.validator.validate_donor_tax_identifier(donor)
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_agreement_duration_minimum_5_years(self):
        """Test agreement requires minimum 5 years"""
        # 4 years - should fail
        is_valid, error = self.validator.validate_agreement_duration(4)
        self.assertFalse(is_valid)
        self.assertIn("5", error)

        # 5 years - should pass
        is_valid, error = self.validator.validate_agreement_duration(5)
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_agreement_duration_lifetime_valid(self):
        """Test lifetime agreement (-1) is valid"""
        is_valid, error = self.validator.validate_agreement_duration(-1)
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_agreement_type_requires_formal_documentation(self):
        """Test ANBI requires notarial or written agreement"""
        # Notarial - valid
        is_valid, error = self.validator.validate_agreement_type("Notarial")
        self.assertTrue(is_valid)

        # Private Written - valid
        is_valid, error = self.validator.validate_agreement_type("Private Written")
        self.assertTrue(is_valid)

        # Verbal - invalid
        is_valid, error = self.validator.validate_agreement_type("Verbal")
        self.assertFalse(is_valid)
        self.assertIn("formal", error.lower())

    def test_reportable_amount_threshold(self):
        """Test reportable amount threshold (€500)"""
        # Below threshold
        self.assertFalse(self.validator.should_mark_reportable(499.99))

        # At threshold
        self.assertTrue(self.validator.should_mark_reportable(500.00))

        # Above threshold
        self.assertTrue(self.validator.should_mark_reportable(1000.00))

    def test_full_validation_valid_agreement(self):
        """Test complete validation with valid ANBI agreement"""
        from verenigingen.tests.fixtures.dutch_validation_helpers import get_test_bsn_numbers

        # Create donor with all requirements
        donor = self.create_test_donor(
            donor_name="Valid ANBI Donor",
            donor_email="valid@example.com",
            donor_type="Individual",
            anbi_consent=1,
            bsn_citizen_service_number=get_test_bsn_numbers()[0]
        )

        # Validate 5-year agreement
        is_valid, errors = self.validator.validate_full_anbi_eligibility(
            donor_name=donor.name,
            duration_years=5,
            agreement_type="Notarial"
        )

        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)

    def test_full_validation_multiple_errors(self):
        """Test validation collects multiple errors"""
        # Create donor missing BSN and consent
        donor = self.create_test_donor(
            donor_name="Invalid Donor",
            donor_email="invalid@example.com",
            donor_type="Individual",
            anbi_consent=0  # Missing consent
            # Missing BSN
        )

        # Try to validate too-short agreement
        is_valid, errors = self.validator.validate_full_anbi_eligibility(
            donor_name=donor.name,
            duration_years=3,  # Too short
            agreement_type="Verbal"  # Invalid type
        )

        self.assertFalse(is_valid)
        # Should have multiple errors: consent, BSN, duration, agreement type
        self.assertGreater(len(errors), 2)

    def test_validation_status_dict_format(self):
        """Test validation status dictionary has correct format"""
        from verenigingen.tests.fixtures.dutch_validation_helpers import get_test_bsn_numbers

        donor = self.create_test_donor(
            donor_name="Status Test Donor",
            donor_email="status@example.com",
            donor_type="Individual",
            anbi_consent=1,
            bsn_citizen_service_number=get_test_bsn_numbers()[0]
        )

        status = self.validator.get_validation_status_dict(
            donor_name=donor.name,
            duration_years=5,
            agreement_type="Notarial"
        )

        # Check structure
        self.assertIn("valid", status)
        self.assertIn("errors", status)
        self.assertIn("warnings", status)
        self.assertIn("message", status)

        # Check types
        self.assertIsInstance(status["valid"], bool)
        self.assertIsInstance(status["errors"], list)
        self.assertIsInstance(status["message"], str)


def tearDownModule():
    """Clean up after all tests"""
    frappe.db.rollback()
