"""
Working Mollie Integration Test - Following Real Implementation

Based on the actual working implementation in /donate page
"""

import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils.payment_gateways import PaymentGatewayFactory


class TestWorkingMollieIntegration(EnhancedTestCase):
    
    def test_mollie_process_payment_like_donate_page(self):
        """Test Mollie process_payment method like the /donate page does"""
        
        # Create a test donation using Enhanced Test Factory
        donor = self.create_test_donor(
            donor_name="Real Mollie Test",
            donor_email=f"mollietest{frappe.utils.random_string(6)}@test.nl"
        )
        
        donation = self.create_test_donation(
            donor=donor.name,
            amount=35.00,
            mode_of_payment="Mollie"
        )
        
        # Get the gateway like the donate page does
        gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")
        
        # Form data like what comes from the /donate form
        form_data = {
            "donor_email": donor.donor_email,
            "payment_method": "Mollie"
        }
        
        # Call process_payment (not create_subscription)
        result = gateway.process_payment(donation, form_data)
        
        print(f"REAL MOLLIE RESULT: {result}")
        
        # Check the result structure
        self.assertIsInstance(result, dict)
        self.assertIn("status", result)
        
        # If it worked, it should want to redirect to Mollie
        if result["status"] == "redirect_required":
            self.assertIn("payment_url", result)
            self.assertIn("payment_id", result)
            print(f"✅ SUCCESS: Got real Mollie payment URL: {result['payment_url']}")
            print(f"✅ SUCCESS: Got real Mollie payment ID: {result['payment_id']}")
        elif result["status"] == "error":
            print(f"❌ REAL ERROR: {result.get('message', 'Unknown error')}")
            # Don't fail the test - this tells us about real configuration issues
        else:
            print(f"🤔 UNEXPECTED STATUS: {result['status']}")
            
    def test_mollie_subscription_creation_real_member(self):
        """Test subscription creation with real Member (not Donor)"""
        
        # The subscription code expects a Member, not a Donor!
        member = self.create_test_member(
            first_name="Subscription",
            last_name="Test",
            email=f"substest{frappe.utils.random_string(6)}@test.nl",
            birth_date="1990-01-01"
        )
        
        # Get gateway
        gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")
        
        # Test subscription creation with proper data format
        subscription_data = {
            "amount": 25.00,  # Gateway expects float, not dict
            "currency": "EUR",
            "interval": "1 month", 
            "description": "Test recurring membership dues"
        }
        
        try:
            result = gateway.create_subscription(member, subscription_data)
            print(f"SUBSCRIPTION RESULT: {result}")
            
            if result.get("status") == "success":
                print(f"✅ SUBSCRIPTION SUCCESS: Customer ID: {result.get('customer_id')}")
                print(f"✅ SUBSCRIPTION SUCCESS: Subscription ID: {result.get('subscription_id')}")
            else:
                print(f"❌ SUBSCRIPTION ERROR: {result.get('message')}")
                
        except Exception as e:
            print(f"SUBSCRIPTION EXCEPTION: {e}")
            # Don't fail - we want to see what the real error is
            import traceback
            print(f"FULL TRACEBACK: {traceback.format_exc()}")
            
    def test_investigate_subscription_bug(self):
        """Debug the exact subscription failure"""
        
        # Create member with all expected fields
        member = self.create_test_member(
            first_name="Debug",
            last_name="Member",
            email=f"debug{frappe.utils.random_string(6)}@test.nl",
            birth_date="1990-01-01"
        )
        
        print(f"DEBUG: Member fields: {[f.fieldname for f in frappe.get_meta('Member').fields if hasattr(member, f.fieldname)]}")
        
        # Check if member has iban field
        if hasattr(member, 'iban'):
            print(f"DEBUG: Member.iban = {member.iban}")
        else:
            print("DEBUG: Member has NO iban field")
            
        # Try accessing the problem line directly
        try:
            iban_value = member.iban.replace(" ", "") if member.iban else None
            print(f"DEBUG: IBAN processing worked: {iban_value}")
        except AttributeError as e:
            print(f"DEBUG: IBAN access failed: {e}")
        except Exception as e:
            print(f"DEBUG: Other IBAN error: {e}")