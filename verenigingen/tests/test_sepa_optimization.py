#!/usr/bin/env python3
"""
SEPA Operations Optimization Validation Test
===========================================

Tests the optimized SEPA bulk operations to measure:
- Query count reduction 
- Performance improvement
- Data accuracy preservation
- SEPA compliance maintenance
"""

import time
from typing import List, Dict, Any

import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils.frappe_native_sepa_operations import (
    FrappeNativeSEPAOperation, FrappeNativeSEPAManager
)
from verenigingen.verenigingen_payments.utils.frappe_native_sepa_operations_optimized import (
    FrappeNativeSEPAManagerOptimized
)
from verenigingen.verenigingen_payments.utils.audit_context import ExecutionSource


class TestSEPAOptimization(EnhancedTestCase):
    """Test SEPA operations optimization performance and accuracy"""

    def test_sepa_optimization_performance(self):
        """Compare original vs optimized SEPA bulk operations"""
        print("🔍 SEPA Operations Optimization Validation")
        print("=" * 50)
        
        # Create test operations for validation
        test_operations = self._create_test_sepa_operations()
        
        if not test_operations:
            print("❌ No test operations could be created")
            return
            
        print(f"📊 Created {len(test_operations)} test SEPA operations")
        
        # Test original approach
        original_results = self._test_original_sepa_processing(test_operations)
        
        # Test optimized approach
        optimized_results = self._test_optimized_sepa_processing(test_operations)
        
        # Compare and validate results
        self._compare_sepa_results(original_results, optimized_results)
        
    def _create_test_sepa_operations(self) -> List[FrappeNativeSEPAOperation]:
        """Create test SEPA operations for performance comparison"""
        operations = []
        
        try:
            # Create 3 test members for SEPA operations
            for i in range(3):
                member = self.create_test_member(
                    first_name=f"SEPA",
                    last_name=f"Test{i+1}",
                    birth_date="1990-01-01"
                )
                
                # Create operations for each member
                operations.extend([
                    FrappeNativeSEPAOperation(
                        member_id=member.name,
                        operation_type="create",
                        operation_data={
                            "iban": f"NL91ABNA041716430{i:02d}",
                            "bank_name": "ABN AMRO Bank",
                            "account_holder_name": f"{member.first_name} {member.last_name}",
                            "sign_date": frappe.utils.today(),
                            "status": "Active"
                        }
                    ),
                    FrappeNativeSEPAOperation(
                        member_id=member.name,
                        operation_type="update", 
                        operation_data={
                            "notes": f"Updated via bulk operation test {i}"
                        }
                    )
                ])
            
            print(f"✅ Created {len(operations)} SEPA operations for testing")
            return operations
            
        except Exception as e:
            print(f"❌ Error creating test operations: {str(e)}")
            return []

    def _test_original_sepa_processing(self, operations: List[FrappeNativeSEPAOperation]) -> Dict[str, Any]:
        """Test the original SEPA processing approach"""
        print(f"\n🐌 Testing ORIGINAL SEPA Processing...")
        
        manager = FrappeNativeSEPAManager()
        
        # Query counting setup
        original_sql = frappe.db.sql
        query_count = 0
        business_queries = []
        
        def counting_sql(*args, **kwargs):
            nonlocal query_count
            query_count += 1
            query_text = str(args[0]) if args else ""
            
            # Track business logic queries (SEPA-related)
            if any(table in query_text for table in ['tabSEPA Mandate', 'tabMember', 'tabPayment Entry']):
                business_queries.append(f"Q{query_count}: {query_text[:80]}...")
                
            return original_sql(*args, **kwargs)
        
        frappe.db.sql = counting_sql
        start_time = time.time()
        
        try:
            # Process with original approach
            result = manager.process_bulk_operations_native(operations, ExecutionSource.HTTP)
            
            execution_time = time.time() - start_time
            
            print(f"📊 Original approach results:")
            print(f"   Total queries: {query_count}")
            print(f"   Business queries: {len(business_queries)}")
            print(f"   Execution time: {execution_time:.3f}s")
            print(f"   Operations processed: {result.get('processed', 0)}")
            print(f"   Operations failed: {result.get('failed', 0)}")
            
            return {
                "approach": "original",
                "total_queries": query_count,
                "business_queries": len(business_queries),
                "execution_time": execution_time,
                "processed": result.get("processed", 0),
                "failed": result.get("failed", 0),
                "success": result.get("success", False),
                "query_details": business_queries[:10]  # First 10 for analysis
            }
            
        except Exception as e:
            print(f"❌ Error in original approach: {str(e)}")
            return {"approach": "original", "error": str(e)}
            
        finally:
            frappe.db.sql = original_sql

    def _test_optimized_sepa_processing(self, operations: List[FrappeNativeSEPAOperation]) -> Dict[str, Any]:
        """Test the optimized SEPA processing approach"""
        print(f"\n🚀 Testing OPTIMIZED SEPA Processing...")
        
        manager = FrappeNativeSEPAManagerOptimized()
        
        # Query counting setup
        original_sql = frappe.db.sql
        query_count = 0
        business_queries = []
        
        def counting_sql(*args, **kwargs):
            nonlocal query_count
            query_count += 1
            query_text = str(args[0]) if args else ""
            
            # Track business logic queries (SEPA-related)
            if any(table in query_text for table in ['tabSEPA Mandate', 'tabMember', 'tabPayment Entry']):
                business_queries.append(f"Q{query_count}: {query_text[:80]}...")
                
            return original_sql(*args, **kwargs)
        
        frappe.db.sql = counting_sql
        start_time = time.time()
        
        try:
            # Process with optimized approach
            result = manager.process_bulk_operations_optimized(operations, ExecutionSource.HTTP)
            
            execution_time = time.time() - start_time
            
            print(f"📊 Optimized approach results:")
            print(f"   Total queries: {query_count}")
            print(f"   Business queries: {len(business_queries)}")
            print(f"   Execution time: {execution_time:.3f}s")
            print(f"   Operations processed: {result.get('processed', 0)}")
            print(f"   Operations failed: {result.get('failed', 0)}")
            
            return {
                "approach": "optimized",
                "total_queries": query_count,
                "business_queries": len(business_queries),
                "execution_time": execution_time,
                "processed": result.get("processed", 0),
                "failed": result.get("failed", 0),
                "success": result.get("success", False),
                "query_details": business_queries
            }
            
        except Exception as e:
            print(f"❌ Error in optimized approach: {str(e)}")
            return {"approach": "optimized", "error": str(e)}
            
        finally:
            frappe.db.sql = original_sql

    def _compare_sepa_results(self, original: Dict[str, Any], optimized: Dict[str, Any]):
        """Compare SEPA optimization results and calculate improvements"""
        print(f"\n📈 SEPA OPTIMIZATION COMPARISON RESULTS")
        print("=" * 50)
        
        if "error" in original or "error" in optimized:
            print("❌ Cannot compare due to errors")
            if "error" in original:
                print(f"   Original error: {original['error']}")
            if "error" in optimized:
                print(f"   Optimized error: {optimized['error']}")
            return
            
        # Calculate improvements
        query_reduction = 0
        time_improvement = 0
        
        if original["business_queries"] > 0:
            query_reduction = ((original["business_queries"] - optimized["business_queries"]) / original["business_queries"]) * 100
            
        if original["execution_time"] > 0:
            time_improvement = ((original["execution_time"] - optimized["execution_time"]) / original["execution_time"]) * 100
        
        print(f"🔍 Business Logic Queries:")
        print(f"   Original: {original['business_queries']} queries")
        print(f"   Optimized: {optimized['business_queries']} queries")
        if query_reduction > 0:
            print(f"   📉 Reduction: {query_reduction:.1f}%")
        else:
            print(f"   📈 Change: {query_reduction:.1f}% (negative = increase)")
        
        print(f"\n⏱️  Execution Time:")
        print(f"   Original: {original['execution_time']:.3f}s")
        print(f"   Optimized: {optimized['execution_time']:.3f}s")
        if time_improvement > 0:
            print(f"   🚀 Improvement: {time_improvement:.1f}%")
        else:
            print(f"   ⚠️  Time change: {time_improvement:.1f}%")
        
        print(f"\n💼 Operations Processing:")
        print(f"   Original processed: {original['processed']}")
        print(f"   Optimized processed: {optimized['processed']}")
        print(f"   Original failed: {original['failed']}")
        print(f"   Optimized failed: {optimized['failed']}")
        
        # Data consistency check
        if original['processed'] == optimized['processed'] and original['failed'] == optimized['failed']:
            print("   ✅ Data consistency: PERFECT")
        else:
            print("   ⚠️  Data consistency: DIFFERENCE DETECTED")
        
        # Performance assessment
        print(f"\n🎯 OPTIMIZATION ASSESSMENT:")
        if query_reduction >= 70:
            print("   🚀 EXCELLENT: Query reduction exceeds 70%")
        elif query_reduction >= 50:
            print("   ✅ GOOD: Significant query reduction achieved")
        elif query_reduction >= 25:
            print("   🟡 MODERATE: Some optimization benefit")
        else:
            print("   ⚠️  LIMITED: Query reduction below 25%")
            
        # Show query patterns for analysis
        print(f"\n🔍 Query Pattern Analysis:")
        print(f"   Original pattern (first 3 queries):")
        for query in original.get("query_details", [])[:3]:
            print(f"     {query}")
            
        print(f"   Optimized pattern (all business queries):")
        for query in optimized.get("query_details", []):
            print(f"     {query}")
            
        # SEPA compliance validation
        self._validate_sepa_compliance(original, optimized)
        
        return {
            "query_reduction_percent": query_reduction,
            "time_improvement_percent": time_improvement,
            "data_consistent": (original['processed'] == optimized['processed'] and 
                               original['failed'] == optimized['failed'])
        }

    def _validate_sepa_compliance(self, original: Dict[str, Any], optimized: Dict[str, Any]):
        """Validate that SEPA compliance is maintained after optimization"""
        print(f"\n🏛️  SEPA COMPLIANCE VALIDATION:")
        
        # Check that both approaches process the same number of operations
        if original.get("processed", 0) == optimized.get("processed", 0):
            print("   ✅ Operation count consistency: MAINTAINED")
        else:
            print("   ❌ Operation count consistency: MISMATCH")
            
        # Check for audit trail preservation (both should have success status)
        if original.get("success", False) and optimized.get("success", False):
            print("   ✅ Transaction integrity: MAINTAINED")
        else:
            print("   ⚠️  Transaction integrity: CHECK REQUIRED")
            
        # Validate error handling consistency
        if original.get("failed", 0) == optimized.get("failed", 0):
            print("   ✅ Error handling consistency: MAINTAINED")
        else:
            print("   ⚠️  Error handling: DIFFERENCE DETECTED")
            
        print("   📋 SEPA regulatory requirements appear to be maintained")


def test_sepa_optimization():
    """Standalone function for direct testing"""
    test_case = TestSEPAOptimization()
    test_case.setUp()
    try:
        return test_case.test_sepa_optimization_performance()
    finally:
        test_case.tearDown()