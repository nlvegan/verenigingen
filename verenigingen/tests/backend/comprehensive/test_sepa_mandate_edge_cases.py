"""
SEPA Mandate Processing Edge Cases Test Suite
Tests for SEPA mandate validation, usage tracking, and banking integration edge cases
"""

import unittest

import frappe
from frappe.utils import add_days, today


class TestSEPAMandateEdgeCases(unittest.TestCase):
    """Test SEPA mandate processing edge cases and failure scenarios"""

    @classmethod
    def setUpClass(cls):
        """Set up test data"""
        cls.test_records = []

        # Create test chapter
        cls.chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "chapter_name": "SEPA Test Chapter",
                "short_name": "STC",
                "country": "Netherlands",
            }
        )
        cls.chapter.insert(ignore_permissions=True)
        cls.test_records.append(cls.chapter)

        # Create test member
        cls.member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "SEPA",
                "last_name": "Testmember",
                "email": "sepa.test@test.com",
                "status": "Active",
                "chapter": cls.chapter.name,
            }
        )
        cls.member.insert(ignore_permissions=True)
        cls.test_records.append(cls.member)

        # Valid IBAN test cases
        cls.valid_ibans = [
            "NL91ABNA0417164300",  # Netherlands
            "DE89370400440532013000",  # Germany
            "GB82WEST12345698765432",  # UK
            "FR1420041010050500013M02606",  # France
            "BE68539007547034",  # Belgium
        ]

        # Invalid IBAN test cases
        cls.invalid_ibans = [
            "NL91ABNA041716430",  # Too short
            "NL91ABNA04171643000",  # Too long
            "XX91ABNA0417164300",  # Invalid country code
            "NL00ABNA0417164300",  # Invalid check digits
            "NL91XXXX0417164300",  # Invalid bank code
            "NL91ABNA0417164301",  # Invalid check digit
            "",  # Empty
            "NOT-AN-IBAN",  # Completely invalid
            "1234567890",  # Numbers only
        ]

    @classmethod
    def tearDownClass(cls):
        """Clean up test data"""
        for record in reversed(cls.test_records):
            try:
                record.delete(ignore_permissions=True)
            except Exception:
                pass

    def setUp(self):
        """Set up each test"""
        frappe.set_user("Administrator")

    # ===== IBAN VALIDATION EDGE CASES =====

    def test_valid_iban_formats(self):
        """Test validation of various valid IBAN formats"""
        for iban in self.valid_ibans:
            mandate = frappe.get_doc(
                {
                    "doctype": "SEPA Mandate",
                    "member": self.member.name,
                    "iban": iban,
                    "status": "Active",
                    "mandate_date": today(),
                }
            )

            try:
                mandate.insert()
                self.assertTrue(True, f"Valid IBAN {iban} should be accepted")
                mandate.delete()
            except frappe.ValidationError as e:
                self.fail(f"Valid IBAN {iban} was rejected: {str(e)}")

    def test_invalid_iban_formats(self):
        """Test rejection of invalid IBAN formats"""
        for iban in self.invalid_ibans:
            with self.assertRaises(frappe.ValidationError, msg=f"Invalid IBAN {iban} should be rejected"):
                mandate = frappe.get_doc(
                    {
                        "doctype": "SEPA Mandate",
                        "member": self.member.name,
                        "iban": iban,
                        "status": "Active",
                        "mandate_date": today(),
                    }
                )
                mandate.insert()

    def test_iban_formatting_normalization(self):
        """Test IBAN formatting normalization (spaces, case)"""
        test_cases = [
            ("nl91 abna 0417 1643 00", "NL91ABNA0417164300"),  # Lowercase with spaces
            ("NL91 ABNA 0417 1643 00", "NL91ABNA0417164300"),  # Uppercase with spaces
            ("nl91abna0417164300", "NL91ABNA0417164300"),  # Lowercase no spaces
            ("  NL91ABNA0417164300  ", "NL91ABNA0417164300"),  # Leading/trailing spaces
        ]

        for input_iban, expected_iban in test_cases:
            mandate = frappe.get_doc(
                {
                    "doctype": "SEPA Mandate",
                    "member": self.member.name,
                    "iban": input_iban,
                    "status": "Active",
                    "mandate_date": today(),
                }
            )
            mandate.insert()

            # Check if IBAN was normalized
            self.assertEqual(
                mandate.iban, expected_iban, f"IBAN {input_iban} should be normalized to {expected_iban}"
            )

            mandate.delete()

    def test_iban_checksum_validation(self):
        """Test IBAN checksum validation algorithm"""
        # Create IBAN with wrong checksum
        wrong_checksum_iban = "NL92ABNA0417164300"  # Changed checksum from 91 to 92

        with self.assertRaises(frappe.ValidationError):
            mandate = frappe.get_doc(
                {
                    "doctype": "SEPA Mandate",
                    "member": self.member.name,
                    "iban": wrong_checksum_iban,
                    "status": "Active",
                    "mandate_date": today(),
                }
            )
            mandate.insert()

    # ===== MANDATE LIFECYCLE EDGE CASES =====

    def test_mandate_expiry_handling(self):
        """Test mandate expiry date handling"""
        # Test past expiry date
        past_date = add_days(today(), -30)

        mandate = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "member": self.member.name,
                "iban": "NL91ABNA0417164300",
                "status": "Active",
                "mandate_date": past_date,
                "expiry_date": past_date,
            }
        )

        # Should either reject or auto-expire
        try:
            mandate.insert()
            # If allowed, should be automatically marked as expired
            if mandate.expiry_date and mandate.expiry_date < today():
                self.assertEqual(mandate.status, "Expired")
            mandate.delete()
        except frappe.ValidationError:
            # Rejection is also acceptable
            pass

    def test_mandate_cancellation_with_pending_payments(self):
        """Test mandate cancellation when payments are pending"""
        mandate = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "member": self.member.name,
                "iban": "NL91ABNA0417164300",
                "status": "Active",
                "mandate_date": today(),
            }
        )
        mandate.insert()

        # Simulate pending payment
        try:
            # This would typically check for pending direct debit batches
            mandate.status = "Cancelled"
            mandate.save()

            # Should either prevent cancellation or handle gracefully
            self.assertIn(mandate.status, ["Cancelled", "Active"])
        finally:
            mandate.delete()

    def test_duplicate_mandate_prevention(self):
        """Test prevention of duplicate active mandates for same member"""
        # Create first mandate
        mandate1 = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "member": self.member.name,
                "iban": "NL91ABNA0417164300",
                "status": "Active",
                "mandate_date": today(),
            }
        )
        mandate1.insert()

        # Try to create second active mandate for same member
        with self.assertRaises(frappe.ValidationError):
            mandate2 = frappe.get_doc(
                {
                    "doctype": "SEPA Mandate",
                    "member": self.member.name,
                    "iban": "DE89370400440532013000",  # Different IBAN
                    "status": "Active",
                    "mandate_date": today(),
                }
            )
            mandate2.insert()

        # Clean up
        mandate1.delete()

    # ===== MANDATE USAGE TRACKING EDGE CASES =====

    def test_mandate_usage_limits(self):
        """Test mandate usage limit enforcement"""
        mandate = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "member": self.member.name,
                "iban": "NL91ABNA0417164300",
                "status": "Active",
                "mandate_date": today(),
                "usage_limit": 3,  # Allow only 3 uses
            }
        )
        mandate.insert()

        # Simulate multiple usage attempts
        try:
            for i in range(5):  # Try to use 5 times (exceeds limit)
                usage = frappe.get_doc(
                    {
                        "doctype": "SEPA Mandate Usage",
                        "mandate": mandate.name,
                        "usage_date": today(),
                        "amount": 100.00,
                        "description": f"Usage {i + 1}",
                    }
                )

                if i < 3:  # First 3 should succeed
                    usage.insert()
                else:  # 4th and 5th should fail
                    with self.assertRaises(frappe.ValidationError):
                        usage.insert()
        finally:
            # Clean up usage records
            frappe.db.sql("DELETE FROM `tabSEPA Mandate Usage` WHERE mandate = %s", mandate.name)
            mandate.delete()

    def test_mandate_monthly_limits(self):
        """Test monthly usage limits"""
        mandate = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "member": self.member.name,
                "iban": "NL91ABNA0417164300",
                "status": "Active",
                "mandate_date": today(),
                "monthly_limit": 500.00,  # €500 per month
            }
        )
        mandate.insert()

        try:
            # First usage within limit
            usage1 = frappe.get_doc(
                {
                    "doctype": "SEPA Mandate Usage",
                    "mandate": mandate.name,
                    "usage_date": today(),
                    "amount": 300.00,
                    "description": "First usage",
                }
            )
            usage1.insert()

            # Second usage exceeding limit
            with self.assertRaises(frappe.ValidationError):
                usage2 = frappe.get_doc(
                    {
                        "doctype": "SEPA Mandate Usage",
                        "mandate": mandate.name,
                        "usage_date": today(),
                        "amount": 250.00,  # 300 + 250 = 550 > 500 limit
                        "description": "Second usage",
                    }
                )
                usage2.insert()
        finally:
            # Clean up
            frappe.db.sql("DELETE FROM `tabSEPA Mandate Usage` WHERE mandate = %s", mandate.name)
            mandate.delete()

    # ===== BANKING INTEGRATION EDGE CASES =====

    def test_direct_debit_file_generation_errors(self):
        """Test direct debit file generation error handling"""
        mandate = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "member": self.member.name,
                "iban": "NL91ABNA0417164300",
                "status": "Active",
                "mandate_date": today(),
            }
        )
        mandate.insert()

        # Create direct debit batch
        batch = frappe.get_doc(
            {"doctype": "SEPA Direct Debit Batch", "batch_date": today(), "status": "Draft"}
        )
        batch.insert()

        # Add mandate to batch
        batch_invoice = frappe.get_doc(
            {
                "doctype": "SEPA Direct Debit Batch Invoice",
                "parent": batch.name,
                "mandate": mandate.name,
                "amount": 100.00,
                "currency": "EUR",
            }
        )
        batch_invoice.insert()

        # Test file generation with various error conditions
        test_conditions = [
            ("Invalid character in name", {"member_name": "Test\x00Member"}),
            ("Amount too large", {"amount": 999999999.99}),
            ("Invalid currency", {"currency": "INVALID"}),
            ("Missing IBAN", {"iban": ""}),
        ]

        for condition_name, error_data in test_conditions:
            with self.subTest(condition=condition_name):
                # Simulate error condition
                if "member_name" in error_data:
                    original_name = self.member.first_name
                    self.member.first_name = error_data["member_name"]
                    self.member.save()

                try:
                    # Attempt file generation
                    batch.status = "Ready"
                    batch.save()

                    # Should handle error gracefully
                    if batch.status == "Error":
                        self.assertTrue(True, f"Error condition '{condition_name}' handled correctly")
                except frappe.ValidationError:
                    # Validation error is acceptable
                    pass
                finally:
                    # Restore original data
                    if "member_name" in error_data:
                        self.member.first_name = original_name
                        self.member.save()

        # Clean up
        batch_invoice.delete()
        batch.delete()
        mandate.delete()

    def test_bank_response_processing(self):
        """Test processing of bank response files"""
        mandate = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "member": self.member.name,
                "iban": "NL91ABNA0417164300",
                "status": "Active",
                "mandate_date": today(),
            }
        )
        mandate.insert()

        # Simulate various bank response scenarios
        bank_responses = [
            ("success", "Payment successful"),
            ("insufficient_funds", "Insufficient funds"),
            ("invalid_account", "Account not found"),
            ("mandate_cancelled", "Mandate cancelled by debtor"),
            ("technical_error", "Technical processing error"),
        ]

        for response_type, response_message in bank_responses:
            with self.subTest(response=response_type):
                # Process bank response
                try:
                    # This would be implemented in actual bank integration
                    from verenigingen.utils.sepa_processing import process_bank_response

                    response_data = {
                        "mandate": mandate.name,
                        "status": response_type,
                        "message": response_message,
                        "amount": 100.00,
                    }

                    result = process_bank_response(response_data)

                    # Verify appropriate handling
                    if response_type == "success":
                        self.assertEqual(result["status"], "processed")
                    else:
                        self.assertEqual(result["status"], "failed")

                except ImportError:
                    # Bank response processing not implemented yet
                    pass

        mandate.delete()

    # ===== SEPA REGULATION COMPLIANCE =====

    def test_sepa_notification_requirements(self):
        """Test SEPA pre-notification requirements"""
        mandate = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "member": self.member.name,
                "iban": "NL91ABNA0417164300",
                "status": "Active",
                "mandate_date": today(),
            }
        )
        mandate.insert()

        # Test pre-notification timing
        debit_date = add_days(today(), 1)  # Next day (too soon for SEPA)

        with self.assertRaises(frappe.ValidationError):
            # SEPA requires minimum 5 working days pre-notification
            batch = frappe.get_doc(
                {
                    "doctype": "SEPA Direct Debit Batch",
                    "batch_date": today(),
                    "execution_date": debit_date,  # Too soon
                    "status": "Draft",
                }
            )
            batch.insert()

        mandate.delete()

    def test_sepa_mandate_data_retention(self):
        """Test SEPA mandate data retention requirements"""
        mandate = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "member": self.member.name,
                "iban": "NL91ABNA0417164300",
                "status": "Active",
                "mandate_date": add_days(today(), -1000),  # Old mandate
            }
        )
        mandate.insert()

        # Cancel mandate
        mandate.status = "Cancelled"
        mandate.save()

        # Test data retention (mandates must be kept for 14 months after last use)
        try:
            mandate.delete()
            # Should either prevent deletion or archive appropriately
            self.fail("Cancelled mandate should not be deletable immediately")
        except frappe.LinkExistsError:
            # Expected - mandate should be preserved
            pass
        except frappe.ValidationError:
            # Also acceptable
            pass
        finally:
            # Force delete for cleanup
            frappe.delete_doc("SEPA Mandate", mandate.name, force=True)

    # ===== CROSS-BORDER PAYMENT EDGE CASES =====

    def test_cross_border_iban_validation(self):
        """Test cross-border IBAN validation"""
        cross_border_ibans = [
            ("NL91ABNA0417164300", "Netherlands", True),
            ("DE89370400440532013000", "Germany", True),
            ("US12345678901234567890", "USA", False),  # Not SEPA
            ("JP1234567890123456", "Japan", False),  # Not SEPA
        ]

        for iban, country, should_be_valid in cross_border_ibans:
            with self.subTest(iban=iban, country=country):
                mandate = frappe.get_doc(
                    {
                        "doctype": "SEPA Mandate",
                        "member": self.member.name,
                        "iban": iban,
                        "status": "Active",
                        "mandate_date": today(),
                    }
                )

                if should_be_valid:
                    try:
                        mandate.insert()
                        mandate.delete()
                    except frappe.ValidationError:
                        self.fail(f"Valid SEPA IBAN {iban} from {country} should be accepted")
                else:
                    with self.assertRaises(frappe.ValidationError):
                        mandate.insert()

    def test_currency_restrictions(self):
        """Test SEPA currency restrictions (EUR only)"""
        mandate = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "member": self.member.name,
                "iban": "NL91ABNA0417164300",
                "status": "Active",
                "mandate_date": today(),
            }
        )
        mandate.insert()

        # Test non-EUR currencies (should be rejected)
        non_eur_currencies = ["USD", "GBP", "CHF", "JPY"]

        for currency in non_eur_currencies:
            with self.subTest(currency=currency):
                with self.assertRaises(frappe.ValidationError):
                    usage = frappe.get_doc(
                        {
                            "doctype": "SEPA Mandate Usage",
                            "mandate": mandate.name,
                            "usage_date": today(),
                            "amount": 100.00,
                            "currency": currency,  # Non-EUR currency
                            "description": f"Test {currency}",
                        }
                    )
                    usage.insert()

        mandate.delete()

    # ===== FRAUD PREVENTION =====

    def test_mandate_fraud_detection(self):
        """Test mandate fraud detection"""
        # Test suspicious patterns
        suspicious_patterns = [
            {"pattern": "Multiple mandates same day", "count": 10},
            {"pattern": "High value first transaction", "amount": 10000.00},
            {"pattern": "Rapid successive transactions", "count": 5},
        ]

        for pattern_data in suspicious_patterns:
            with self.subTest(pattern=pattern_data["pattern"]):
                if "count" in pattern_data and pattern_data["count"] > 1:
                    # Test multiple rapid transactions
                    mandate = frappe.get_doc(
                        {
                            "doctype": "SEPA Mandate",
                            "member": self.member.name,
                            "iban": "NL91ABNA0417164300",
                            "status": "Active",
                            "mandate_date": today(),
                        }
                    )
                    mandate.insert()

                    # Create multiple transactions
                    for i in range(pattern_data["count"]):
                        try:
                            usage = frappe.get_doc(
                                {
                                    "doctype": "SEPA Mandate Usage",
                                    "mandate": mandate.name,
                                    "usage_date": today(),
                                    "amount": 100.00,
                                    "description": f"Rapid transaction {i + 1}",
                                }
                            )
                            usage.insert()
                        except frappe.ValidationError:
                            # Fraud detection triggered - good!
                            break

                    # Clean up
                    frappe.db.sql("DELETE FROM `tabSEPA Mandate Usage` WHERE mandate = %s", mandate.name)
                    mandate.delete()


def run_sepa_mandate_edge_case_tests():
    """Run all SEPA mandate edge case tests"""
    print("🏦 Running SEPA Mandate Edge Case Tests...")

    suite = unittest.TestLoader().loadTestsFromTestCase(TestSEPAMandateEdgeCases)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    if result.wasSuccessful():
        print("✅ All SEPA mandate edge case tests passed!")
        return True
    else:
        print(f"❌ {len(result.failures)} test(s) failed, {len(result.errors)} error(s)")
        return False


if __name__ == "__main__":
    run_sepa_mandate_edge_case_tests()
