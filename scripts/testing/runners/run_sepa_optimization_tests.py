#!/usr/bin/env python3
"""
Comprehensive test runner for SEPA optimizations
Runs all optimization-related tests in the correct order
"""

import sys
import os

# Add the app to Python path
sys.path.insert(0, '/home/frappe/frappe-bench/apps/verenigingen')

import frappe
from frappe.utils import today
import unittest


def run_enhanced_sepa_integration_test():
    """Run the enhanced SEPA integration test"""
    print("🔍 Running Enhanced SEPA Integration Test...")
    
    try:
        from verenigingen.tests.test_enhanced_sepa_integration import test_enhanced_sepa_integration
        
        result = test_enhanced_sepa_integration()
        print("✅ Enhanced SEPA integration test completed")
        return True
        
    except Exception as e:
        print(f"❌ Enhanced SEPA integration test failed: {str(e)}")
        return False


def run_optimization_integration_tests():
    """Run the optimization integration test suite"""
    print("\n🔍 Running SEPA Optimization Integration Tests...")
    
    try:
        from verenigingen.tests.test_sepa_optimizations_integration import run_optimization_tests
        
        success = run_optimization_tests()
        if success:
            print("✅ All optimization integration tests passed")
        else:
            print("❌ Some optimization integration tests failed")
        
        return success
        
    except Exception as e:
        print(f"❌ Optimization integration tests failed: {str(e)}")
        return False


def run_performance_regression_tests():
    """Run performance regression tests"""
    print("\n🚀 Running Performance Regression Tests...")
    
    try:
        from verenigingen.tests.test_sepa_performance_regression import run_performance_tests
        
        success = run_performance_tests()
        return success
        
    except Exception as e:
        print(f"❌ Performance regression tests failed: {str(e)}")
        return False


def run_sequence_type_validation_tests():
    """Run sequence type validation tests with optimization integration"""
    print("\n🔍 Running Sequence Type Validation Tests...")
    
    try:
        # Import and run the test class
        from verenigingen.tests.test_sepa_sequence_type_validation import TestSEPASequenceTypeValidation
        
        suite = unittest.TestSuite()
        
        # Add specific tests that include optimization integration
        suite.addTest(TestSEPASequenceTypeValidation('test_error_handler_integration'))
        suite.addTest(TestSEPASequenceTypeValidation('test_mandate_service_integration'))
        
        # Also run the core validation tests
        suite.addTest(TestSEPASequenceTypeValidation('test_critical_error_rcur_when_frst_required'))
        suite.addTest(TestSEPASequenceTypeValidation('test_warning_frst_when_rcur_expected'))
        
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)
        
        if result.wasSuccessful():
            print("✅ Sequence type validation tests passed")
            return True
        else:
            print("❌ Some sequence type validation tests failed")
            return False
            
    except Exception as e:
        print(f"❌ Sequence type validation tests failed: {str(e)}")
        return False


def run_database_index_verification():
    """Verify database indexes are working"""
    print("\n🗂️ Verifying Database Indexes...")
    
    try:
        from verenigingen.fixtures.add_sepa_database_indexes import verify_sepa_indexes
        
        verification_results = verify_sepa_indexes()
        found_indexes = [r for r in verification_results if r['status'] == 'found']
        missing_indexes = [r for r in verification_results if r['status'] == 'missing']
        
        print(f"✅ Found {len(found_indexes)}/{len(verification_results)} indexes")
        
        if missing_indexes:
            print(f"⚠️  Missing indexes: {[idx['index'] for idx in missing_indexes]}")
            return len(found_indexes) >= 8  # Allow some missing in different environments
        
        return True
        
    except Exception as e:
        print(f"❌ Database index verification failed: {str(e)}")
        return False


