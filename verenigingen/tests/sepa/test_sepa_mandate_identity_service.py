#!/usr/bin/env python3
"""
Unit Tests for SEPA Mandate Identity Service

Tests the SEPAMandateIdentityService class methods in isolation with realistic
data generation and minimal mocking. Focuses on business logic correctness
rather than framework integration.

Test Coverage:
- generate_mandate_id() with various naming patterns and edge cases
- _generate_mandate_id_with_counter() logic and counter management
- validate_mandate_reference() format validation
- ensure_mandate_uniqueness() duplicate detection
- Edge cases: custom patterns, counter overflow, uniqueness conflicts
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, date
import re

import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.services.sepa_mandate_identity_service import SEPAMandateIdentityService


class TestSEPAMandateIdentityService(EnhancedTestCase):
    """Unit tests for SEPA Mandate Identity Service"""

    def setUp(self):
        """Set up test environment and service instance"""
        super().setUp()
        self.service = SEPAMandateIdentityService()
        # Clear any cached settings between tests
        self.service.clear_settings_cache()

    def tearDown(self):
        """Clean up after each test"""
        super().tearDown()

    def create_sepa_mandate_with_id(self, mandate_reference):
        """
        Helper method to create a SEPA Mandate with a specific mandate_reference ID.
        Used to test ID generation and counter increment logic with real database state.
        """
        # Create a test member for the mandate
        member = self.create_test_member(
            first_name="SEPA",
            last_name="Test",
            email=f"sepa.{mandate_reference.lower().replace('-', '.')}@example.com"
        )

        # Create mandate with specific ID. The SEPA Mandate field is `mandate_id`
        # (there is no `mandate_reference` field), and the identity service queries
        # `mandate_id` — so the ID must be set via mandate_id, not mandate_reference.
        mandate = self.create_test_sepa_mandate(
            member_name=member.name,
            mandate_id=mandate_reference
        )

        return mandate

    # ========================================================================
    # Tests for generate_mandate_id()
    # ========================================================================

    def test_generate_mandate_id_with_default_pattern(self):
        """Test mandate ID generation with default naming pattern"""
        with patch.object(self.service, '_get_settings') as mock_settings:
            # Mock settings without custom pattern
            mock_settings.return_value = Mock(
                sepa_mandate_naming_pattern=None,
                sepa_mandate_starting_counter=None
            )

            with patch.object(self.service, '_generate_mandate_id_with_counter') as mock_generate:
                mock_generate.return_value = "MANDATE-24-09-0001"

                result = self.service.generate_mandate_id()

                # Should use default pattern and starting counter
                mock_generate.assert_called_once_with("MANDATE-.YY.-.MM.-.####", 1)
                self.assertEqual(result, "MANDATE-24-09-0001")

    def test_generate_mandate_id_with_custom_pattern(self):
        """Test mandate ID generation with custom naming pattern"""
        with patch.object(self.service, '_get_settings') as mock_settings:
            # Mock settings with custom pattern
            mock_settings.return_value = Mock(
                sepa_mandate_naming_pattern="VEG-{YYYY}-{MM}-{DD}-###",
                sepa_mandate_starting_counter="100"
            )

            with patch.object(self.service, '_generate_mandate_id_with_counter') as mock_generate:
                mock_generate.return_value = "VEG-2024-09-18-100"

                result = self.service.generate_mandate_id()

                # Should use custom pattern and starting counter
                mock_generate.assert_called_once_with("VEG-{YYYY}-{MM}-{DD}-###", 100)
                self.assertEqual(result, "VEG-2024-09-18-100")

    def test_generate_mandate_id_fallback_on_error(self):
        """Test fallback behavior when ID generation fails"""
        with patch.object(self.service, '_get_settings', side_effect=Exception("Settings error")):
            with patch('frappe.model.naming.make_autoname', return_value="MANDATE-24-09-0001") as mock_autoname:
                with patch('frappe.log_error') as mock_log:

                    result = self.service.generate_mandate_id()

                    # Should fallback to default autoname
                    mock_autoname.assert_called_once_with("MANDATE-.YY.-.MM.-.####")
                    mock_log.assert_called_once()
                    self.assertEqual(result, "MANDATE-24-09-0001")

    def test_generate_mandate_id_with_mandate_doc(self):
        """Test mandate ID generation with mandate document context"""
        mock_mandate = Mock(name="Test Mandate")

        with patch.object(self.service, '_get_settings') as mock_settings:
            mock_settings.return_value = Mock(
                sepa_mandate_naming_pattern="MEMBER-{YYYY}-####",
                sepa_mandate_starting_counter="1"
            )

            with patch.object(self.service, '_generate_mandate_id_with_counter') as mock_generate:
                mock_generate.return_value = "MEMBER-2024-0001"

                result = self.service.generate_mandate_id(mock_mandate)

                self.assertEqual(result, "MEMBER-2024-0001")

    # ========================================================================
    # Tests for _generate_mandate_id_with_counter()
    # ========================================================================

    def test_generate_mandate_id_with_counter_date_replacement(self):
        """Test date token replacement in mandate ID generation"""
        # Mock datetime to have predictable dates
        mock_datetime = datetime(2024, 9, 18, 10, 30, 0)

        with patch('verenigingen.verenigingen_payments.services.sepa_mandate_identity_service.now_datetime', return_value=mock_datetime):
            # Use real database state (no existing mandates due to test rollback)

            # Test various date patterns
            test_cases = [
                ("PREFIX-{YYYY}-{MM}-{DD}-###", "PREFIX-2024-09-18-001"),
                ("MANDATE-{YY}-{MM}-###", "MANDATE-24-09-001"),
                ("TEST.YYYY..MM..DD.####", "TEST-2024-09-18-0001"),
                ("{YYYY}{MM}{DD}####", "20240918-0001"),
            ]

            for pattern, expected_base in test_cases:
                with self.subTest(pattern=pattern):
                    result = self.service._generate_mandate_id_with_counter(pattern, 1)
                    # Remove the incremented number for comparison
                    self.assertTrue(result.startswith(expected_base[:-4]) or result.startswith(expected_base[:-3]))

    def test_generate_mandate_id_with_counter_existing_mandates(self):
        """Test counter increment based on existing mandates"""
        mock_datetime = datetime(2024, 9, 18, 10, 30, 0)

        with patch('verenigingen.verenigingen_payments.services.sepa_mandate_identity_service.now_datetime', return_value=mock_datetime):
            # Create real mandate with counter 5
            self.create_sepa_mandate_with_id("MANDATE-24-09-0005")

            result = self.service._generate_mandate_id_with_counter("MANDATE-.YY.-.MM.-.####", 1)

            # Should increment to 6
            self.assertEqual(result, "MANDATE-24-09-0006")

    def test_generate_mandate_id_with_counter_no_counter_pattern(self):
        """Test mandate ID generation without counter pattern"""
        mock_datetime = datetime(2024, 9, 18, 10, 30, 0)

        with patch('verenigingen.verenigingen_payments.services.sepa_mandate_identity_service.now_datetime', return_value=mock_datetime):

            result = self.service._generate_mandate_id_with_counter("STATIC-ID-{YYYY}-{MM}", 1)

            # Should return pattern with dates replaced
            self.assertEqual(result, "STATIC-ID-2024-09")

    def test_generate_mandate_id_with_counter_frappe_dot_notation(self):
        """Test Frappe's dot notation for date patterns"""
        mock_datetime = datetime(2024, 9, 18, 10, 30, 0)

        with patch('verenigingen.verenigingen_payments.services.sepa_mandate_identity_service.now_datetime', return_value=mock_datetime):
            # Use real database state (no existing mandates)

            result = self.service._generate_mandate_id_with_counter("MANDATE-.YY.-.MM.-.####", 10)

            # Should handle Frappe dot notation correctly
            self.assertEqual(result, "MANDATE-24-09-0010")

    def test_generate_mandate_id_with_counter_malformed_last_mandate(self):
        """Test handling of malformed last mandate ID"""
        mock_datetime = datetime(2024, 9, 18, 10, 30, 0)

        with patch('verenigingen.verenigingen_payments.services.sepa_mandate_identity_service.now_datetime', return_value=mock_datetime):
            # Create real mandate with invalid counter format
            self.create_sepa_mandate_with_id("MANDATE-24-09-INVALID")

            result = self.service._generate_mandate_id_with_counter("MANDATE-.YY.-.MM.-.####", 100)

            # Should use starting counter when last mandate is malformed
            self.assertEqual(result, "MANDATE-24-09-0100")

    def test_generate_mandate_id_with_counter_different_digit_lengths(self):
        """Test counter patterns with different digit lengths"""
        mock_datetime = datetime(2024, 9, 18, 10, 30, 0)

        with patch('verenigingen.verenigingen_payments.services.sepa_mandate_identity_service.now_datetime', return_value=mock_datetime):
            # Use real database state (no existing mandates)

            test_cases = [
                ("PREFIX-##", "PREFIX-01", 1),
                ("PREFIX-###", "PREFIX-001", 1),
                ("PREFIX-####", "PREFIX-0001", 1),
                ("PREFIX-#####", "PREFIX-00001", 1),
                ("PREFIX-##", "PREFIX-99", 99),
            ]

            for pattern, expected, starting_counter in test_cases:
                with self.subTest(pattern=pattern, starting_counter=starting_counter):
                    result = self.service._generate_mandate_id_with_counter(pattern, starting_counter)
                    self.assertEqual(result, expected)

    # ========================================================================
    # Tests for validate_mandate_reference()
    # ========================================================================

    def test_validate_mandate_reference_valid_formats(self):
        """Test validation of valid mandate reference formats"""
        valid_references = [
            "MANDATE-24-09-0001",
            "VEG-2024-001",
            "TEST_MANDATE_123",
            "SEPA/2024/001",
            "MANDATE.2024.09.001",
            "123456789",  # Simple numeric
            "A" * 35,  # Maximum length
            "ABC",  # Minimum length
            "MIX-123_TEST.2024/001"  # Mixed valid characters
        ]

        for reference in valid_references:
            with self.subTest(reference=reference):
                result = self.service.validate_mandate_reference(reference)
                self.assertTrue(result, f"Reference {reference} should be valid")

    def test_validate_mandate_reference_invalid_formats(self):
        """Test validation of invalid mandate reference formats"""
        invalid_references = [
            None,  # None value
            "",  # Empty string
            "AB",  # Too short (less than 3 characters)
            "A" * 36,  # Too long (more than 35 characters)
            "TEST@MANDATE",  # Invalid character @
            "TEST#MANDATE",  # Invalid character #
            "TEST MANDATE",  # Space not allowed in this context
            "TEST+MANDATE",  # Invalid character +
            "TEST*MANDATE",  # Invalid character *
            "MANDATE[001]",  # Invalid characters []
            "MANDATE{001}",  # Invalid characters {}
            "MANDATE<001>",  # Invalid characters <>
        ]

        for reference in invalid_references:
            with self.subTest(reference=reference):
                result = self.service.validate_mandate_reference(reference)
                self.assertFalse(result, f"Reference {reference} should be invalid")

    def test_validate_mandate_reference_sepa_compliance(self):
        """Test SEPA mandate reference format compliance"""
        # SEPA mandate references should allow alphanumeric and limited special chars
        sepa_compliant = [
            "MANDATE-2024-001",
            "SEPA.24.09.001",
            "VEG/2024/001",
            "MEMBER_2024_001",
            "123456789012345678901234567890123456789"[:35]  # Exactly 35 chars
        ]

        for reference in sepa_compliant:
            with self.subTest(reference=reference):
                result = self.service.validate_mandate_reference(reference)
                self.assertTrue(result, f"SEPA compliant reference {reference} should be valid")

    # ========================================================================
    # Tests for ensure_mandate_uniqueness()
    # ========================================================================

    def test_ensure_mandate_uniqueness_unique_id(self):
        """Test uniqueness check for non-existing mandate ID"""
        # Use real database state (no mandate with this ID exists due to test rollback)
        result = self.service.ensure_mandate_uniqueness("UNIQUE-MANDATE-001")
        self.assertTrue(result, "Non-existing mandate ID should be unique")

    def test_ensure_mandate_uniqueness_duplicate_id(self):
        """Test uniqueness check for existing mandate ID"""
        # Create real mandate to test duplicate detection
        existing_mandate = self.create_sepa_mandate_with_id("EXISTING-MANDATE-001")

        result = self.service.ensure_mandate_uniqueness("EXISTING-MANDATE-001")
        self.assertFalse(result, "Existing mandate ID should not be unique")

    def test_ensure_mandate_uniqueness_with_exclude(self):
        """Test uniqueness check excluding current mandate"""
        # Create real mandate
        existing_mandate = self.create_sepa_mandate_with_id("MANDATE-001")

        # Check uniqueness excluding the existing mandate (simulating update scenario)
        result = self.service.ensure_mandate_uniqueness(
            "MANDATE-001",
            exclude_name=existing_mandate.name
        )
        self.assertTrue(result, "Should be unique when excluding current mandate")

    def test_ensure_mandate_uniqueness_case_insensitivity(self):
        """Uniqueness check is case-insensitive (mandate_id column uses a *_ci collation).

        The SEPA Mandate.mandate_id column uses a case-insensitive collation
        (utf8mb4_unicode_ci), so a uniqueness check matches regardless of case.
        This is the real production behaviour and a desirable safeguard against
        near-duplicate mandate IDs that differ only by case.
        """
        # Create mandate with uppercase ID
        self.create_sepa_mandate_with_id("TEST-MANDATE-001")

        # A case-variant is NOT considered unique (collation is case-insensitive).
        result = self.service.ensure_mandate_uniqueness("test-mandate-001")
        self.assertFalse(result, "Case-variant mandate ID should collide under *_ci collation")

        # Exact match is likewise not unique.
        result = self.service.ensure_mandate_uniqueness("TEST-MANDATE-001")
        self.assertFalse(result, "Exact match should not be unique")

    # ========================================================================
    # Tests for settings caching and edge cases
    # ========================================================================

    def test_get_settings_caching(self):
        """Test that settings are cached properly"""
        mock_settings = Mock(
            sepa_mandate_naming_pattern="CACHED-####",
            sepa_mandate_starting_counter="1"
        )

        with patch('frappe.get_single', return_value=mock_settings) as mock_get_single:
            # First call should hit database
            settings1 = self.service._get_settings()

            # Second call should use cache
            settings2 = self.service._get_settings()

            # Should only call database once (SEPA fields now in Payments Settings)
            mock_get_single.assert_called_once_with("Verenigingen Payments Settings")
            self.assertEqual(settings1, settings2)

    def test_clear_settings_cache(self):
        """Test cache clearing functionality"""
        mock_settings = Mock()

        with patch('frappe.get_single', return_value=mock_settings) as mock_get_single:
            # Load settings
            self.service._get_settings()

            # Clear cache
            self.service.clear_settings_cache()

            # Next call should hit database again
            self.service._get_settings()

            # Should have called database twice
            self.assertEqual(mock_get_single.call_count, 2)

    def test_generate_mandate_id_with_invalid_starting_counter(self):
        """Test handling of invalid starting counter values"""
        with patch.object(self.service, '_get_settings') as mock_settings:
            # Mock settings with invalid counter
            mock_settings.return_value = Mock(
                sepa_mandate_naming_pattern="TEST-####",
                sepa_mandate_starting_counter="invalid"
            )

            with patch.object(self.service, '_generate_mandate_id_with_counter') as mock_generate:
                mock_generate.return_value = "TEST-0001"

                self.service.generate_mandate_id()

                # Should default to 1 when counter is invalid
                mock_generate.assert_called_once_with("TEST-####", 1)

    def test_generate_mandate_id_with_empty_starting_counter(self):
        """Test handling of empty starting counter values"""
        with patch.object(self.service, '_get_settings') as mock_settings:
            # Mock settings with empty counter
            mock_settings.return_value = Mock(
                sepa_mandate_naming_pattern="TEST-####",
                sepa_mandate_starting_counter=""
            )

            with patch.object(self.service, '_generate_mandate_id_with_counter') as mock_generate:
                mock_generate.return_value = "TEST-0001"

                self.service.generate_mandate_id()

                # Should default to 1 when counter is empty
                mock_generate.assert_called_once_with("TEST-####", 1)

    # ========================================================================
    # Integration and realistic data tests
    # ========================================================================

    def test_realistic_dutch_naming_patterns(self):
        """Test with realistic Dutch association naming patterns"""
        mock_datetime = datetime(2024, 9, 18, 10, 30, 0)

        with patch('verenigingen.verenigingen_payments.services.sepa_mandate_identity_service.now_datetime', return_value=mock_datetime):
            # Use real database state (no existing mandates due to test rollback)

            dutch_patterns = [
                ("VEG-{YYYY}-####", "VEG-2024-0001"),
                ("ROOD-{YY}{MM}-###", "ROOD-2409-001"),
                ("MEMBER.{YYYY}.{MM}.####", "MEMBER.2024.09.0001"),
                ("SEPA/{YYYY}/{MM}/{DD}/####", "SEPA/2024/09/18/0001"),
            ]

            for pattern, expected in dutch_patterns:
                with self.subTest(pattern=pattern):
                    result = self.service._generate_mandate_id_with_counter(pattern, 1)
                    self.assertEqual(result, expected)

    def test_year_boundary_handling(self):
        """Test date handling at year boundaries"""
        # Test New Year's Day
        new_year = datetime(2025, 1, 1, 0, 0, 0)

        with patch('verenigingen.verenigingen_payments.services.sepa_mandate_identity_service.now_datetime', return_value=new_year):
            # Use real database state (no existing mandates due to test rollback)

            result = self.service._generate_mandate_id_with_counter("MANDATE-{YYYY}-{YY}-{MM}-####", 1)
            self.assertEqual(result, "MANDATE-2025-25-01-0001")

    def test_leap_year_handling(self):
        """Test date handling in leap year"""
        # Test February 29th in leap year
        leap_day = datetime(2024, 2, 29, 12, 0, 0)

        with patch('verenigingen.verenigingen_payments.services.sepa_mandate_identity_service.now_datetime', return_value=leap_day):
            # Use real database state (no existing mandates due to test rollback)

            result = self.service._generate_mandate_id_with_counter("LEAP-{YYYY}-{MM}-{DD}-###", 1)
            self.assertEqual(result, "LEAP-2024-02-29-001")

    def test_high_counter_values(self):
        """Test handling of high counter values"""
        mock_datetime = datetime(2024, 9, 18, 10, 30, 0)

        with patch('verenigingen.verenigingen_payments.services.sepa_mandate_identity_service.now_datetime', return_value=mock_datetime):
            # Create real mandate with high counter (9999)
            self.create_sepa_mandate_with_id("MANDATE-24-09-9999")

            result = self.service._generate_mandate_id_with_counter("MANDATE-.YY.-.MM.-.####", 1)

            # Should increment to 10000 (5 digits)
            self.assertEqual(result, "MANDATE-24-09-10000")


if __name__ == "__main__":
    unittest.main()