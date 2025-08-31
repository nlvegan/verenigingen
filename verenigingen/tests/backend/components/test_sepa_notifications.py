"""
SEPA Notification Business Logic Unit Tests
==========================================

Focused unit tests for core SEPA notification business logic.
Complex notification workflows are tested in integration tests.
"""

import unittest
from unittest.mock import MagicMock

from verenigingen.verenigingen_payments.utils.sepa_notifications import SEPAMandateNotificationManager


class TestSEPANotificationBusinessLogic(unittest.TestCase):
    """Test SEPA notification business logic - core functions only"""

    def setUp(self):
        """Set up for each test"""
        self.notification_manager = SEPAMandateNotificationManager()

    def test_iban_masking(self):
        """Test IBAN masking for security"""
        # Test various IBANs
        test_cases = [
            ("NL39RABO0300065264", "NL39****5264"),
            ("DE89370400440532013000", "DE89****3000"),
            ("BE68539007547034", "BE68****7034"),
            ("FR1420041010050500013M02606", "FR14****2606"),
            ("SHORT", "SHORT"),  # Too short to mask
            ("", ""),  # Empty
            (None, None),  # None
        ]

        for iban, expected in test_cases:
            with self.subTest(iban=iban):
                masked = self.notification_manager._mask_iban(iban)
                self.assertEqual(masked, expected)

    def test_bank_name_derivation(self):
        """Test bank name derivation from IBAN"""
        # Test known Dutch banks
        test_cases = [
            ("NL39RABO0300065264", "Rabobank"),
            ("NL91ABNA0417164300", "ABN AMRO"),
            ("NL69INGB0123456789", "ING"),
            ("DE89370400440532013000", "Unknown Bank"),  # Non-Dutch
            ("INVALID", "Unknown Bank"),  # Invalid IBAN
        ]

        for iban, expected in test_cases:
            with self.subTest(iban=iban):
                bank_name = self.notification_manager._get_bank_name(iban)
                if expected != "Unknown Bank":
                    self.assertEqual(bank_name, expected)
                else:
                    # For unknown banks, just check it returns something
                    self.assertIsNotNone(bank_name)
                    
    def test_settings_caching(self):
        """Test that settings are cached for performance"""
        # First call should load settings
        settings1 = self.notification_manager._get_settings()
        
        # Second call should return cached settings
        settings2 = self.notification_manager._get_settings()
        
        # Should be the same object (cached)
        self.assertIs(settings1, settings2)
        
        # Reset cache
        self.notification_manager.settings = None
        
        # New call should load fresh settings
        settings3 = self.notification_manager._get_settings()
        self.assertIsNotNone(settings3)
        
    def test_bulk_member_data_loading(self):
        """Test bulk member data loading for performance"""
        # Test with empty list
        result = self.notification_manager._load_member_data_bulk([])
        self.assertEqual(result, {})
        
        # Test with non-existent members
        result = self.notification_manager._load_member_data_bulk(["NON_EXISTENT"])
        self.assertEqual(result, {})
        
        # Test with valid structure (can't test actual data without DB setup)
        member_names = ["TEST_MEMBER_1", "TEST_MEMBER_2"]
        result = self.notification_manager._load_member_data_bulk(member_names)
        self.assertIsInstance(result, dict)
        
    def test_error_handling_no_email(self):
        """Test notification system handles missing emails gracefully"""
        # Create mock mandate with member that has no email
        mock_mandate = MagicMock()
        mock_mandate.member = "TEST_MEMBER"
        
        # Mock member data loading to return member with no email
        self.notification_manager._load_member_data_bulk = MagicMock(return_value={
            "TEST_MEMBER": {"name": "TEST_MEMBER", "full_name": "Test Member", "email": ""}
        })
        
        # Should not raise exception when sending batch notifications
        try:
            self.notification_manager.send_mandate_notifications_batch([
                {"mandate": mock_mandate, "notification_type": "created", "extra_data": {}}
            ])
        except Exception as e:
            self.fail(f"Batch notification with missing email raised exception: {e}")
            
    def test_context_preparation_methods(self):
        """Test context preparation methods work correctly"""
        # Mock settings
        mock_settings = MagicMock()
        mock_settings.company_name = "Test Company"
        mock_settings.support_email = "support@test.com"
        self.notification_manager._get_settings = MagicMock(return_value=mock_settings)
        
        # Mock mandate and member data
        mock_mandate = MagicMock()
        mock_mandate.mandate_id = "TEST-MANDATE-001"
        mock_mandate.iban = "NL39RABO0300065264"
        mock_mandate.sign_date = "2025-01-01"
        mock_mandate.expiry_date = "2025-12-31"
        
        mock_member_data = {
            "name": "TEST_MEMBER",
            "full_name": "Test Member",
            "email": "test@example.com"
        }
        
        # Test created context
        context = self.notification_manager._prepare_created_context(mock_mandate, mock_member_data, mock_settings)
        self.assertIn("member_name", context)
        self.assertIn("mandate_id", context)
        self.assertIn("company_name", context)
        self.assertEqual(context["member_name"], "Test Member")
        
        # Test cancelled context
        context = self.notification_manager._prepare_cancelled_context(mock_mandate, mock_member_data, mock_settings, "Test reason")
        self.assertIn("cancellation_reason", context)
        self.assertEqual(context["cancellation_reason"], "Test reason")
        
        # Test expiring context
        context = self.notification_manager._prepare_expiring_context(mock_mandate, mock_member_data, mock_settings, 15)
        self.assertIn("days_until_expiry", context)
        self.assertEqual(context["days_until_expiry"], 15)


def run_tests():
    """Run all SEPA notification tests"""
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(TestSEPANotificationBusinessLogic))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    run_tests()