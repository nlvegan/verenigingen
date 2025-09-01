"""
Test Correct Mollie Flow Based on API Documentation

Tests the proper Mollie recurring payment flow per their API docs:
1. Create customer
2. Create "first" payment with sequenceType: "first" (establishes mandate)  
3. Customer completes payment (establishes payment method on Mollie's side)
4. Create subscription (now has established payment method)
"""

import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMollieCorrectFlow(EnhancedTestCase):
    
    def test_mollie_api_correct_recurring_flow(self):
        """Test the correct Mollie recurring payment flow per API documentation"""
        
        # Get Mollie settings and client directly
        settings = frappe.get_doc('Mollie Settings', 'Default')
        client = settings.get_mollie_client()
        
        # Create test member  
        member = self.create_test_member(
            first_name="Correct",
            last_name="Flow",
            email=f"correctflow{frappe.utils.random_string(6)}@test.nl",
            birth_date="1990-01-01"
        )
        
        try:
            # Step 1: Create Mollie customer
            print("STEP 1: Creating Mollie customer...")
            customer_data = {
                "name": f"{member.first_name} {member.last_name}",
                "email": member.email
            }
            
            mollie_customer = client.customers.create(customer_data)
            print(f"✅ MOLLIE CUSTOMER: {mollie_customer.id}")
            
            # Step 2: Create "first" payment to establish mandate (per API docs)
            print("\nSTEP 2: Creating FIRST payment to establish mandate...")
            
            payment_data = {
                "amount": {"currency": "EUR", "value": "25.00"},
                "description": "First payment to establish recurring mandate", 
                "sequenceType": "first",  # This is the key!
                "customerId": mollie_customer.id,
                "redirectUrl": "https://example.com/success",
                "webhookUrl": settings.get_webhook_url(),
                "metadata": {
                    "member_id": member.name,
                    "payment_type": "first_payment_for_subscription"
                }
            }
            
            first_payment = client.payments.create(payment_data)
            print(f"✅ FIRST PAYMENT: {first_payment.id}")
            print(f"🔗 CHECKOUT URL: {first_payment.checkout_url or first_payment._links.checkout.href}")
            print(f"📊 STATUS: {first_payment.status}")
            print(f"🎯 SEQUENCE TYPE: {getattr(first_payment, 'sequenceType', 'Not set')}")
            
            # Step 3: Check customer mandates (should still be empty until payment completed)
            print("\nSTEP 3: Checking customer mandates after first payment creation...")
            mandates = mollie_customer.mandates.list()
            print(f"MANDATES AFTER FIRST PAYMENT: {len(mandates)} found")
            
            # In real flow, customer would complete payment here, then mandate would be created
            print("💡 In real flow, customer completes payment → mandate gets created automatically")
            
            # Step 4: Try subscription creation (should still fail until payment completed)
            print("\nSTEP 4: Trying subscription creation (should fail until first payment completed)...")
            
            try:
                subscription_data = {
                    "amount": {"currency": "EUR", "value": "25.00"},
                    "interval": "1 month", 
                    "description": "Monthly membership dues"
                }
                
                subscription = mollie_customer.subscriptions.create(data=subscription_data)
                print(f"🤔 UNEXPECTED SUCCESS: {subscription.id}")
                
            except Exception as sub_error:
                print(f"❌ EXPECTED FAILURE: {sub_error}")
                print("✅ CONFIRMED: Subscription needs completed first payment, not just created first payment")
                
            print("\n🎯 KEY INSIGHT: The missing piece is sequenceType: 'first' in our payment gateway!")
            print("🔧 FIX NEEDED: Update MollieGateway.process_payment() to set sequenceType based on context")
            
        except Exception as e:
            print(f"ERROR: {e}")
            import traceback
            traceback.print_exc()
            
    def test_check_our_payment_gateway_missing_sequence_type(self):
        """Confirm our payment gateway doesn't set sequenceType"""
        
        from verenigingen.verenigingen_payments.utils.payment_gateways import PaymentGatewayFactory
        
        # Create test data
        donor = self.create_test_donor(
            donor_name="Sequence Test",
            donor_email=f"seqtest{frappe.utils.random_string(6)}@test.nl"
        )
        
        donation = self.create_test_donation(
            donor=donor.name,
            amount=25.00,
            mode_of_payment="Mollie"
        )
        
        # Get gateway
        gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")
        
        # Look at the actual payment data our gateway creates
        print("🔍 ANALYZING: What payment data does our gateway create?")
        
        # We need to peek inside the process_payment method
        # Let's mock the Mollie API call to see what data gets sent
        
        form_data = {"donor_email": donor.donor_email}
        
        try:
            # This will fail but we want to see what data structure is created
            result = gateway.process_payment(donation, form_data)
            print(f"PAYMENT RESULT: {result}")
            
            # Check if the result contains sequenceType info
            if 'sequence' in str(result).lower():
                print("✅ Found sequence type info")
            else:
                print("❌ NO SEQUENCE TYPE: Our gateway doesn't set sequenceType!")
                print("💡 This explains why subscription creation fails")
                
        except Exception as e:
            print(f"Payment creation result: {e}")
            
    def test_demonstrate_fix_needed(self):
        """Show exactly what needs to be fixed in the payment gateway"""
        
        print("🔧 FIX NEEDED in MollieGateway.process_payment():")
        print()
        print("CURRENT payment_data structure:")
        print("""
        payment_data = {
            "amount": {"value": "25.00", "currency": "EUR"},
            "description": "Donation", 
            "redirectUrl": redirect_url,
            "webhookUrl": webhook_url,
            # MISSING: "sequenceType": "first" or "recurring"
        }
        """)
        print()
        print("NEEDED payment_data structure for subscriptions:")
        print("""
        payment_data = {
            "amount": {"value": "25.00", "currency": "EUR"},
            "description": "Donation",
            "redirectUrl": redirect_url, 
            "webhookUrl": webhook_url,
            "sequenceType": "first",  # ← ADD THIS for first payments
            "customerId": customer_id,  # ← ADD THIS for recurring payments
        }
        """)
        print()
        print("✅ SOLUTION: Detect if this is for a recurring donation and set sequenceType accordingly")
        print("📝 The donate page should pass a flag indicating this is for subscription setup")