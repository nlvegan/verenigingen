#!/usr/bin/env python3
"""
Unit Tests for SEPA Mandate Validation Service

Tests the SEPAMandateValidationService class methods in isolation with realistic
data generation and minimal mocking. Focuses on business logic correctness
and validation rule enforcement.

Test Coverage:
- validate_mandate_dates() with various date scenarios and edge cases
- validate_mandate_iban() with Dutch IBAN validation and BIC derivation
- validate_mandate_business_rules() constraint checking
- validate_mandate_uniqueness() conflict detection
- Edge cases: past dates, invalid IBANs, BIC derivation, business rule violations
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import timedelta

import frappe
# Use frappe's getdate() (site-timezone "today"), NOT datetime.date.today()
# (process/UTC "today"): the validation service under test compares sign dates
# against frappe.utils.getdate(), so a Python-UTC date diverges from it in the
# window after UTC midnight when the site tz is behind UTC -- intermittently
# flagging a "today" sign date as in the future.
from frappe.utils import getdate
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.services.sepa_mandate_validation_service import SEPAMandateValidationService
from verenigingen.utils.validation.iban_validator import generate_test_iban, generate_invalid_iban


class TestSEPAMandateValidationService(EnhancedTestCase):
    """Unit tests for SEPA Mandate Validation Service"""

    def setUp(self):
        """Set up test environment and service instance"""
        super().setUp()
        self.service = SEPAMandateValidationService()

    def tearDown(self):
        """Clean up after each test"""
        super().tearDown()

    def _create_mock_mandate(self, **kwargs):
        """Create a mock mandate document with default values"""
        defaults = {
            'sign_date': None,
            'expiry_date': None,
            'iban': None,
            'bic': None,
            'status': 'Draft',
            'mandate_type': 'RCUR',
            'mandate_id': None,
            'account_holder_name': None,
            'member': None,
            'name': None
        }
        defaults.update(kwargs)
        return Mock(**defaults)

    # ========================================================================
    # Tests for validate_mandate_dates()
    # ========================================================================

    def test_validate_mandate_dates_valid_range(self):
        """Test validation of valid date ranges"""
        today = getdate()
        past_date = today - timedelta(days=30)
        future_date = today + timedelta(days=365)

        mandate = self._create_mock_mandate(
            sign_date=past_date,
            expiry_date=future_date
        )

        result = self.service.validate_mandate_dates(mandate)

        self.assertTrue(result['is_valid'])
        self.assertEqual(len(result['errors']), 0)
        self.assertEqual(len(result['warnings']), 0)

    def test_validate_mandate_dates_sign_after_expiry(self):
        """Test validation when sign date is after expiry date"""
        today = getdate()
        sign_date = today - timedelta(days=10)
        expiry_date = today - timedelta(days=30)  # Earlier than sign date

        mandate = self._create_mock_mandate(
            sign_date=sign_date,
            expiry_date=expiry_date
        )

        result = self.service.validate_mandate_dates(mandate)

        self.assertFalse(result['is_valid'])
        self.assertIn('Sign date cannot be after expiry date', result['errors'][0])

    def test_validate_mandate_dates_future_sign_date(self):
        """Test validation when sign date is in the future"""
        today = getdate()
        future_sign_date = today + timedelta(days=10)

        mandate = self._create_mock_mandate(
            sign_date=future_sign_date,
            expiry_date=None
        )

        result = self.service.validate_mandate_dates(mandate)

        self.assertFalse(result['is_valid'])
        self.assertIn('Sign date cannot be in the future', result['errors'][0])

    def test_validate_mandate_dates_same_dates_allowed(self):
        """Test that same sign and expiry dates are allowed"""
        today = getdate()

        mandate = self._create_mock_mandate(
            sign_date=today,
            expiry_date=today
        )

        result = self.service.validate_mandate_dates(mandate)

        self.assertTrue(result['is_valid'])
        self.assertEqual(len(result['errors']), 0)

    def test_validate_mandate_dates_no_dates_provided(self):
        """Test validation when no dates are provided"""
        mandate = self._create_mock_mandate(
            sign_date=None,
            expiry_date=None
        )

        result = self.service.validate_mandate_dates(mandate)

        # Should be valid when no dates are provided
        self.assertTrue(result['is_valid'])
        self.assertEqual(len(result['errors']), 0)

    def test_validate_mandate_dates_only_sign_date(self):
        """Test validation with only sign date provided"""
        past_date = getdate() - timedelta(days=30)

        mandate = self._create_mock_mandate(
            sign_date=past_date,
            expiry_date=None
        )

        result = self.service.validate_mandate_dates(mandate)

        self.assertTrue(result['is_valid'])
        self.assertEqual(len(result['errors']), 0)

    def test_validate_mandate_dates_only_expiry_date(self):
        """Test validation with only expiry date provided"""
        future_date = getdate() + timedelta(days=365)

        mandate = self._create_mock_mandate(
            sign_date=None,
            expiry_date=future_date
        )

        result = self.service.validate_mandate_dates(mandate)

        # Should be valid - no constraint between missing sign date and expiry date
        self.assertTrue(result['is_valid'])

    def test_validate_mandate_dates_exception_handling(self):
        """Test exception handling in date validation"""
        mandate = self._create_mock_mandate()

        with patch('verenigingen.verenigingen_payments.services.sepa_mandate_validation_service.DateRangeValidator') as mock_validator_class:
            mock_validator_class.side_effect = Exception("Validation error")

            result = self.service.validate_mandate_dates(mandate)

            self.assertFalse(result['is_valid'])
            self.assertTrue(any('Date validation error' in error for error in result['errors']))

    # ========================================================================
    # Tests for validate_mandate_iban()
    # ========================================================================

    def test_validate_mandate_iban_valid_dutch_iban(self):
        """Test validation of valid Dutch IBAN"""
        valid_iban = generate_test_iban("INGB")  # ING Bank test IBAN

        mandate = self._create_mock_mandate(iban=valid_iban, bic=None)

        with patch('verenigingen.verenigingen_payments.services.sepa_mandate_validation_service.validate_iban') as mock_validate:
            mock_validate.return_value = {'valid': True, 'message': 'Valid IBAN'}

            with patch('verenigingen.verenigingen_payments.services.sepa_mandate_validation_service.format_iban') as mock_format:
                mock_format.return_value = valid_iban

                with patch('verenigingen.verenigingen_payments.services.sepa_mandate_validation_service.derive_bic_from_iban') as mock_bic:
                    mock_bic.return_value = 'INGBNL2A'

                    result = self.service.validate_mandate_iban(mandate)

                    self.assertTrue(result['is_valid'])
                    self.assertEqual(result['derived_bic'], 'INGBNL2A')
                    self.assertEqual(mandate.bic, 'INGBNL2A')  # Should be auto-populated

    def test_validate_mandate_iban_missing_iban(self):
        """Test validation when IBAN is missing"""
        mandate = self._create_mock_mandate(iban=None)

        result = self.service.validate_mandate_iban(mandate)

        self.assertFalse(result['is_valid'])
        self.assertIn('IBAN is required', result['errors'][0])

    def test_validate_mandate_iban_invalid_iban(self):
        """Test validation of invalid IBAN"""
        invalid_iban = generate_invalid_iban("checksum")

        mandate = self._create_mock_mandate(iban=invalid_iban)

        with patch('verenigingen.verenigingen_payments.services.sepa_mandate_validation_service.validate_iban') as mock_validate:
            mock_validate.return_value = {'valid': False, 'message': 'Invalid checksum'}

            result = self.service.validate_mandate_iban(mandate)

            self.assertFalse(result['is_valid'])
            self.assertIn('Invalid IBAN format', result['errors'][0])

    def test_validate_mandate_iban_bic_mismatch_warning(self):
        """Test warning when provided BIC doesn't match derived BIC"""
        valid_iban = generate_test_iban("INGB")

        mandate = self._create_mock_mandate(iban=valid_iban, bic='WRONG2A')

        with patch('verenigingen.verenigingen_payments.services.sepa_mandate_validation_service.validate_iban') as mock_validate:
            mock_validate.return_value = {'valid': True, 'message': 'Valid IBAN'}

            with patch('verenigingen.verenigingen_payments.services.sepa_mandate_validation_service.format_iban') as mock_format:
                mock_format.return_value = valid_iban

                with patch('verenigingen.verenigingen_payments.services.sepa_mandate_validation_service.derive_bic_from_iban') as mock_bic:
                    mock_bic.return_value = 'INGBNL2A'

                    result = self.service.validate_mandate_iban(mandate)

                    self.assertTrue(result['is_valid'])  # Still valid, but with warning
                    self.assertTrue(any('does not match derived BIC' in warning for warning in result['warnings']))

    def test_validate_mandate_iban_auto_format(self):
        """Test automatic IBAN formatting"""
        unformatted_iban = "NL91INGB0001234567"
        formatted_iban = "NL91 INGB 0001 2345 67"

        mandate = self._create_mock_mandate(iban=unformatted_iban)

        with patch('verenigingen.verenigingen_payments.services.sepa_mandate_validation_service.validate_iban') as mock_validate:
            mock_validate.return_value = {'valid': True, 'message': 'Valid IBAN'}

            with patch('verenigingen.verenigingen_payments.services.sepa_mandate_validation_service.format_iban') as mock_format:
                mock_format.return_value = formatted_iban

                with patch('verenigingen.verenigingen_payments.services.sepa_mandate_validation_service.derive_bic_from_iban') as mock_bic:
                    mock_bic.return_value = None

                    self.service.validate_mandate_iban(mandate)

                    # Should update mandate with formatted IBAN
                    self.assertEqual(mandate.iban, formatted_iban)

    def test_validate_mandate_iban_no_bic_derivation(self):
        """Test IBAN validation when BIC cannot be derived"""
        valid_iban = generate_test_iban("UNKN")  # Unknown bank code

        mandate = self._create_mock_mandate(iban=valid_iban, bic=None)

        with patch('verenigingen.verenigingen_payments.services.sepa_mandate_validation_service.validate_iban') as mock_validate:
            mock_validate.return_value = {'valid': True, 'message': 'Valid IBAN'}

            with patch('verenigingen.verenigingen_payments.services.sepa_mandate_validation_service.format_iban') as mock_format:
                mock_format.return_value = valid_iban

                with patch('verenigingen.verenigingen_payments.services.sepa_mandate_validation_service.derive_bic_from_iban') as mock_bic:
                    mock_bic.return_value = None

                    result = self.service.validate_mandate_iban(mandate)

                    self.assertTrue(result['is_valid'])
                    self.assertIsNone(result['derived_bic'])
                    self.assertIsNone(mandate.bic)

    def test_validate_mandate_iban_exception_handling(self):
        """Test exception handling in IBAN validation"""
        mandate = self._create_mock_mandate(iban="NL91INGB0001234567")

        with patch('verenigingen.verenigingen_payments.services.sepa_mandate_validation_service.validate_iban', side_effect=Exception("Validation error")):

            result = self.service.validate_mandate_iban(mandate)

            self.assertFalse(result['is_valid'])
            self.assertTrue(any('IBAN validation error' in error for error in result['errors']))

    # ========================================================================
    # Tests for validate_mandate_business_rules()
    # ========================================================================

    def test_validate_mandate_business_rules_active_mandate_valid(self):
        """Test business rules validation for valid active mandate"""
        mandate = self._create_mock_mandate(
            status='Active',
            iban='NL91 INGB 0001 2345 67',
            mandate_id='MANDATE-001',
            account_holder_name='Jan de Vries',
            member='MEMBER-001'
        )

        with patch('frappe.db.exists', return_value=True):  # Member exists

            result = self.service.validate_mandate_business_rules(mandate)

            self.assertTrue(result['is_valid'])
            self.assertEqual(len(result['errors']), 0)

    def test_validate_mandate_business_rules_active_mandate_missing_fields(self):
        """Test business rules validation for active mandate with missing required fields"""
        mandate = self._create_mock_mandate(
            status='Active',
            iban=None,  # Missing required field
            mandate_id=None,  # Missing required field
            account_holder_name=None  # Missing required field
        )

        result = self.service.validate_mandate_business_rules(mandate)

        self.assertFalse(result['is_valid'])
        self.assertEqual(len(result['errors']), 3)  # Three missing fields

    def test_validate_mandate_business_rules_ooff_mandate_long_validity(self):
        """Test business rules for one-off mandate with long validity period"""
        sign_date = getdate() - timedelta(days=10)
        expiry_date = getdate() + timedelta(days=40)  # More than 30 days

        mandate = self._create_mock_mandate(
            mandate_type='OOFF',
            sign_date=sign_date,
            expiry_date=expiry_date
        )

        result = self.service.validate_mandate_business_rules(mandate)

        self.assertTrue(result['is_valid'])  # Still valid, but with warning
        self.assertTrue(any('One-off mandate valid for' in warning for warning in result['warnings']))

    def test_validate_mandate_business_rules_member_not_exists(self):
        """Test business rules when referenced member doesn't exist"""
        mandate = self._create_mock_mandate(
            member='NON-EXISTENT-MEMBER'
        )

        with patch('frappe.db.exists', return_value=False):

            result = self.service.validate_mandate_business_rules(mandate)

            self.assertFalse(result['is_valid'])
            self.assertIn('Member NON-EXISTENT-MEMBER does not exist', result['errors'][0])

    def test_validate_mandate_business_rules_draft_mandate(self):
        """Test business rules for draft mandate (less strict requirements)"""
        mandate = self._create_mock_mandate(
            status='Draft',
            iban=None,  # Not required for draft
            mandate_id=None,  # Not required for draft
            account_holder_name=None  # Not required for draft
        )

        result = self.service.validate_mandate_business_rules(mandate)

        self.assertTrue(result['is_valid'])  # Should be valid for draft
        self.assertEqual(len(result['errors']), 0)

    def test_validate_mandate_business_rules_ooff_no_dates(self):
        """Test one-off mandate without dates (no warning)"""
        mandate = self._create_mock_mandate(
            mandate_type='OOFF',
            sign_date=None,
            expiry_date=None
        )

        result = self.service.validate_mandate_business_rules(mandate)

        self.assertTrue(result['is_valid'])
        self.assertEqual(len(result['warnings']), 0)

    def test_validate_mandate_business_rules_exception_handling(self):
        """Test exception handling in business rules validation"""
        mandate = self._create_mock_mandate(member="MEMBER-001")  # Provide member to trigger db.exists call

        with patch('frappe.db.exists', side_effect=Exception("Database error")):

            result = self.service.validate_mandate_business_rules(mandate)

            self.assertFalse(result['is_valid'])
            self.assertTrue(any('Business rule validation error' in error for error in result['errors']))

    # ========================================================================
    # Tests for validate_mandate_uniqueness()
    # ========================================================================

    def test_validate_mandate_uniqueness_unique_mandate_id(self):
        """Test uniqueness validation for unique mandate ID"""
        mandate = self._create_mock_mandate(
            mandate_id='UNIQUE-MANDATE-001',
            name='SEPA-MANDATE-001'
        )

        with patch('frappe.db.exists', return_value=None):

            result = self.service.validate_mandate_uniqueness(mandate)

            self.assertTrue(result['is_valid'])
            self.assertEqual(len(result['errors']), 0)

    def test_validate_mandate_uniqueness_duplicate_mandate_id(self):
        """Test uniqueness validation for duplicate mandate ID"""
        mandate = self._create_mock_mandate(
            mandate_id='EXISTING-MANDATE-001',
            name='SEPA-MANDATE-001'
        )

        with patch('frappe.db.exists', return_value='SEPA-MANDATE-002'):

            result = self.service.validate_mandate_uniqueness(mandate)

            self.assertFalse(result['is_valid'])
            self.assertIn('Mandate ID EXISTING-MANDATE-001 already exists', result['errors'][0])

    def test_validate_mandate_uniqueness_no_mandate_id(self):
        """Test uniqueness validation when mandate ID is not set"""
        mandate = self._create_mock_mandate(mandate_id=None)

        result = self.service.validate_mandate_uniqueness(mandate)

        # Should be valid when no mandate ID is set (will be generated later)
        self.assertTrue(result['is_valid'])

    def test_validate_mandate_uniqueness_conflicting_active_mandates(self):
        """Test detection of conflicting active mandates for same member/IBAN"""
        mandate = self._create_mock_mandate(
            member='MEMBER-001',
            iban='NL91 INGB 0001 2345 67',
            status='Active',
            name='SEPA-MANDATE-001'
        )

        # Mock SQL query to return conflicting mandate
        with patch('frappe.db.sql', return_value=[('SEPA-MANDATE-002', 'EXISTING-MANDATE-001')]):

            result = self.service.validate_mandate_uniqueness(mandate)

            self.assertTrue(result['is_valid'])  # Still valid, but with warning
            self.assertTrue(any('Member already has active mandate' in warning for warning in result['warnings']))

    def test_validate_mandate_uniqueness_no_conflict_different_status(self):
        """Test no conflict when mandate is not active"""
        mandate = self._create_mock_mandate(
            member='MEMBER-001',
            iban='NL91 INGB 0001 2345 67',
            status='Draft',  # Not active
            name='SEPA-MANDATE-001'
        )

        # Should not check for conflicting active mandates when status is not Active
        with patch('frappe.db.sql') as mock_sql:
            result = self.service.validate_mandate_uniqueness(mandate)

            # SQL should not be called for non-active mandates
            mock_sql.assert_not_called()
            self.assertTrue(result['is_valid'])

    def test_validate_mandate_uniqueness_exception_handling(self):
        """Test exception handling in uniqueness validation"""
        mandate = self._create_mock_mandate(mandate_id='TEST-001')

        with patch('frappe.db.exists', side_effect=Exception("Database error")):

            result = self.service.validate_mandate_uniqueness(mandate)

            self.assertFalse(result['is_valid'])
            self.assertTrue(any('Uniqueness validation error' in error for error in result['errors']))

    # ========================================================================
    # Integration and realistic data tests
    # ========================================================================

    def test_realistic_dutch_mandate_validation(self):
        """Test validation with realistic Dutch association mandate data"""
        # Create realistic Dutch member mandate
        mandate = self._create_mock_mandate(
            status='Active',
            mandate_type='RCUR',
            mandate_id='VEG-2024-001',
            member='MEMBER-001',
            account_holder_name='Jan van der Berg',
            iban='NL91 INGB 0001 2345 67',
            bic='INGBNL2A',
            sign_date=getdate() - timedelta(days=10),
            expiry_date=getdate() + timedelta(days=365)
        )

        # Mock all external dependencies
        with patch('verenigingen.verenigingen_payments.services.sepa_mandate_validation_service.validate_iban') as mock_validate_iban:
            mock_validate_iban.return_value = {'valid': True, 'message': 'Valid IBAN'}

            with patch('verenigingen.verenigingen_payments.services.sepa_mandate_validation_service.format_iban') as mock_format:
                mock_format.return_value = 'NL91 INGB 0001 2345 67'

                with patch('verenigingen.verenigingen_payments.services.sepa_mandate_validation_service.derive_bic_from_iban') as mock_bic:
                    mock_bic.return_value = 'INGBNL2A'

                    with patch('frappe.db.exists') as mock_exists:
                        def exists_side_effect(doctype, filters):
                            if doctype == "Member":
                                return True  # Member exists
                            elif doctype == "SEPA Mandate":
                                return False  # Mandate ID doesn't exist (unique)
                            return None
                        mock_exists.side_effect = exists_side_effect

                        with patch('frappe.db.sql', return_value=[]):  # No conflicting mandates

                            # Test date validation
                            date_result = self.service.validate_mandate_dates(mandate)
                            self.assertTrue(date_result['is_valid'])

                            # Test IBAN validation
                            iban_result = self.service.validate_mandate_iban(mandate)
                            self.assertTrue(iban_result['is_valid'])

                            # Test business rules
                            business_result = self.service.validate_mandate_business_rules(mandate)
                            self.assertTrue(business_result['is_valid'])

                            # Test uniqueness
                            uniqueness_result = self.service.validate_mandate_uniqueness(mandate)
                            self.assertTrue(uniqueness_result['is_valid'])

    def test_edge_case_weekend_sign_date(self):
        """Test mandate signed on weekend (should be valid)"""
        # Find a past Saturday
        today = getdate()
        days_back = today.weekday() + 2  # Go back to last Saturday
        if today.weekday() == 5:  # If today is Saturday
            days_back = 0
        saturday = today - timedelta(days_back)

        mandate = self._create_mock_mandate(
            sign_date=saturday,
            expiry_date=saturday + timedelta(days=365)
        )

        result = self.service.validate_mandate_dates(mandate)

        # Weekend signing should be valid (no business day restriction)
        self.assertTrue(result['is_valid'])

    def test_multiple_validation_errors(self):
        """Test mandate with multiple validation errors"""
        mandate = self._create_mock_mandate(
            status='Active',
            mandate_id='DUPLICATE-001',
            iban=None,  # Missing IBAN
            account_holder_name=None,  # Missing account holder
            member='NON-EXISTENT',  # Non-existent member
            sign_date=getdate() + timedelta(days=10)  # Future sign date
        )

        # Mock duplicate mandate ID
        with patch('frappe.db.exists') as mock_exists:
            def exists_side_effect(doctype, filters):
                if doctype == "SEPA Mandate":
                    return 'EXISTING-MANDATE'
                elif doctype == "Member":
                    return False
                return None
            mock_exists.side_effect = exists_side_effect

            # Test all validation methods
            date_result = self.service.validate_mandate_dates(mandate)
            iban_result = self.service.validate_mandate_iban(mandate)
            business_result = self.service.validate_mandate_business_rules(mandate)
            uniqueness_result = self.service.validate_mandate_uniqueness(mandate)

            # All should have errors
            self.assertFalse(date_result['is_valid'])
            self.assertFalse(iban_result['is_valid'])
            self.assertFalse(business_result['is_valid'])
            self.assertFalse(uniqueness_result['is_valid'])

    def test_mandate_with_tussenvoegsel_name(self):
        """Test mandate validation with Dutch tussenvoegsel in account holder name"""
        mandate = self._create_mock_mandate(
            status='Active',
            account_holder_name='Jan van der Berg',  # Dutch name with tussenvoegsel
            iban=generate_test_iban("INGB"),
            mandate_id='VEG-2024-001'
        )

        result = self.service.validate_mandate_business_rules(mandate)

        # Should be valid with tussenvoegsel names
        self.assertTrue(result['is_valid'])


if __name__ == "__main__":
    unittest.main()