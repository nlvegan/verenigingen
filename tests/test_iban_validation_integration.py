"""
Test IBAN Validation Integration
Tests comprehensive IBAN validation across different components
"""

import unittest

import frappe
from frappe.utils import today

from verenigingen.utils.iban_validator import derive_bic_from_iban, validate_iban


class TestIBANValidationIntegration(unittest.TestCase):
    """Test IBAN validation integration across the system"""

    def setUp(self):
        """Set up test data"""
        frappe.set_user("Administrator")

    def test_iban_validation_comprehensive(self):
        """Test comprehensive IBAN validation"""
        test_cases = [
            # Valid IBANs
            ("NL91ABNA0417164300", True, "Valid IBAN"),
            ("nl91abna0417164300", True, "Valid IBAN"),  # lowercase
            ("NL91 ABNA 0417 1643 00", True, "Valid IBAN"),  # with spaces
            ("BE68539007547034", True, "Valid IBAN"),
            ("DE89370400440532013000", True, "Valid IBAN"),
            ("FR1420041010050500013M02606", True, "Valid IBAN"),
            # Invalid IBANs
            ("NL91ABNA0417164301", False, "Invalid IBAN checksum"),  # wrong checksum
            ("NL91ABNA041716430", False, "Dutch IBAN must be 18 characters"),  # too short
            ("XX91ABNA0417164300", False, "Unsupported country code: XX"),  # invalid country
            ("", False, "IBAN is required"),
            ("123456789", False, "Invalid IBAN format"),
        ]

        for iban, expected_valid, expected_msg in test_cases:
            with self.subTest(iban=iban):
                result = validate_iban(iban)
                self.assertEqual(
                    result["valid"], expected_valid, f"IBAN {iban} validation failed: {result.get('message')}"
                )
                self.assertIn(expected_msg, result["message"])

    def test_bic_derivation(self):
        """Test BIC derivation from Dutch IBANs"""
        test_cases = [
            ("NL91ABNA0417164300", "ABNANL2A"),
            ("NL44RABO0123456789", "RABONL2U"),
            ("NL69INGB0123456789", "INGBNL2A"),
            ("NL63TRIO0212345678", "TRIONL2U"),
            ("BE68539007547034", None),  # Non-Dutch IBAN
        ]

        for iban, expected_bic in test_cases:
            with self.subTest(iban=iban):
                bic = derive_bic_from_iban(iban)
                self.assertEqual(bic, expected_bic, f"BIC derivation for {iban} failed")

    def test_member_iban_validation(self):
        """Test IBAN validation in Member doctype"""
        # Create test member
        member = frappe.new_doc("Member")
        member.first_name = "IBAN"
        member.last_name = "Test"
        member.email = f"iban.test.{frappe.utils.random_string(5)}@example.com"
        member.payment_method = "SEPA Direct Debit"

        # Test invalid IBAN
        member.iban = "NL91ABNA0417164301"  # Invalid checksum
        with self.assertRaises(frappe.ValidationError):
            member.validate()

        # Test valid IBAN
        member.iban = "NL91ABNA0417164300"
        member.validate()
        self.assertEqual(member.iban, "NL91 ABNA 0417 1643 00")  # Should be formatted
        self.assertEqual(member.bic, "ABNANL2A")  # Should be auto-derived

    def test_sepa_mandate_iban_validation(self):
        """Test IBAN validation in SEPA Mandate creation"""
        # Create test member first
        member = frappe.new_doc("Member")
        member.first_name = "SEPA"
        member.last_name = "Test"
        member.email = f"sepa.test.{frappe.utils.random_string(5)}@example.com"
        member.payment_method = "Bank Transfer"
        member.save()

        # Create SEPA mandate with invalid IBAN
        mandate = frappe.new_doc("SEPA Mandate")
        mandate.member = member.name
        mandate.member_name = member.full_name
        mandate.mandate_id = f"TEST-{member.name}-001"
        mandate.iban = "NL91ABNA041716430"  # Too short
        mandate.account_holder_name = member.full_name
        mandate.mandate_type = "RCUR"
        mandate.sign_date = today()

        with self.assertRaises(frappe.ValidationError) as context:
            mandate.validate()

        self.assertIn("IBAN", str(context.exception))

        # Test with valid IBAN
        mandate.iban = "NL91ABNA0417164300"
        mandate.validate()
        self.assertEqual(mandate.iban, "NL91 ABNA 0417 1643 00")
        self.assertEqual(mandate.bic, "ABNANL2A")

    def test_membership_application_iban_validation(self):
        """Test IBAN validation in membership application API"""
        from verenigingen.api.membership_application import validate_application_data

        # Test application with invalid IBAN
        application_data = {
            "first_name": "App",
            "last_name": "Test",
            "email": f"app.test.{frappe.utils.random_string(5)}@example.com",
            "birth_date": "1990-01-01",
            "address_line1": "Test Street 123",
            "postal_code": "1234AB",
            "city": "Amsterdam",
            "country": "Netherlands",
            "membership_type": "Annual",
            "payment_method": "SEPA Direct Debit",
            "iban": "XX91ABNA0417164300",  # Invalid country
            "bank_account_name": "Test Account",
        }

        validation_result = validate_application_data(application_data)
        self.assertFalse(validation_result["valid"])
        self.assertIn("IBAN", validation_result.get("errors", {}).get("iban", ""))

        # Test with valid IBAN
        application_data["iban"] = "NL91ABNA0417164300"
        validation_result = validate_application_data(application_data)
        # Should pass IBAN validation (might fail on other fields)
        if not validation_result["valid"]:
            self.assertNotIn("iban", validation_result.get("errors", {}))


def run_tests():
    """Run IBAN validation integration tests"""
    suite = unittest.TestLoader().loadTestsFromTestCase(TestIBANValidationIntegration)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    unittest.main()
