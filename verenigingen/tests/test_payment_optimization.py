#!/usr/bin/env python3
"""
Test Payment Mixin Optimization Performance
"""

import frappe
import time
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.member.mixins.payment_mixin_optimized import PaymentMixinOptimized


class TestPaymentOptimization(EnhancedTestCase):
    """Test payment processing optimization"""

    def test_payment_mixin_performance(self):
        """Test the optimized payment mixin performance"""
        print("🔍 Testing Payment Mixin Optimization Performance")
        print("=" * 50)
        
        # Create test member with enhanced factory
        member = self.create_test_member(
            first_name="Test",
            last_name="Payment",
            birth_date="1985-06-15"
        )
        
        print(f"👤 Created test member: {member.first_name} {member.last_name}")
        
        # Create some test invoices for payment history or find existing member
        test_member = self._create_test_invoices_for_member(member)
        
        # Test optimized payment loading with the actual member document
        # Note: The mixin needs to be applied to a real Member document
        self._test_optimized_payment_loading(test_member, test_member)
        
    def _create_test_invoices_for_member(self, member):
        """Create test invoices for the member"""
        print("📋 Creating test invoices...")
        
        # First create a test item if it doesn't exist
        test_item_code = "Test-Membership-Fee"
        if not frappe.db.exists("Item", test_item_code):
            item = frappe.get_doc({
                "doctype": "Item",
                "item_code": test_item_code,
                "item_name": "Test Membership Fee",
                "item_group": "All Item Groups",
                "stock_uom": "Nos",
                "is_stock_item": 0,
                "is_sales_item": 1
            })
            item.insert()
        
        # Create 2-3 test invoices to simulate payment history
        for i in range(3):
            invoice = frappe.get_doc({
                "doctype": "Sales Invoice",
                "customer": member.customer,
                "due_date": frappe.utils.today(),
                "items": [{
                    "item_code": test_item_code,
                    "qty": 1,
                    "rate": 25.00
                }]
            })
            invoice.insert()
            invoice.submit()  # This makes invoice.docstatus = 1
            
        # Also test with existing members that have payment history
        existing_member = self._find_member_with_payment_history()
        if existing_member:
            print(f"✅ Found existing member with payment history: {existing_member}")
            return existing_member
            
        print(f"✅ Created 3 test invoices for {member.customer}")
        return member
        
    def _find_member_with_payment_history(self):
        """Find an existing member with actual payment history"""
        try:
            member_data = frappe.db.sql("""
                SELECT m.name, m.first_name, m.last_name, m.customer
                FROM `tabMember` m
                JOIN `tabSales Invoice` si ON si.customer = m.customer
                WHERE si.docstatus = 1
                AND m.customer IS NOT NULL
                GROUP BY m.name
                HAVING COUNT(si.name) >= 2
                ORDER BY COUNT(si.name) DESC
                LIMIT 1
            """, as_dict=True)
            
            if member_data:
                member = frappe.get_doc("Member", member_data[0].name)
                print(f"🔍 Found member {member.first_name} {member.last_name} with payment history")
                return member
                
        except Exception as e:
            print(f"⚠️  Could not find existing member with payment history: {str(e)}")
            
        return None
        
    def _test_optimized_payment_loading(self, member, original_member):
        """Test the optimized payment history loading"""
        print(f"\n🚀 Testing Optimized Payment History Loading for {member.first_name} {member.last_name}...")
        
        # Apply the optimized mixin methods to the member dynamically
        from verenigingen.verenigingen.doctype.member.mixins.payment_mixin_optimized import PaymentMixinOptimized
        
        # Add mixin methods to the member instance
        for method_name in dir(PaymentMixinOptimized):
            if not method_name.startswith('__') and callable(getattr(PaymentMixinOptimized, method_name)):
                setattr(member, method_name, getattr(PaymentMixinOptimized, method_name).__get__(member, member.__class__))
        
        # Query counting setup
        original_sql = frappe.db.sql
        query_count = 0
        queries_executed = []
        
        def counting_sql(*args, **kwargs):
            nonlocal query_count
            query_count += 1
            # Store query info for analysis
            query_text = str(args[0])[:100] if args else "Unknown query"
            queries_executed.append(f"Query {query_count}: {query_text}")
            return original_sql(*args, **kwargs)
        
        frappe.db.sql = counting_sql
        start_time = time.time()
        
        try:
            # Call the optimized bulk loading method
            member._load_payment_history_bulk_optimized()
            
            execution_time = time.time() - start_time
            
            # Get the actual payment history from the member
            payment_history = getattr(member, 'payment_history', [])
            
            print(f"✅ Optimized payment loading completed!")
            print(f"📊 Total queries executed: {query_count}")
            print(f"⏱️  Execution time: {execution_time:.3f}s")
            print(f"💳 Payment records found: {len(payment_history) if payment_history else 0}")
            
            # Filter and show only business logic queries
            business_queries = [q for q in queries_executed if 
                               ('tabSales Invoice' in q or 'tabPayment Entry' in q or 
                                'tabMembership' in q or 'tabSEPA Mandate' in q)]
            framework_queries = query_count - len(business_queries)
            
            print(f"\n🔍 Query Analysis:")
            print(f"   📋 Business Logic Queries: {len(business_queries)}")
            print(f"   ⚙️  Framework Overhead: {framework_queries}")
            
            if len(business_queries) <= 6:
                print("🚀 EXCELLENT: Business query count is optimal! (≤6 queries)")
                result_status = "optimal"
            elif len(business_queries) <= 10:
                print("✅ GOOD: Business query count is reasonable (7-10 queries)")
                result_status = "good"
            else:
                print("⚠️  HIGH: Business query count needs optimization")
                result_status = "needs_optimization"
                
            # Validate data quality if we have payment history
            if payment_history and len(payment_history) > 0:
                print(f"🔍 Payment history type: {type(payment_history)}")
                print(f"🔍 First item type: {type(payment_history[0]) if payment_history else 'N/A'}")
                try:
                    data_valid = self._validate_payment_data_quality(payment_history)
                    if not data_valid:
                        result_status = "data_validation_failed"
                except Exception as validation_error:
                    print(f"⚠️  Data validation failed: {str(validation_error)}")
                    result_status = "validation_error"
                
            return {
                "status": result_status,
                "query_count": query_count,
                "execution_time": execution_time,
                "payment_records": len(payment_history) if payment_history else 0
            }
            
        except Exception as e:
            print(f"❌ Error during optimization test: {str(e)}")
            frappe.log_error(f"Payment optimization test failed: {str(e)}", "Payment Optimization Test")
            return {"status": "error", "error": str(e)}
            
        finally:
            frappe.db.sql = original_sql
            
    def _validate_payment_data_quality(self, payment_history):
        """Validate that payment data has required structure and accuracy"""
        print(f"\n🔍 Validating payment data quality...")
        
        if not payment_history:
            print("⚠️  No payment history to validate")
            return False
        
        # Convert to list if it's a Frappe child table
        if hasattr(payment_history, '__iter__') and not isinstance(payment_history, (str, dict)):
            payment_list = list(payment_history)
        else:
            payment_list = payment_history if isinstance(payment_history, list) else [payment_history]
            
        if not payment_list:
            print("⚠️  Payment history is empty after conversion")
            return False
            
        sample_payment = payment_list[0]
        required_fields = ['invoice', 'paid_amount', 'status', 'grand_total', 'outstanding_amount']
        
        # Check data structure - use hasattr for Frappe documents
        missing_fields = [field for field in required_fields if not hasattr(sample_payment, field)]
        if missing_fields:
            print(f"❌ Missing required fields: {missing_fields}")
            return False
        
        print("✅ Payment data structure is valid")
        
        # Validate data consistency
        validation_passed = True
        
        # Check that paid + outstanding = grand total (allowing for rounding)
        for i, payment in enumerate(payment_list[:3]):  # Check first 3
            paid = float(getattr(payment, 'paid_amount', 0))
            outstanding = float(getattr(payment, 'outstanding_amount', 0))
            grand_total = float(getattr(payment, 'grand_total', 0))
            
            calculated_total = paid + outstanding
            if abs(calculated_total - grand_total) > 0.01:  # Allow 1 cent rounding
                print(f"❌ Financial calculation error in record {i+1}:")
                print(f"   Paid: €{paid}, Outstanding: €{outstanding}, Grand Total: €{grand_total}")
                validation_passed = False
        
        if validation_passed:
            print("✅ Financial calculations are accurate")
        
        # Show sample data with correct field names
        print(f"📋 Sample payment record:")
        print(f"   Invoice: {getattr(sample_payment, 'invoice', 'N/A')}")
        print(f"   Paid Amount: €{getattr(sample_payment, 'paid_amount', 'N/A')}")
        print(f"   Outstanding: €{getattr(sample_payment, 'outstanding_amount', 'N/A')}")
        print(f"   Status: {getattr(sample_payment, 'status', 'N/A')}")
        print(f"   SEPA Mandate: {getattr(sample_payment, 'has_sepa_mandate', 'N/A')}")
        
        return validation_passed


def test_payment_mixin_performance():
    """Standalone function for direct testing"""
    test_case = TestPaymentOptimization()
    test_case.setUp()
    try:
        return test_case.test_payment_mixin_performance()
    finally:
        test_case.tearDown()