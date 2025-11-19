#!/usr/bin/env python3
"""
Test Script for Performance Measurement Tools
Phase 1 Implementation - Evidence-Based Performance Improvement Plan

This script validates that the measurement infrastructure is working correctly
before running the full baseline measurements.
"""

import sys
import os
import time

# Add the app directory to Python path
sys.path.insert(0, '/home/frappe/frappe-bench/apps/verenigingen')

# Import required modules after path setup
import frappe
from frappe.utils import now

def test_measurement_tools():
    """Test the performance measurement infrastructure"""
    
    print("Testing Performance Measurement Tools...")
    print("=" * 60)
    
    # Initialize Frappe
    try:
        frappe.init(site='dev.veganisme.net')
        frappe.connect()
        print("✓ Connected to Frappe site")
    except Exception as e:
        print(f"✗ Failed to connect to Frappe: {e}")
        return False
        
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
            measure_member_performance
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
            
        # Test 5: Bottleneck analysis
        print("\nTest 5: Testing bottleneck analysis...")
        
        try:
            analyzer = PaymentOperationAnalyzer()
            analysis = analyzer.analyze_member_payment_performance(test_member.name)
            
            bottleneck_count = len(analysis.get('bottlenecks', []))
            n1_patterns = len(analysis.get('n1_patterns', {}).get('patterns', []))
            print(f"✓ Bottleneck analysis working - found {bottleneck_count} bottlenecks, {n1_patterns} N+1 patterns")
            
        except Exception as e:
            print(f"✗ Bottleneck analysis failed: {e}")
            return False
            
        # Test 6: API endpoint
        print("\nTest 6: Testing API endpoint...")
        
        try:
            api_result = measure_member_performance(test_member.name)
            
            if api_result.get('success'):
                print("✓ API endpoint working")
            else:
                print(f"✗ API endpoint failed: {api_result.get('error', 'Unknown error')}")
                return False
                
        except Exception as e:
            print(f"✗ API endpoint failed: {e}")
            return False
            
        # Test 7: Performance reporter
        print("\nTest 7: Testing performance reporter...")
        
        try:
            reporter = PerformanceReporter()
            # Test with minimal sample size
            report = reporter.generate_comprehensive_report(include_baselines=False, sample_size=2)
            
            if 'report_metadata' in report:
                print("✓ Performance reporter working")
            else:
                print("✗ Performance reporter didn't generate expected report structure")
                return False
                
        except Exception as e:
            print(f"✗ Performance reporter failed: {e}")
            return False
            
        print("\n" + "=" * 60)
        print("ALL TESTS PASSED ✓")
        print("Performance measurement infrastructure is ready for baseline collection")
        
        return True
        
    except Exception as e:
        print(f"\n✗ CRITICAL TEST FAILURE: {e}")
        import traceback
        print(traceback.format_exc())
        return False
        
    finally:
        try:
            frappe.destroy()
        except:
            pass


def run_quick_measurement_demo():
    """Run a quick demonstration of the measurement capabilities"""
    
    print("\n" + "=" * 60)
    print("QUICK MEASUREMENT DEMONSTRATION")
    print("=" * 60)
    
    try:
        frappe.init(site='dev.veganisme.net')
        frappe.connect()
        
        # Get a member for demo
        demo_members = frappe.get_all(
            "Member",
            filters={"customer": ("!=", "")},
            fields=["name", "full_name"],
            limit=1
        )
        
        if not demo_members:
            print("No members available for demo")
            return
            
        demo_member = demo_members[0]
        print(f"Demo Member: {demo_member.name} ({demo_member.full_name})")
        
        # Import measurement tools
        from verenigingen.utils.performance.query_measurement import measure_member_payment_history
        from verenigingen.utils.performance.bottleneck_analyzer import PaymentOperationAnalyzer
        
        print("\n1. Measuring payment history performance...")
        start_time = time.time()
        payment_results = measure_member_payment_history(demo_member.name)
        measurement_time = time.time() - start_time
        
        print(f"   - Queries executed: {payment_results.get('query_count', 0)}")
        print(f"   - Execution time: {payment_results.get('execution_time', 0):.3f}s")
        print(f"   - Payment entries: {payment_results.get('payment_entries_loaded', 0)}")
        print(f"   - Queries per payment: {payment_results.get('queries_per_payment', 0):.1f}")
        print(f"   - Measurement overhead: {measurement_time:.3f}s")
        
        print("\n2. Analyzing performance bottlenecks...")
        analyzer = PaymentOperationAnalyzer()
        analysis = analyzer.analyze_member_payment_performance(demo_member.name)
        
        bottlenecks = analysis.get('bottlenecks', [])
        n1_patterns = analysis.get('n1_patterns', {}).get('patterns', [])
        priority = analysis.get('optimization_priority', 'unknown')
        
        print(f"   - Bottlenecks found: {len(bottlenecks)}")
        print(f"   - N+1 patterns: {len(n1_patterns)}")
        print(f"   - Optimization priority: {priority.upper()}")
        
        if bottlenecks:
            print("   - Top bottlenecks:")
            for i, bottleneck in enumerate(bottlenecks[:3]):
                print(f"     {i+1}. {bottleneck.get('type', 'unknown')} ({bottleneck.get('severity', 'unknown')})")
                
        print("\n3. Sample recommendations:")
        recommendations = analysis.get('recommendations', [])
        for i, rec in enumerate(recommendations[:3]):
            print(f"   {i+1}. {rec.get('title', 'Unknown recommendation')}")
            print(f"      Expected: {rec.get('expected_improvement', 'Unknown improvement')}")
            
        print(f"\nDemo completed successfully!")
        
    except Exception as e:
        print(f"Demo failed: {e}")
        import traceback
        print(traceback.format_exc())
        
    finally:
        try:
            frappe.destroy()
        except:
            pass


if __name__ == "__main__":
    # Run tests
    success = test_measurement_tools()
    
    if success:
        # Run demo if tests pass
        run_quick_measurement_demo()
        print("\n" + "=" * 60)
        print("READY TO RUN FULL PHASE 1 MEASUREMENTS")
        print("Execute: python scripts/performance/run_phase1_measurements.py")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("TESTS FAILED - FIX ISSUES BEFORE RUNNING MEASUREMENTS")
        print("=" * 60)
        sys.exit(1)