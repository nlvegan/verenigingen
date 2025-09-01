"""
Test Mollie Integration Following Proper Flow

Tests the correct Mollie subscription flow:
1. Create initial payment (establishes mandate on Mollie's side)
2. Then create subscription (now has payment method available)
"""

import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils.payment_gateways import PaymentGatewayFactory


class TestMollieProperFlow(EnhancedTestCase):
    
    def test_mollie_subscription_proper_flow(self):
        """Test proper Mollie subscription flow: payment first, then subscription"""
        
        # Create test member and donation
        member = self.create_test_member(
            first_name="Proper",
            last_name="Flow",
            email=f"properflow{frappe.utils.random_string(6)}@test.nl",
            birth_date="1990-01-01"
        )
        
        donor = self.create_test_donor(
            donor_name=f"{member.first_name} {member.last_name}",
            donor_email=member.email
        )
        
        initial_donation = self.create_test_donation(
            donor=donor.name,
            amount=25.00,
            mode_of_payment="Mollie"
        )
        
        gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")
        
        # Step 1: Create initial payment (this establishes the mandate on Mollie's side)
        print("STEP 1: Creating initial payment to establish mandate...")
        
        form_data = {
            "donor_email": donor.donor_email,
            "payment_method": "Mollie"
        }
        
        payment_result = gateway.process_payment(initial_donation, form_data)
        print(f"INITIAL PAYMENT RESULT: {payment_result}")
        
        if payment_result["status"] == "redirect_required":
            print(f"✅ Initial payment created: {payment_result['payment_id']}")
            print(f"🔗 Payment URL: {payment_result['payment_url']}")
            
            # In real flow, user would complete payment here, establishing mandate
            # For testing, we simulate that this happened by assuming customer now has mandate
            
            # Step 2: Now try creating subscription (should work because customer has payment method)
            print("\nSTEP 2: Creating subscription (customer now has payment method)...")
            
            subscription_data = {
                "amount": 25.00,
                "currency": "EUR", 
                "interval": "1 month",
                "description": "Recurring membership dues"
            }
            
            try:
                subscription_result = gateway.create_subscription(member, subscription_data)
                print(f"SUBSCRIPTION RESULT: {subscription_result}")
                
                if subscription_result.get("status") == "success":
                    print(f"✅ SUBSCRIPTION SUCCESS: {subscription_result['subscription_id']}")
                    print("🎉 Proper Mollie flow completed successfully!")
                else:
                    print(f"❌ SUBSCRIPTION STILL FAILED: {subscription_result.get('message')}")
                    print("💡 This indicates the customer still doesn't have a payment method established")
                    
            except Exception as e:
                print(f"SUBSCRIPTION EXCEPTION: {e}")
                print("💡 This suggests we need to actually complete the first payment for the mandate to work")
                
        else:
            print(f"❌ Initial payment failed: {payment_result}")
            
    def test_understand_mollie_customer_mandate_relationship(self):
        """Understand how Mollie customers and mandates work together"""
        
        # Create a member and test the direct Mollie API relationship
        member = self.create_test_member(
            first_name="Mandate",
            last_name="Test", 
            email=f"mandatetest{frappe.utils.random_string(6)}@test.nl",
            birth_date="1990-01-01"
        )
        
        # Get Mollie settings and client directly
        settings = frappe.get_doc('Mollie Settings', 'Default')
        client = settings.get_mollie_client()
        
        try:
            # Step 1: Create customer on Mollie
            print("STEP 1: Creating Mollie customer...")
            customer_data = {
                "name": f"{member.first_name} {member.last_name}",
                "email": member.email
            }
            
            mollie_customer = client.customers.create(customer_data)
            print(f"✅ MOLLIE CUSTOMER CREATED: {mollie_customer.id}")
            
            # Step 2: Check customer's mandates (should be empty)
            print("\nSTEP 2: Checking customer mandates...")
            mandates = mollie_customer.mandates.list()
            print(f"CUSTOMER MANDATES: {len(mandates)} found")
            
            for mandate in mandates:
                print(f"  - Mandate {mandate.id}: status={mandate.status}, method={mandate.method}")
                
            if len(mandates) == 0:
                print("❌ NO MANDATES: Customer has no payment methods established")
                print("💡 This explains why subscription creation fails")
                
            # Step 3: Try to create subscription anyway (should fail)
            print("\nSTEP 3: Trying to create subscription without mandates...")
            try:
                subscription_data = {
                    "amount": {"currency": "EUR", "value": "25.00"},
                    "interval": "1 month",
                    "description": "Test subscription"
                }
                
                subscription = mollie_customer.subscriptions.create(data=subscription_data)
                print(f"✅ UNEXPECTED SUCCESS: {subscription.id}")
                
            except Exception as sub_error:
                print(f"❌ EXPECTED FAILURE: {sub_error}")
                print("💡 Confirmed: Subscription needs established payment method")
                
        except Exception as e:
            print(f"ERROR IN MANDATE TEST: {e}")
            import traceback
            traceback.print_exc()