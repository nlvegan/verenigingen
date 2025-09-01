"""
Raw Mollie API Test - No Bullshit

One test. One API call. Whatever happens, happens.
"""

import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils.payment_gateways import PaymentGatewayFactory


class TestMollieRaw(EnhancedTestCase):
    
    def test_mollie_api_raw_call(self):
        """Make one real API call to Mollie. Let it succeed or fail authentically."""
        
        # Get gateway - no safety nets
        gateway = PaymentGatewayFactory.get_gateway("Mollie", "Test Gateway")
        
        # Create minimal test member
        member = self.create_test_member(
            first_name="Raw",
            last_name="Test",
            email=f"rawtest{frappe.utils.random_string(6)}@test.nl",
            birth_date="1990-01-01"
        )
        
        # Make real API call
        result = gateway.create_subscription(member, {
            "amount": 35.00,
            "interval": "1 month", 
            "currency": "EUR",
            "description": "Raw API test"
        })
        
        # Show whatever actually happened
        print(f"REAL RESULT: {result}")
        
        # Basic assertion - whatever comes back should have some structure
        self.assertIsInstance(result, dict)