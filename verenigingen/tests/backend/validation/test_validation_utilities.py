"""Test validation utilities with configurable settings"""

import unittest
from datetime import date, datetime

import frappe
from dateutil.relativedelta import relativedelta
from frappe.utils import add_years, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.validation_utilities import AgeValidator, ValidationError


class TestAgeValidator(EnhancedTestCase):
    """Test age validation with configurable settings"""

    def setUp(self):
        """Set up test data"""
        super().setUp()
        self.today = date.today()

    def test_default_membership_age_validation(self):
        """Test membership age validation with default settings"""
        # Test valid age (20 years old)
        birth_date = self.today - relativedelta(years=20)
        result = AgeValidator.validate_age(birth_date, context="membership", throw_on_error=False)

        self.assertTrue(result.is_valid)
        self.assertAlmostEqual(result.age_years, 20, places=1)

    def test_configurable_minimum_age_membership(self):
        """Test that configurable minimum age is respected"""
        # Create a birth date for someone who is 17 years old
        birth_date = self.today - relativedelta(years=17)

        # With default minimum age (16), this should be valid
        result = AgeValidator.validate_age(birth_date, context="membership", throw_on_error=False)
        self.assertTrue(result.is_valid)

        # Test validation fails for under-age
        young_birth_date = self.today - relativedelta(years=15)
        result = AgeValidator.validate_age(young_birth_date, context="membership", throw_on_error=False)
        self.assertFalse(result.is_valid)
        self.assertIn("must be at least", result.message.lower())

    def test_configurable_volunteer_age_validation(self):
        """Test volunteer age validation uses configurable setting"""
        # Test valid volunteer age (18 years old)
        birth_date = self.today - relativedelta(years=18)
        result = AgeValidator.validate_age(birth_date, context="volunteer", throw_on_error=False)

        self.assertTrue(result.is_valid)

        # Test validation fails for under-age volunteer
        young_birth_date = self.today - relativedelta(years=15)
        result = AgeValidator.validate_age(young_birth_date, context="volunteer", throw_on_error=False)
        self.assertFalse(result.is_valid)

    def test_voting_age_validation(self):
        """Test voting age validation"""
        # Test valid voting age (19 years old)
        birth_date = self.today - relativedelta(years=19)
        result = AgeValidator.validate_age(birth_date, context="voting", throw_on_error=False)

        self.assertTrue(result.is_valid)

        # Test validation fails for under voting age
        young_birth_date = self.today - relativedelta(years=17)
        result = AgeValidator.validate_age(young_birth_date, context="voting", throw_on_error=False)
        self.assertFalse(result.is_valid)
        self.assertIn("voting rights require", result.message.lower())

    def test_student_membership_age_validation(self):
        """Test student membership age validation"""
        # Test valid student age (20 years old)
        birth_date = self.today - relativedelta(years=20)
        result = AgeValidator.validate_age(birth_date, context="student_membership", throw_on_error=False)

        self.assertTrue(result.is_valid)

        # Test validation fails for too young
        young_birth_date = self.today - relativedelta(years=13)
        result = AgeValidator.validate_age(
            young_birth_date, context="student_membership", throw_on_error=False
        )
        self.assertFalse(result.is_valid)

    def test_membership_type_specific_validation(self):
        """Test membership type-specific age validation"""
        # Test Student membership type
        birth_date = self.today - relativedelta(years=20)
        result = AgeValidator.validate_membership_age_for_type(birth_date, "Student", throw_on_error=False)
        self.assertTrue(result.is_valid)

        # Test Youth membership type
        birth_date = self.today - relativedelta(years=16, months=6)
        result = AgeValidator.validate_membership_age_for_type(birth_date, "Youth", throw_on_error=False)
        self.assertTrue(result.is_valid)

        # Test Senior membership type
        birth_date = self.today - relativedelta(years=67)
        result = AgeValidator.validate_membership_age_for_type(birth_date, "Senior", throw_on_error=False)
        self.assertTrue(result.is_valid)

    def test_custom_age_override(self):
        """Test custom age overrides work"""
        birth_date = self.today - relativedelta(years=15)

        # Should fail with default minimum age
        result = AgeValidator.validate_age(birth_date, context="membership", throw_on_error=False)
        self.assertFalse(result.is_valid)

        # Should pass with custom minimum age
        result = AgeValidator.validate_age(
            birth_date, context="membership", custom_min_age=14, throw_on_error=False
        )
        self.assertTrue(result.is_valid)

    def test_parental_consent_handling(self):
        """Test parental consent for under-age members"""
        birth_date = self.today - relativedelta(years=16, months=6)

        # Should require parental consent for youth membership
        result = AgeValidator.validate_age(
            birth_date,
            context="membership",
            custom_min_age=18,  # Require 18 for regular membership
            allow_parental_consent=True,
            throw_on_error=False,
        )
        self.assertTrue(result.is_valid)
        self.assertIn("parental consent", result.warning.lower())

    def test_configurable_settings_integration(self):
        """Minimum age is read solely from Verenigingen Settings (no fallback arg)."""
        import frappe

        configured = frappe.db.get_single_value("Verenigingen Settings", "minimum_membership_age")
        min_age = AgeValidator._get_configurable_min_age("membership")
        self.assertIsInstance(min_age, int)
        self.assertEqual(min_age, int(configured))

    def test_future_birth_date_validation(self):
        """Test that future birth dates are rejected"""
        future_date = self.today + relativedelta(years=1)

        with self.assertRaises(ValidationError) as context:
            AgeValidator.validate_age(future_date, context="membership", throw_on_error=True)

        self.assertIn("cannot be in the future", str(context.exception))

    def test_extremely_old_age_validation(self):
        """Test validation of extremely old ages"""
        birth_date = self.today - relativedelta(years=150)

        result = AgeValidator.validate_age(birth_date, context="membership", throw_on_error=False)
        self.assertFalse(result.is_valid)
        self.assertIn("unrealistic", result.message.lower())


if __name__ == "__main__":
    unittest.main()
