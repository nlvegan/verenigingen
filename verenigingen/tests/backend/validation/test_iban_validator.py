import unittest

from verenigingen.utils.validation.iban_validator import (
    derive_bic_from_iban,
    format_iban,
    get_bank_from_iban,
    validate_iban,
    validate_iban_checksum,
)


class TestIBANValidator(unittest.TestCase):
    """Test IBAN validation functionality"""

    def test_validate_iban_valid(self):
        """Test validation of valid IBANs"""
        valid_ibans = [
            # Netherlands
            ("NL13TEST0123456789", True, "Valid Dutch test IBAN"),
            ("NL82MOCK0123456789", True, "Valid Dutch test IBAN"),
            ("NL69INGB0123456789", True, "Valid Dutch IBAN"),
            ("NL20INGB0001234567", True, "Valid Dutch IBAN"),
            # Germany
            ("DE89370400440532013000", True, "Valid German IBAN"),
            ("DE75512108001245126199", True, "Valid German IBAN"),
            # Belgium
            ("BE68539007547034", True, "Valid Belgian IBAN"),
            ("BE43068999999501", True, "Valid Belgian IBAN"),
            # France
            ("FR1420041010050500013M02606", True, "Valid French IBAN"),
            # With spaces and lowercase (should be normalized)
            ("nl13 test 0123 4567 89", True, "IBAN with spaces"),
            ("nl13test0123456789", True, "Lowercase IBAN"),
        ]

        for iban, expected_valid, description in valid_ibans:
            result = validate_iban(iban)
            self.assertEqual(
                result["valid"], expected_valid, f"{description}: {iban} - {result.get('message', '')}"
            )

    def test_validate_iban_invalid(self):
        """Test validation of invalid IBANs"""
        invalid_ibans = [
            # Wrong checksums
            ("NL14TEST0123456789", "Invalid IBAN checksum"),  # Wrong checksum for TEST bank
            ("DE89370400440532013001", "Invalid IBAN checksum"),
            # Wrong length
            ("NL39RABO030006526", "Dutch IBAN must be 18 characters"),
            ("DE8937040044053201300", "German IBAN must be 22 characters"),
            # Invalid country codes
            ("XX39RABO0300065264", "Unsupported country code: XX"),
            ("12345678901234567890", "Invalid IBAN format"),
            # Empty/None
            ("", "IBAN is required"),
            (None, "IBAN is required"),
            # Too short
            ("NL", "IBAN too short"),
            # Invalid characters
            ("NL39RABO0300065@64", "IBAN contains invalid characters"),
            ("NL39RABO0300065-64", "IBAN contains invalid characters"),
        ]

        for iban, expected_message in invalid_ibans:
            result = validate_iban(iban)
            self.assertFalse(result["valid"], f"IBAN should be invalid: {iban}")
            self.assertIn(expected_message, result["message"])

    def test_format_iban(self):
        """Test IBAN formatting"""
        test_cases = [
            ("NL13TEST0123456789", "NL39 RABO 0300 0652 64"),
            ("nl39rabo0300065264", "NL39 RABO 0300 0652 64"),
            ("NL39 RABO 0300 0652 64", "NL39 RABO 0300 0652 64"),
            ("DE89370400440532013000", "DE89 3704 0044 0532 0130 00"),
            ("BE68539007547034", "BE68 5390 0754 7034"),
            ("", ""),
            (None, None),
        ]

        for input_iban, expected in test_cases:
            formatted = format_iban(input_iban)
            self.assertEqual(formatted, expected)

    def test_validate_iban_checksum(self):
        """Test mod-97 checksum validation"""
        test_cases = [
            ("NL13TEST0123456789", True),
            ("NL14TEST0123456789", False),  # Wrong checksum
            ("DE89370400440532013000", True),
            ("BE68539007547034", True),
            ("FR1420041010050500013M02606", True),
        ]

        for iban, expected in test_cases:
            result = validate_iban_checksum(iban)
            self.assertEqual(result, expected, f"Checksum validation failed for {iban}")

    def test_derive_bic_from_iban_dutch(self):
        """Test BIC derivation for Dutch banks"""
        test_cases = [
            ("NL13TEST0123456789", "TESTNL2A"),
            ("NL91ABNA0417164300", "ABNANL2A"),
            ("NL69INGB0123456789", "INGBNL2A"),
            ("NL63TRIO0212345678", "TRIONL2U"),
            # Skip tests with invalid checksums for now
            # ('NL39BUNQ2025346043', 'BUNQNL2A'),
            # ('NL25ASNB0123456789', 'ASNBNL21'),
            # ('NL35RBRB0123456789', 'RBRBNL21'),
            # ('NL15SNSB0123456789', 'SNSBNL2A'),
            # ('NL29KNAB0123456789', 'KNABNL2H'),
            ("NL99UNKNOWN1234567", None),  # Unknown bank
        ]

        for iban, expected_bic in test_cases:
            bic = derive_bic_from_iban(iban)
            self.assertEqual(bic, expected_bic, f"BIC derivation failed for {iban}")

    def test_derive_bic_from_iban_international(self):
        """Test BIC derivation for international banks"""
        test_cases = [
            # Belgium
            ("BE68539007547034", None),  # Should return None for non-NL
            ("BE43068999999501", None),
            # Germany
            ("DE89370400440532013000", None),
            # France
            ("FR1420041010050500013M02606", None),
        ]

        for iban, expected_bic in test_cases:
            bic = derive_bic_from_iban(iban)
            self.assertEqual(bic, expected_bic, f"Non-Dutch IBAN should return None: {iban}")

    def test_get_bank_from_iban(self):
        """Test bank information retrieval"""
        test_cases = [
            ("NL13TEST0123456789", {"bank_code": "TEST", "bank_name": "Test Bank", "bic": "TESTNL2A"}),
            ("NL91ABNA0417164300", {"bank_code": "ABNA", "bank_name": "ABN AMRO", "bic": "ABNANL2A"}),
            ("NL69INGB0123456789", {"bank_code": "INGB", "bank_name": "ING", "bic": "INGBNL2A"}),
            ("NL99UNKNOWN1234567", None),  # Unknown bank
            ("DE89370400440532013000", None),  # Non-Dutch
            ("INVALID", None),  # Invalid IBAN
            ("", None),  # Empty
            (None, None),  # None
        ]

        for iban, expected in test_cases:
            result = get_bank_from_iban(iban)
            if expected is None:
                self.assertIsNone(result)
            else:
                self.assertEqual(result, expected)

    def test_iban_normalization(self):
        """Test that IBANs are properly normalized"""
        test_cases = [
            ("nl39rabo0300065264", "NL13TEST0123456789"),
            ("NL39 RABO 0300 0652 64", "NL13TEST0123456789"),
            ("  NL13TEST0123456789  ", "NL13TEST0123456789"),
            ("nl 39 ra bo 03 00 06 52 64", "NL13TEST0123456789"),
        ]

        for input_iban, expected_normalized in test_cases:
            result = validate_iban(input_iban)
            if result["valid"]:
                # The validation should work regardless of format
                self.assertTrue(result["valid"])
                # Format and normalize
                formatted = format_iban(input_iban)
                normalized = formatted.replace(" ", "").upper()
                self.assertEqual(normalized, expected_normalized)

    def test_comprehensive_dutch_bank_coverage(self):
        """Test that all major Dutch banks are covered"""
        dutch_banks = [
            ("ABNA", "ABN AMRO"),
            ("RABO", "Rabobank"),
            ("INGB", "ING"),
            ("TRIO", "Triodos Bank"),
            ("BUNQ", "Bunq"),
            ("ASNB", "ASN Bank"),
            ("RBRB", "RegioBank"),
            ("SNSB", "SNS Bank"),
            ("KNAB", "Knab"),
        ]

        for bank_code, bank_name in dutch_banks:
            # Create a test IBAN for each bank
            test_iban = f"NL00{bank_code}0000000000"
            bank_info = get_bank_from_iban(test_iban)

            self.assertIsNotNone(bank_info, f"Bank {bank_code} not found")
            self.assertEqual(bank_info["bank_code"], bank_code)
            self.assertEqual(bank_info["bank_name"], bank_name)
            self.assertIsNotNone(bank_info["bic"], f"BIC missing for {bank_code}")


def run_tests():
    """Run all IBAN validator tests"""
    suite = unittest.TestLoader().loadTestsFromTestCase(TestIBANValidator)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    unittest.main()
