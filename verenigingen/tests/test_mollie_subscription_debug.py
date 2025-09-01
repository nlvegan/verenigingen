"""
Debug the exact subscription failure
"""

import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils.payment_gateways import PaymentGatewayFactory


class TestMollieSubscriptionDebug(EnhancedTestCase):
    
    def test_check_mollie_settings(self):
        """Check if Mollie settings are properly configured"""
        
        try:
            # Get all Mollie settings
            settings_list = frappe.get_all('Mollie Settings', fields=['gateway_name', 'enable_subscriptions', 'test_mode'])
            print(f"MOLLIE SETTINGS: {settings_list}")
            
            if settings_list:
                # Get the first one in detail
                settings_name = settings_list[0]['gateway_name']
                settings = frappe.get_doc('Mollie Settings', settings_name)
                print(f"SUBSCRIPTION ENABLED: {settings.enable_subscriptions}")
                print(f"TEST MODE: {settings.test_mode}")
                
                # Check if test API key exists
                test_key = settings.get_password('test_secret_key')
                print(f"HAS TEST KEY: {bool(test_key)}")
                if test_key:
                    print(f"TEST KEY FORMAT: {test_key[:10]}...{test_key[-5:] if len(test_key) > 15 else test_key}")
                    
        except Exception as e:
            print(f"ERROR CHECKING SETTINGS: {e}")
            import traceback
            traceback.print_exc()
            
    def test_direct_mollie_settings_subscription(self):
        """Test calling create_subscription directly on Mollie Settings"""
        
        # Get Mollie Settings
        settings = frappe.get_doc('Mollie Settings', 'Default')
        
        # Test customer data
        customer_data = {
            "name": "Test Customer",
            "email": "test@example.com"
        }
        
        # Test subscription data
        subscription_data = {
            "amount": {"currency": "EUR", "value": "25.00"},
            "interval": "1 month",
            "description": "Test subscription"
        }
        
        try:
            result = settings.create_subscription(customer_data, subscription_data)
            print(f"DIRECT SUBSCRIPTION RESULT: {result}")
        except Exception as e:
            print(f"DIRECT SUBSCRIPTION ERROR: {e}")
            import traceback
            print(f"FULL TRACEBACK:\n{traceback.format_exc()}")