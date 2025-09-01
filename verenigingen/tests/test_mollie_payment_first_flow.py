"""
Test the correct payment-first flow as per Mollie API documentation

This test implements the proper Mollie flow:
1. Create customer
2. Create FIRST payment with sequenceType: "first" 
3. Customer completes payment (establishes mandate)
4. Create subscription (now has payment method)
"""

import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMolliePaymentFirstFlow(EnhancedTestCase):
    
    def test_implement_correct_mollie_flow_in_gateway(self):
        """Test implementing the correct Mollie flow in our payment gateway"""
        
        # Create test member and donor
        member = self.create_test_member(
            first_name="Payment",
            last_name="First",
            email=f"paymentfirst{frappe.utils.random_string(6)}@test.nl",
            birth_date="1990-01-01"
        )
        
        donor = self.create_test_donor(
            donor_name=f"{member.first_name} {member.last_name}",
            donor_email=member.email
        )
        
        # Create donation marked for subscription setup
        donation = self.create_test_donation(
            donor=donor.name,
            amount=50.00,
            mode_of_payment="Mollie"
        )
        
        from verenigingen.verenigingen_payments.utils.payment_gateways import PaymentGatewayFactory
        gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")
        
        print("🔧 TESTING: Modified gateway approach for subscription setup...")
        
        # Step 1: Create payment with context indicating this is for subscription setup
        form_data = {
            "donor_email": donor.donor_email,
            "subscription_setup": True  # This should trigger sequenceType: "first"
        }
        
        # This should work - payment creation with proper sequenceType
        payment_result = gateway.process_payment(donation, form_data)
        print(f"PAYMENT RESULT: {payment_result}")
        
        if payment_result["status"] == "redirect_required":
            print(f"✅ Payment created successfully: {payment_result['payment_id']}")
            print(f"🔗 Checkout URL: {payment_result['payment_url']}")
            
            # In the real flow, customer would complete this payment, establishing the mandate
            print("💡 Customer completes payment → mandate established automatically")
            
            # Step 2: Now subscription creation should work (in theory)
            subscription_data = {
                "amount": 50.00,
                "currency": "EUR",
                "interval": "1 month",
                "description": "Monthly membership after payment completed"
            }
            
            try:
                subscription_result = gateway.create_subscription(member, subscription_data)
                print(f"SUBSCRIPTION RESULT: {subscription_result}")
                
                if subscription_result.get("status") == "success":
                    print("✅ SUCCESS: Subscription created after first payment!")
                else:
                    print(f"❌ SUBSCRIPTION STILL FAILED: {subscription_result.get('message')}")
                    print("💡 The first payment needs to be COMPLETED, not just created")
                    
            except Exception as e:
                print(f"SUBSCRIPTION ERROR: {e}")
                print("💡 Still need to complete the first payment for mandate to exist")
                
        else:
            print(f"❌ Payment creation failed: {payment_result}")
            
    def test_check_if_sequencetype_fixes_issue(self):
        """Check if adding sequenceType to payment fixes the mandate issue"""
        
        # Get Mollie settings and client directly for testing
        settings = frappe.get_doc('Mollie Settings', 'Default')
        client = settings.get_mollie_client()
        
        member = self.create_test_member(
            first_name="Sequence",
            last_name="Fix",
            email=f"sequencefix{frappe.utils.random_string(6)}@test.nl", 
            birth_date="1990-01-01"
        )
        
        try:
            # Step 1: Create customer
            print("STEP 1: Creating customer...")
            customer = client.customers.create({
                "name": f"{member.first_name} {member.last_name}",
                "email": member.email
            })
            print(f"✅ Customer created: {customer.id}")
            
            # Step 2: Create first payment WITH sequenceType
            print("\\nSTEP 2: Creating first payment WITH sequenceType...")
            payment_data = {
                "amount": {"currency": "EUR", "value": "50.00"},
                "description": "First payment with sequenceType",
                "sequenceType": "first",  # THIS IS THE KEY
                "customerId": customer.id,
                "redirectUrl": "https://example.com/success",
                "webhookUrl": settings.get_webhook_url(),
                "metadata": {
                    "member_id": member.name,
                    "payment_type": "subscription_setup"
                }
            }
            
            payment = client.payments.create(payment_data)
            print(f"✅ Payment created: {payment.id}")
            print(f"🔗 Checkout URL: {payment.checkout_url or payment._links.checkout.href}")
            print(f"🎯 Sequence Type: {getattr(payment, 'sequenceType', 'Not available')}")
            
            # Step 3: Check mandates (still empty until payment completed)
            print("\\nSTEP 3: Checking mandates after first payment creation...")
            mandates = customer.mandates.list()
            print(f"MANDATES: {len(mandates)} found")
            
            # Step 4: Try subscription creation
            print("\\nSTEP 4: Testing subscription creation...")
            try:
                subscription_data = {
                    "amount": {"currency": "EUR", "value": "50.00"},
                    "interval": "1 month",
                    "description": "Test subscription after first payment"
                }
                
                subscription = customer.subscriptions.create(data=subscription_data)
                print(f"🤔 UNEXPECTED SUCCESS: {subscription.id}")
                print("💡 The sequenceType parameter allows subscription creation!")
                
            except Exception as sub_error:
                print(f"❌ STILL FAILING: {sub_error}")
                print("💡 Even with sequenceType, subscription needs COMPLETED first payment")
                
        except Exception as e:
            print(f"ERROR: {e}")
            import traceback
            traceback.print_exc()