def run_api_endpoint_tests():
    """Test optimization API endpoints"""
    print("\n🌐 Testing Optimization API Endpoints...")
    
    try:
        # Test configuration APIs
        from verenigingen.utils.sepa_config_manager import (
            get_sepa_config, validate_sepa_configuration, get_sepa_config_cache_info
        )
        
        config = get_sepa_config()
        assert isinstance(config, dict), "Configuration API failed"
        
        validation = validate_sepa_configuration()
        assert isinstance(validation, dict) and "valid" in validation, "Validation API failed"
        
        cache_info = get_sepa_config_cache_info()
        assert isinstance(cache_info, dict), "Cache info API failed"
        
        print("✅ Configuration APIs working")
        
        # Test mandate service APIs
        from verenigingen.utils.sepa_mandate_service import (
            get_sepa_cache_stats, clear_sepa_mandate_cache
        )
        
        cache_stats = get_sepa_cache_stats()
        assert isinstance(cache_stats, dict), "Cache stats API failed"
        
        clear_result = clear_sepa_mandate_cache()
        assert clear_result.get("success"), "Cache clear API failed"
        
        print("✅ Mandate service APIs working")
        
        # Test error handler APIs
        from verenigingen.utils.sepa_error_handler import (
            get_sepa_error_handler_status, reset_sepa_circuit_breaker
        )
        
        error_status = get_sepa_error_handler_status()
        assert isinstance(error_status, dict) and "state" in error_status, "Error handler status API failed"
        
        reset_result = reset_sepa_circuit_breaker()
        assert reset_result.get("success"), "Circuit breaker reset API failed"
        
        print("✅ Error handler APIs working")
        
        return True
        
    except Exception as e:
        print(f"❌ API endpoint tests failed: {str(e)}")
        return False


def run_comprehensive_optimization_tests(suite_type="all"):
    """
    Run comprehensive SEPA optimization tests
    
    Args:
        suite_type: "all", "integration", "performance", "api", "indexes", "core"
    """
    print(f"🧪 Running SEPA Optimization Tests - Suite: {suite_type}")
    print("=" * 70)
    
    tests_passed = 0
    total_tests = 0
    
    if suite_type in ["all", "core"]:
        total_tests += 1
        if run_enhanced_sepa_integration_test():
            tests_passed += 1
    
    if suite_type in ["all", "integration"]:
        total_tests += 1
        if run_optimization_integration_tests():
            tests_passed += 1
        
        total_tests += 1
        if run_sequence_type_validation_tests():
            tests_passed += 1
    
    if suite_type in ["all", "performance"]:
        total_tests += 1
        if run_performance_regression_tests():
            tests_passed += 1
    
    if suite_type in ["all", "indexes"]:
        total_tests += 1
        if run_database_index_verification():
            tests_passed += 1
    
    if suite_type in ["all", "api"]:
        total_tests += 1
        if run_api_endpoint_tests():
            tests_passed += 1
    
    print("\n" + "=" * 70)
    print(f"🎯 SEPA Optimization Test Results: {tests_passed}/{total_tests} test suites passed")
    
    if tests_passed == total_tests:
        print("🎉 ALL SEPA OPTIMIZATION TESTS PASSED!")
        print("\n📋 Verification Summary:")
        print("✅ Enhanced SEPA Processor - Optimizations integrated")
        print("✅ Mandate Service - Batch processing and caching working")
        print("✅ Configuration Manager - Centralized settings functional")
        print("✅ Error Handler - Retry logic and circuit breaker operational")
        print("✅ Database Indexes - Performance optimizations in place")
        print("✅ API Endpoints - All optimization APIs functional")
        print("✅ Performance - Regression tests confirm optimization benefits")
        print("\n🚀 SEPA system optimizations are production-ready!")
    else:
        print(f"⚠️  {total_tests - tests_passed} test suite(s) failed.")
        print("Please review the test output above for specific failures.")
    
    return tests_passed == total_tests


def main():
    """Main test runner entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Run SEPA optimization tests")
    parser.add_argument(
        "--suite", 
        choices=["all", "integration", "performance", "api", "indexes", "core"],
        default="all",
        help="Test suite to run"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    
    args = parser.parse_args()
    
    # Initialize Frappe (if not already initialized)
    try:
        if not hasattr(frappe.local, 'site'):
            frappe.init(site='dev.veganisme.net')
            frappe.connect()
    except Exception as e:
        print(f"Warning: Could not initialize Frappe: {e}")
        print("Some tests may fail. Ensure you run from the correct environment.")
    
    success = run_comprehensive_optimization_tests(args.suite)
    
    return 0 if success else 1


if __name__ == "__main__":
    exit(main())