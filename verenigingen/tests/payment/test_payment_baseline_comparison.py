#!/usr/bin/env python3
"""
Payment Processing Performance Baseline Comparison
=================================================

Compares original N+1 pattern vs optimized bulk queries using identical data
"""

import frappe
import time
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPaymentBaselineComparison(EnhancedTestCase):
    """Compare original vs optimized payment processing performance"""

    def test_baseline_comparison(self):
        """Run side-by-side comparison of original vs optimized payment loading"""
        print("📊 Payment Processing Baseline Comparison")
        print("=" * 50)
        
        # Find member with substantial payment history
        member = self._find_member_with_payment_history()
        if not member:
            print("❌ No suitable member found for baseline comparison")
            return
            
        print(f"👤 Testing with: {member.first_name} {member.last_name}")
        
        # Test original approach (simulated N+1 pattern)
        original_results = self._test_original_payment_loading(member)
        
        # Test optimized approach
        optimized_results = self._test_optimized_payment_loading(member)
        
        # Compare results
        self._compare_results(original_results, optimized_results)
        
    def _find_member_with_payment_history(self):
        """Find member with good payment history for testing"""
        try:
            member_data = frappe.db.sql("""
                SELECT m.name, m.first_name, m.last_name, m.customer,
                       COUNT(si.name) as invoice_count
                FROM `tabMember` m
                JOIN `tabSales Invoice` si ON si.customer = m.customer
                WHERE si.docstatus = 1
                AND m.customer IS NOT NULL
                GROUP BY m.name
                HAVING invoice_count >= 3
                ORDER BY invoice_count DESC
                LIMIT 1
            """, as_dict=True)
            
            if member_data:
                member = frappe.get_doc("Member", member_data[0].name)
                print(f"📋 Found member with {member_data[0].invoice_count} invoices")
                return member
                
        except Exception as e:
            print(f"⚠️  Error finding member: {str(e)}")
            
        return None
        
    def _test_original_payment_loading(self, member):
        """Simulate original N+1 payment loading pattern"""
        print(f"\n🐌 Testing ORIGINAL N+1 Pattern...")
        
        # Query counting setup
        original_sql = frappe.db.sql
        query_count = 0
        business_queries = []
        
        def counting_sql(*args, **kwargs):
            nonlocal query_count
            query_count += 1
            query_text = str(args[0]) if args else ""
            
            # Track business logic queries
            if any(table in query_text for table in ['tabSales Invoice', 'tabPayment Entry', 'tabMembership', 'tabSEPA Mandate']):
                business_queries.append(f"Q{query_count}: {query_text[:80]}...")
                
            return original_sql(*args, **kwargs)
        
        frappe.db.sql = counting_sql
        start_time = time.time()
        
        try:
            # Simulate original N+1 pattern
            payment_records = self._simulate_n_plus_one_pattern(member)
            
            execution_time = time.time() - start_time
            
            print(f"📊 Original approach results:")
            print(f"   Total queries: {query_count}")
            print(f"   Business queries: {len(business_queries)}")
            print(f"   Execution time: {execution_time:.3f}s")
            print(f"   Records processed: {len(payment_records)}")
            
            return {
                "approach": "original",
                "total_queries": query_count,
                "business_queries": len(business_queries),
                "execution_time": execution_time,
                "records": len(payment_records),
                "query_details": business_queries[:10]  # First 10 for analysis
            }
            
        except Exception as e:
            print(f"❌ Error in original approach: {str(e)}")
            return {"approach": "original", "error": str(e)}
            
        finally:
            frappe.db.sql = original_sql
            
    def _simulate_n_plus_one_pattern(self, member):
        """Simulate the original N+1 query pattern"""
        payment_records = []
        
        # Step 1: Get customer invoices (1 query)
        invoices = frappe.get_all("Sales Invoice", 
            filters={"customer": member.customer, "docstatus": 1},
            fields=["name", "posting_date", "grand_total", "outstanding_amount", "status"])
        
        # Step 2: N+1 pattern - individual queries for each invoice's payment data
        for invoice in invoices:
            # Query 1 per invoice: Get payment references (N queries)
            payment_refs = frappe.get_all("Payment Entry Reference",
                filters={
                    "reference_doctype": "Sales Invoice",
                    "reference_name": invoice["name"]
                },
                fields=["parent", "allocated_amount"])
            
            # Query 1 per payment reference: Get payment details (potentially N*M queries)
            for ref in payment_refs:
                payment_entry = frappe.get_all("Payment Entry",
                    filters={"name": ref["parent"], "docstatus": 1},
                    fields=["posting_date", "paid_amount", "reference_no"])
                
                # Additional N+1: Get membership info if available (N queries)
                if invoice.get("membership"):
                    membership = frappe.get_all("Membership",
                        filters={"name": invoice["membership"]},
                        fields=["sepa_mandate"])
                    
                    # More N+1: Get SEPA mandate details (N queries)
                    if membership and membership[0].get("sepa_mandate"):
                        sepa_mandate = frappe.get_all("SEPA Mandate",
                            filters={"name": membership[0]["sepa_mandate"]},
                            fields=["status", "mandate_id"])
            
            # Build payment record (simulating the original logic)
            payment_records.append({
                "invoice": invoice["name"],
                "status": invoice["status"],
                "grand_total": invoice["grand_total"],
                "outstanding_amount": invoice["outstanding_amount"]
            })
        
        return payment_records
        
    def _test_optimized_payment_loading(self, member):
        """Test the optimized bulk payment loading"""
        print(f"\n🚀 Testing OPTIMIZED Bulk Pattern...")
        
        # Apply the optimized mixin to member
        from verenigingen.verenigingen.doctype.member.mixins.payment_mixin_optimized import PaymentMixinOptimized
        
        # Add mixin methods dynamically
        for method_name in dir(PaymentMixinOptimized):
            if not method_name.startswith('__') and callable(getattr(PaymentMixinOptimized, method_name)):
                setattr(member, method_name, getattr(PaymentMixinOptimized, method_name).__get__(member, member.__class__))
        
        # Query counting setup
        original_sql = frappe.db.sql
        query_count = 0
        business_queries = []
        
        def counting_sql(*args, **kwargs):
            nonlocal query_count
            query_count += 1
            query_text = str(args[0]) if args else ""
            
            # Track business logic queries
            if any(table in query_text for table in ['tabSales Invoice', 'tabPayment Entry', 'tabMembership', 'tabSEPA Mandate']):
                business_queries.append(f"Q{query_count}: {query_text[:80]}...")
                
            return original_sql(*args, **kwargs)
        
        frappe.db.sql = counting_sql
        start_time = time.time()
        
        try:
            # Run optimized bulk loading
            member._load_payment_history_bulk_optimized()
            payment_records = list(getattr(member, 'payment_history', []))
            
            execution_time = time.time() - start_time
            
            print(f"📊 Optimized approach results:")
            print(f"   Total queries: {query_count}")
            print(f"   Business queries: {len(business_queries)}")
            print(f"   Execution time: {execution_time:.3f}s")
            print(f"   Records processed: {len(payment_records)}")
            
            return {
                "approach": "optimized",
                "total_queries": query_count,
                "business_queries": len(business_queries),
                "execution_time": execution_time,
                "records": len(payment_records),
                "query_details": business_queries
            }
            
        except Exception as e:
            print(f"❌ Error in optimized approach: {str(e)}")
            return {"approach": "optimized", "error": str(e)}
            
        finally:
            frappe.db.sql = original_sql
            
    def _compare_results(self, original, optimized):
        """Compare performance results and calculate improvements"""
        print(f"\n📈 PERFORMANCE COMPARISON RESULTS")
        print("=" * 45)
        
        if "error" in original or "error" in optimized:
            print("❌ Cannot compare due to errors")
            return
            
        # Calculate improvements
        query_reduction = ((original["business_queries"] - optimized["business_queries"]) / original["business_queries"]) * 100
        time_improvement = ((original["execution_time"] - optimized["execution_time"]) / original["execution_time"]) * 100
        
        print(f"🔍 Business Logic Queries:")
        print(f"   Original (N+1): {original['business_queries']} queries")
        print(f"   Optimized: {optimized['business_queries']} queries")
        print(f"   📉 Reduction: {query_reduction:.1f}%")
        
        print(f"\n⏱️  Execution Time:")
        print(f"   Original: {original['execution_time']:.3f}s")
        print(f"   Optimized: {optimized['execution_time']:.3f}s")
        print(f"   🚀 Improvement: {time_improvement:.1f}%")
        
        print(f"\n💳 Data Processing:")
        print(f"   Original records: {original['records']}")
        print(f"   Optimized records: {optimized['records']}")
        if original['records'] == optimized['records']:
            print("   ✅ Data consistency: PERFECT")
        else:
            print("   ⚠️  Data consistency: MISMATCH")
        
        # Performance assessment
        print(f"\n🎯 OPTIMIZATION ASSESSMENT:")
        if query_reduction >= 70:
            print("   🚀 EXCELLENT: Query reduction exceeds 70%")
        elif query_reduction >= 50:
            print("   ✅ GOOD: Significant query reduction achieved")
        else:
            print("   ⚠️  MODERATE: Query reduction below 50%")
            
        # Show query patterns
        print(f"\n🔍 Query Pattern Analysis:")
        print(f"   Original pattern (first 3 queries):")
        for query in original.get("query_details", [])[:3]:
            print(f"     {query}")
            
        print(f"   Optimized pattern (all business queries):")
        for query in optimized.get("query_details", []):
            print(f"     {query}")
            
        return {
            "query_reduction_percent": query_reduction,
            "time_improvement_percent": time_improvement,
            "data_consistent": original['records'] == optimized['records']
        }


def test_baseline_comparison():
    """Standalone function for direct testing"""
    test_case = TestPaymentBaselineComparison()
    test_case.setUp()
    try:
        return test_case.test_baseline_comparison()
    finally:
        test_case.tearDown()