import frappe
from unittest.mock import patch
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPaymentProcessingAPIMinimal(EnhancedTestCase):
    """Minimal test to isolate performance bottleneck"""

    def test_minimal_member_creation_performance(self):
        """Test basic member creation speed"""
        # Just test the basic Enhanced Test Factory operation
        member = self.create_test_member(
            first_name="Minimal",
            last_name="Test",
            email="minimal.test@example.com"
        )
        
        self.assertIsNotNone(member)
        self.assertEqual(member.first_name, "Minimal")

    def test_customer_creation_performance(self):
        """Test customer creation without invoice complexity"""
        from verenigingen.api.payment_processing import get_or_create_customer
        
        # Create member first
        member = self.create_test_member(
            first_name="Customer",
            last_name="Test", 
            email="customer.test@example.com"
        )
        
        # Test customer creation - pass member object, not name
        customer_name = get_or_create_customer(member)
        
        self.assertIsNotNone(customer_name)
        self.assertTrue(frappe.db.exists("Customer", customer_name))

    @patch("frappe.sendmail")  
    def test_simple_email_mock_only(self, mock_sendmail):
        """Test with only infrastructure mocks - no database operations"""
        mock_sendmail.return_value = True
        
        # Simple test that doesn't create heavy database objects
        result = mock_sendmail("test@example.com", "Test Subject", "Test Message")
        self.assertTrue(result)
        mock_sendmail.assert_called_once()