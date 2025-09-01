"""
Deep exploration of Mollie API for programmatic completion

Test different payment types and explore the complete API response structure
to find the changePaymentState URL mechanism.
"""

import frappe
import json
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMollieDeepAPIExploration(EnhancedTestCase):
    
    def test_explore_payment_response_structure(self):
        """Explore the complete payment response structure"""
        
        print("🔍 DEEP API EXPLORATION: Complete payment response structure...")
        
        # Get Mollie client
        settings = frappe.get_doc('Mollie Settings', 'Default')
        client = settings.get_mollie_client()
        
        try:
            # Create different types of payments to compare
            print("\\n🔧 Creating different payment types for comparison...")
            
            # 1. Regular payment
            print("\\n1️⃣ REGULAR PAYMENT:")
            regular_payment = client.payments.create({
                "amount": {"currency": "EUR", "value": "10.00"},
                "description": "Regular payment exploration",
                "redirectUrl": "https://example.com/success"
            })
            
            self._explore_payment_object(regular_payment, "REGULAR")
            
            # 2. Payment with customer (for potential recurring)
            print("\\n2️⃣ PAYMENT WITH CUSTOMER:")
            customer = client.customers.create({
                "name": "Test Customer",
                "email": f"explore{frappe.utils.random_string(6)}@test.nl"
            })
            
            customer_payment = client.payments.create({
                "amount": {"currency": "EUR", "value": "15.00"},
                "description": "Customer payment exploration",
                "redirectUrl": "https://example.com/success",
                "customerId": customer.id
            })
            
            self._explore_payment_object(customer_payment, "CUSTOMER")
            
            # 3. Payment with sequenceType first
            print("\\n3️⃣ PAYMENT WITH SEQUENCETYPE FIRST:")
            sequence_payment = client.payments.create({
                "amount": {"currency": "EUR", "value": "20.00"},
                "description": "SequenceType first exploration", 
                "redirectUrl": "https://example.com/success",
                "customerId": customer.id,
                "sequenceType": "first"
            })
            
            self._explore_payment_object(sequence_payment, "SEQUENCETYPE_FIRST")
            
            # 4. Try to create recurring payment (this might fail but worth exploring)
            print("\\n4️⃣ ATTEMPTING RECURRING PAYMENT:")
            try:
                recurring_payment = client.payments.create({
                    "amount": {"currency": "EUR", "value": "25.00"},
                    "description": "Recurring payment exploration",
                    "customerId": customer.id,
                    "sequenceType": "recurring"
                })
                
                self._explore_payment_object(recurring_payment, "RECURRING")
                
            except Exception as e:
                print(f"❌ Recurring payment failed (expected): {e}")
                print("💡 This confirms recurring payments need established mandates")
                
        except Exception as e:
            print(f"❌ EXCEPTION: {e}")
            import traceback
            traceback.print_exc()
            
    def _explore_payment_object(self, payment, payment_type):
        """Helper to explore a payment object structure"""
        
        print(f"\\n🔍 {payment_type} PAYMENT EXPLORATION:")
        print(f"  💳 ID: {payment.id}")
        print(f"  📊 Status: {payment.status}")
        print(f"  💰 Amount: {payment.amount}")
        
        # Check for sequenceType
        sequence_type = getattr(payment, 'sequenceType', 'Not available')
        print(f"  🎯 SequenceType: {sequence_type}")
        
        # Check for customerId
        customer_id = getattr(payment, 'customerId', 'Not available')
        print(f"  👤 Customer ID: {customer_id}")
        
        # Explore the raw JSON response if available
        if hasattr(payment, '__dict__'):
            print(f"\\n📋 RAW OBJECT ATTRIBUTES:")
            for key, value in payment.__dict__.items():
                if not key.startswith('_'):
                    print(f"    {key}: {value}")
                    
        # Look for links
        if hasattr(payment, '_links'):
            print(f"\\n🔗 AVAILABLE LINKS:")
            links_obj = payment._links
            if hasattr(links_obj, '__dict__'):
                for link_name, link_obj in links_obj.__dict__.items():
                    if hasattr(link_obj, 'href'):
                        print(f"    {link_name}: {link_obj.href}")
                        
                        # Special check for change/state related links
                        if 'change' in link_name.lower() or 'state' in link_name.lower():
                            print(f"      🎯 POTENTIAL STATE CHANGE LINK!")
            else:
                print("    Links object has no accessible attributes")
        else:
            print("  ❌ No _links found")
            
        # Check for any test-mode specific attributes
        if hasattr(payment, 'mode'):
            print(f"  🧪 Mode: {payment.mode}")
            
        # Check specific attributes mentioned in docs
        test_attributes = [
            'changePaymentState', 'changepaymentstate_url', '_links',
            'testmode', 'mode', 'profileId'
        ]
        
        print(f"\\n🔧 SPECIFIC ATTRIBUTE CHECK:")
        for attr in test_attributes:
            value = getattr(payment, attr, 'NOT_FOUND')
            print(f"    {attr}: {value}")
            
        return payment
        
    def test_investigate_checkout_url_structure(self):
        """Investigate if the checkout URL itself provides completion options"""
        
        print("🔍 INVESTIGATING: Checkout URL structure for completion hints...")
        
        settings = frappe.get_doc('Mollie Settings', 'Default')
        client = settings.get_mollie_client()
        
        try:
            # Create a payment and examine its checkout URL
            payment = client.payments.create({
                "amount": {"currency": "EUR", "value": "5.00"},
                "description": "Checkout URL investigation",
                "redirectUrl": "https://example.com/success"
            })
            
            print(f"💳 Payment ID: {payment.id}")
            
            # Get checkout URL
            checkout_url = None
            if hasattr(payment, 'checkout_url'):
                checkout_url = payment.checkout_url
            elif hasattr(payment, '_links') and hasattr(payment._links, 'checkout'):
                checkout_url = payment._links.checkout.href
                
            if checkout_url:
                print(f"🔗 Checkout URL: {checkout_url}")
                print("\\n🔍 URL ANALYSIS:")
                print(f"  - Base domain: {'mollie.com' if 'mollie.com' in checkout_url else 'other'}")
                print(f"  - Contains 'test': {'test' in checkout_url.lower()}")
                print(f"  - URL pattern: {'/'.join(checkout_url.split('/')[-3:])}")
                
                # Look for any test mode indicators
                if 'test' in checkout_url.lower():
                    print("  🧪 TEST MODE DETECTED in URL")
                    print("  💡 This suggests test-specific functionality may be available")
                    
            else:
                print("❌ No checkout URL found")
                
        except Exception as e:
            print(f"❌ EXCEPTION: {e}")
            
    def test_try_alternative_completion_approaches(self):
        """Try alternative approaches for programmatic completion"""
        
        print("🔧 TESTING: Alternative approaches for programmatic payment completion...")
        
        settings = frappe.get_doc('Mollie Settings', 'Default')
        client = settings.get_mollie_client()
        
        try:
            # Approach 1: Look for test-specific payment methods
            print("\\n1️⃣ Checking available payment methods...")
            try:
                methods = client.methods.list()
                print(f"Available payment methods: {len(methods)}")
                for method in methods:
                    print(f"  - {method.id}: {method.description}")
            except Exception as e:
                print(f"Methods check failed: {e}")
                
            # Approach 2: Create payment with specific test parameters
            print("\\n2️⃣ Creating payment with test-specific parameters...")
            test_payment = client.payments.create({
                "amount": {"currency": "EUR", "value": "0.01"},  # Minimal amount
                "description": "Test completion investigation",
                "redirectUrl": "https://example.com/success",
                "metadata": {"test": "completion", "auto": "true"}
            })
            
            print(f"💳 Test payment: {test_payment.id}")
            print(f"📊 Status: {test_payment.status}")
            
            # Check if minimal amount or metadata affects available options
            self._explore_payment_object(test_payment, "TEST_SPECIFIC")
            
            print("\\n💡 INVESTIGATION RESULTS:")
            print("  - changePaymentState URL may only appear for specific payment types")
            print("  - Could be limited to recurring payments after first completion")
            print("  - May require specific test mode configuration")
            print("  - Alternative: Use webhook simulation for testing")
            
        except Exception as e:
            print(f"❌ EXCEPTION: {e}")
            import traceback
            traceback.print_exc()
            
        print("\\n🎯 RECOMMENDATION:")
        print("  Since changePaymentState URL isn't readily available,")
        print("  focus on webhook simulation approach for end-to-end testing")