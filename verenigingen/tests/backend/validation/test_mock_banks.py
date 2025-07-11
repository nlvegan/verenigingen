"""
Test Mock Banks for IBAN Validation
"""

import unittest

import frappe

from verenigingen.utils.validation.iban_validator import (
    derive_bic_from_iban,
    generate_test_iban,
    get_bank_from_iban,
    validate_iban,
)


class TestMockBanks(unittest.TestCase):
    """Test mock bank functionality for testing purposes"""

    def test_generate_test_iban_valid(self):
        """Test that generated test IBANs are valid"""
        for bank_code in ["TEST", "MOCK", "DEMO"]:
            with self.subTest(bank_code=bank_code):
                iban = generate_test_iban(bank_code)
                self.assertIsNotNone(iban)
                self.assertTrue(iban.startswith("NL"))
                self.assertEqual(len(iban), 18)

    def test_test_iban_validation(self):
        """Test that generated test IBANs pass validation"""
        for bank_code in ["TEST", "MOCK", "DEMO"]:
            with self.subTest(bank_code=bank_code):
                iban = generate_test_iban(bank_code)
                validation = validate_iban(iban)
                self.assertTrue(validation["valid"])
                self.assertEqual(validation["message"], "Valid IBAN")

    def test_test_iban_bic_derivation(self):
        """Test BIC derivation for test IBANs"""
        expected_bics = {
            "TEST": "TESTNL2A",
            "MOCK": "MOCKNL2A",
            "DEMO": "DEMONL2A",
        }
        
        for bank_code, expected_bic in expected_bics.items():
            with self.subTest(bank_code=bank_code):
                iban = generate_test_iban(bank_code)
                bic = derive_bic_from_iban(iban)
                self.assertEqual(bic, expected_bic)

    def test_test_iban_bank_info(self):
        """Test bank information extraction for test IBANs"""
        expected_banks = {
            "TEST": "Test Bank (Mock)",
            "MOCK": "Mock Bank for Testing",
            "DEMO": "Demo Bank for Testing",
        }
        
        for bank_code, expected_name in expected_banks.items():
            with self.subTest(bank_code=bank_code):
                iban = generate_test_iban(bank_code)
                bank_info = get_bank_from_iban(iban)
                self.assertIsNotNone(bank_info)
                self.assertEqual(bank_info["bank_name"], expected_name)
                self.assertEqual(bank_info["bank_code"], bank_code)

    def test_generate_with_custom_account_number(self):
        """Test generating test IBAN with custom account number"""
        custom_account = "1234567890"
        iban = generate_test_iban("TEST", custom_account)
        
        # Should still be valid
        validation = validate_iban(iban)
        self.assertTrue(validation["valid"])
        
        # Should contain the custom account number
        self.assertIn(custom_account, iban)

    def test_invalid_bank_code_defaults_to_test(self):
        """Test that invalid bank codes default to TEST"""
        iban = generate_test_iban("INVALID")
        
        # Should still be valid
        validation = validate_iban(iban)
        self.assertTrue(validation["valid"])
        
        # Should use TEST bank
        self.assertIn("TEST", iban)

    def test_integration_with_sepa_mandate_creation(self):
        """Test that test IBANs work with SEPA mandate creation"""
        iban = generate_test_iban("TEST")
        
        # Should be able to derive BIC (required for SEPA)
        bic = derive_bic_from_iban(iban)
        self.assertIsNotNone(bic)
        self.assertEqual(bic, "TESTNL2A")
        
        # Should pass validation (required for SEPA)
        validation = validate_iban(iban)
        self.assertTrue(validation["valid"])


if __name__ == "__main__":
    unittest.main()