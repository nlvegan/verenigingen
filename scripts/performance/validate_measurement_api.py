#!/usr/bin/env python3
"""
API Validation Script for Performance Measurement Tools
This script validates the measurement API endpoints using bench execute
"""

import frappe

def validate_measurement_infrastructure():
    """Validate the performance measurement infrastructure"""
    
    print("Validating Performance Measurement Infrastructure...")
    print("=" * 60)
    
    try:
        # Test 1: Import measurement modules
        print("\nTest 1: Testing module imports...")
        
        from verenigingen.utils.performance.query_measurement import (
            QueryProfiler, measure_member_payment_history
        )
        print("✓ Query measurement module imported")
        
        from verenigingen.utils.performance.bottleneck_analyzer import (
            PaymentOperationAnalyzer, N1QueryDetector
        )
        print("✓ Bottleneck analyzer module imported")
        
        from verenigingen.utils.performance.performance_reporter import (
            PerformanceReporter
        )
        print("✓ Performance reporter module imported")
        
        from verenigingen.api.performance_measurement_api import (
            measure_member_performance,
            get_performance_summary
        )
        print("✓ Performance API module imported")
        
        # Test 2: Get test member
        print("\nTest 2: Finding test member...")
        
        test_members = frappe.get_all(
            "Member",
            filters={"customer": ("!=", "")},
            fields=["name", "full_name"],
            limit=3
        )
        
        if not test_members:
            print("✗ No members with customers found for testing")
            return False
            
        test_member = test_members[0]
        print(f"✓ Using test member: {test_member.name} ({test_member.full_name})")
        
        # Test 3: Basic query profiling
        print("\nTest 3: Testing basic query profiling...")
        
        try:
            with QueryProfiler("Test_Query_Profile") as profiler:
                member = frappe.get_doc("Member", test_member.name)
                
            results = profiler.get_results()
            print(f"✓ Query profiling working - captured {results['query_count']} queries in {results['execution_time']:.3f}s")
            
        except Exception as e:
            print(f"✗ Query profiling failed: {e}")
            return False
            
        # Test 4: Payment history measurement
        print("\nTest 4: Testing payment history measurement...")
        
        try:
            payment_results = measure_member_payment_history(test_member.name)
            query_count = payment_results.get('query_count', 0)
            exec_time = payment_results.get('execution_time', 0)
            print(f"✓ Payment history measurement working - {query_count} queries in {exec_time:.3f}s")
            
        except Exception as e:
            print(f"✗ Payment history measurement failed: {e}")
            return False
            
        # Test 5: API endpoint
        print("\nTest 5: Testing API endpoint...")
        
        try:
            api_result = measure_member_performance(test_member.name)
            
            if api_result.get('success'):
                data = api_result.get('data', {})
                query_perf = data.get('query_performance', {})
                print(f"✓ API endpoint working - {query_perf.get('total_queries', 0)} queries, {query_perf.get('total_execution_time', 0):.3f}s")
            else:
                print(f"✗ API endpoint failed: {api_result.get('error', 'Unknown error')}")
                return False
                
        except Exception as e:
            print(f"✗ API endpoint failed: {e}")
            return False
            
        # Test 6: Performance summary
        print("\nTest 6: Testing performance summary...")
        
        try:
            summary_result = get_performance_summary()
            
            if summary_result.get('success'):
                print("✓ Performance summary working")
            else:
                print(f"✗ Performance summary failed: {summary_result.get('error', 'Unknown error')}")
                return False
                
        except Exception as e:
            print(f"✗ Performance summary failed: {e}")
            return False
            
        print("\n" + "=" * 60)
        print("ALL TESTS PASSED ✓")
        print("Performance measurement infrastructure is ready!")
        
        # Quick demo
        print("\nQUICK DEMONSTRATION:")
        print("-" * 30)
        
        demo_result = measure_member_performance(test_member.name)
        if demo_result.get('success'):
            data = demo_result['data']
            qp = data.get('query_performance', {})
            bottlenecks = data.get('bottlenecks', [])
            
            print(f"Member: {test_member.full_name}")
            print(f"Queries: {qp.get('total_queries', 0)}")
            print(f"Time: {qp.get('total_execution_time', 0):.3f}s")
            print(f"Bottlenecks: {len(bottlenecks)}")
            print(f"Priority: {data.get('optimization_priority', 'unknown').upper()}")
            
            if bottlenecks:
                print("Top issues:")
                for i, b in enumerate(bottlenecks[:2]):
                    print(f"  {i+1}. {b.get('type', 'unknown')} ({b.get('severity', 'unknown')})")
                    
        return True
        
    except Exception as e:
        print(f"\n✗ CRITICAL TEST FAILURE: {e}")
        import traceback
        print(traceback.format_exc())
        return False


if __name__ == "__main__":
    success = validate_measurement_infrastructure()
    if not success:
        frappe.throw("Measurement infrastructure validation failed")