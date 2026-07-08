"""
Unit Tests for SEPA Business Logic
==================================

Unit tests for isolated SEPA payment processing business logic components.
These tests focus on specific business rules and edge cases without database dependencies.

Focus Areas:
- IBAN validation and normalization
- Mandate lifecycle management
- Payment batch processing logic
- SEPA rulebook compliance
- Error handling and validation
- Dutch banking-specific rules

Author: Enhanced Test Development Phase 5.2
"""

import unittest

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class SEPABusinessLogicUnitTest(EnhancedTestCase):
    """Unit tests for SEPA business logic without database dependencies"""

    def setUp(self):
        """Set up unit test fixtures"""
        super().setUp()

    def test_iban_validation_edge_cases(self):
        """Test IBAN validation business rules"""

        # Test cases for Dutch IBAN validation
        valid_ibans = [
            "NL91ABNA0417164300",  # Standard format
            "NL91 ABNA 0417 1643 00",  # With spaces
            "nl91abna0417164300",  # Lowercase
            "NL02ABNA0123456789",  # Different bank
            "NL20INGB0001234567",  # ING bank
        ]

        invalid_ibans = [
            "NL91ABNA041716430",  # Too short
            "NL91ABNA04171643000",  # Too long
            "DE91ABNA0417164300",  # Wrong country (German)
            "NL00ABNA0417164300",  # Invalid check digits
            "XY91ABNA0417164300",  # Invalid country code
            "NL91ABC0417164300",  # Invalid bank code (too short)
            "",  # Empty string
        ]

        # Use the REAL production validator (proper MOD-97 + bank-code checks)
        # rather than a simplified inline stub that cannot detect invalid check
        # digits (e.g. NL00...) or invalid bank codes.
        from verenigingen.utils.validation.iban_validator import validate_iban

        def validate_dutch_iban(iban):
            return validate_iban(iban)["valid"]

        for iban in valid_ibans:
            self.assertTrue(validate_dutch_iban(iban), f"IBAN {iban} should be valid")

        for iban in invalid_ibans:
            self.assertFalse(validate_dutch_iban(iban), f"IBAN {iban} should be invalid")

    def test_iban_normalization(self):
        """Test IBAN normalization via the real production formatter.

        The former version of this test reimplemented normalization as a
        local ``normalize_iban()`` helper and asserted against itself. It is
        rewritten to call the real ``format_iban()`` (used to display IBANs
        throughout the app), which normalizes casing/spacing and re-groups
        into 4-character blocks -- the actual production behavior.
        """
        from verenigingen.utils.validation.iban_validator import format_iban

        test_cases = [
            ("nl91 abna 0417 1643 00", "NL91 ABNA 0417 1643 00"),
            ("NL91ABNA0417164300", "NL91 ABNA 0417 1643 00"),
            ("  NL91 ABNA 0417 1643 00  ", "NL91 ABNA 0417 1643 00"),
            ("NL91  ABNA  0417  1643  00", "NL91 ABNA 0417 1643 00"),
        ]

        for raw, expected in test_cases:
            self.assertEqual(format_iban(raw), expected, f"format_iban failed for {raw!r}")

        # Falsy input must not raise.
        self.assertEqual(format_iban(""), "")
        self.assertIsNone(format_iban(None))


if __name__ == "__main__":
    unittest.main()
