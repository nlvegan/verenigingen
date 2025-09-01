#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive Authentication Test Suite Runner

This master test runner executes the complete suite of authentication
integration tests for the Verenigingen (Dutch association management) system.

Test Suite Coverage:
==================

1. **Member Authentication Flow Tests** 
   - User login → Member lookup → Permissions verification
   - Session management and role-based access control
   - Fallback mechanisms and error handling
   - Concurrent authentication safety

2. **Portal Authentication Security Tests**
   - Bank details portal access controls
   - Payment dashboard authentication
   - Member portal session validation
   - CSRF protection and session security

3. **API Authentication with Security Decorators Tests**
   - Security decorator integration with member lookup
   - Role-based API access control enforcement
   - Member ownership validation in API endpoints
   - Multi-layer security validation

4. **SEPA Mandate Authentication Security Tests**
   - Financial data access controls
   - Banking regulation compliance (PCI DSS, PSD2)
   - Cross-member mandate access prevention
   - Administrative oversight authentication

Key Features:
=============
- Comprehensive end-to-end authentication testing
- Realistic data generation and scenarios
- Security boundary validation
- Performance impact assessment
- Concurrent access safety verification
- Error handling and audit trail validation

Usage:
======
python /path/to/run_authentication_test_suite.py

Or run individual test modules:
- test_authentication_flows_comprehensive.py
- test_portal_authentication_security.py  
- test_api_authentication_decorators_integration.py
- test_sepa_mandate_authentication_security.py
"""

import os
import sys
import time
import traceback
from typing import Dict, List, Tuple

import frappe

# Add the tests directory to Python path for imports
tests_dir = os.path.dirname(os.path.abspath(__file__))
if tests_dir not in sys.path:
    sys.path.insert(0, tests_dir)


class AuthenticationTestSuiteRunner:
    """Master test suite runner for authentication integration tests"""
    
    def __init__(self):
        """Initialize the test suite runner"""
        self.results = {}
        self.start_time = time.time()
        
    def run_comprehensive_authentication_tests(self):
        """Run the complete authentication test suite"""
        
        print("🔐 VERENIGINGEN AUTHENTICATION INTEGRATION TEST SUITE")
        print("=" * 60)
        print("Running comprehensive authentication flow testing...")
        print(f"Started at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)
        
        # Define test modules to run
        test_modules = [
            {
                "name": "Member Authentication Flow",
                "module": "test_authentication_flows_comprehensive",
                "function": "run_authentication_integration_tests",
                "description": "Core member authentication and session management"
            },
            {
                "name": "Portal Authentication Security", 
                "module": "test_portal_authentication_security",
                "function": "run_portal_authentication_tests",
                "description": "Web portal access controls and CSRF protection"
            },
            {
                "name": "API Authentication Decorators",
                "module": "test_api_authentication_decorators_integration", 
                "function": "run_api_authentication_decorator_tests",
                "description": "API security framework integration testing"
            },
            {
                "name": "SEPA Mandate Authentication",
                "module": "test_sepa_mandate_authentication_security",
                "function": "run_sepa_mandate_authentication_tests", 
                "description": "Financial data access controls and banking security"
            }
        ]
        
        # Run each test module
        for test_config in test_modules:
            self._run_test_module(test_config)
        
        # Generate final report
        self._generate_final_report()
        
        return self._get_overall_success()
    
    def _run_test_module(self, test_config: Dict[str, str]):
        """Run a single test module"""
        
        module_name = test_config["name"]
        print(f"\n📋 Running {module_name} Tests")
        print("-" * 50)
        print(f"Description: {test_config['description']}")
        
        module_start = time.time()
        
        try:
            # Import and run the test module
            module = __import__(test_config["module"])
            test_function = getattr(module, test_config["function"])
            
            success = test_function()
            duration = time.time() - module_start
            
            self.results[module_name] = {
                "success": success,
                "duration": duration,
                "error": None
            }
            
            if success:
                print(f"✅ {module_name} - PASSED ({duration:.2f}s)")
            else:
                print(f"❌ {module_name} - FAILED ({duration:.2f}s)")
                
        except Exception as e:
            duration = time.time() - module_start
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            
            self.results[module_name] = {
                "success": False,
                "duration": duration, 
                "error": error_msg
            }
            
            print(f"💥 {module_name} - ERROR ({duration:.2f}s)")
            print(f"Error: {str(e)}")
    
    def _generate_final_report(self):
        """Generate comprehensive final test report"""
        
        total_duration = time.time() - self.start_time
        passed_tests = sum(1 for r in self.results.values() if r["success"])
        total_tests = len(self.results)
        
        print("\n" + "=" * 60)
        print("🏁 AUTHENTICATION TEST SUITE FINAL REPORT")
        print("=" * 60)
        
        # Overall summary
        print(f"Total Test Modules: {total_tests}")
        print(f"Passed: {passed_tests}")
        print(f"Failed: {total_tests - passed_tests}")
        print(f"Total Duration: {total_duration:.2f} seconds")
        print(f"Success Rate: {(passed_tests/total_tests)*100:.1f}%")
        
        # Detailed results
        print("\n📊 Detailed Results:")
        print("-" * 40)
        
        for module_name, result in self.results.items():
            status = "✅ PASS" if result["success"] else "❌ FAIL"
            print(f"{status} {module_name} ({result['duration']:.2f}s)")
            
            if result["error"]:
                print(f"   Error: {result['error'].split('\\n')[0]}")
        
        # Security validation summary
        print("\n🔒 Security Validation Summary:")
        print("-" * 40)
        
        security_aspects = [
            "Member authentication and session management",
            "Portal access controls and CSRF protection", 
            "API security framework integration",
            "Financial data access controls (SEPA)"
        ]
        
        for i, aspect in enumerate(security_aspects):
            module_name = list(self.results.keys())[i]
            status = "✅" if self.results[module_name]["success"] else "❌"
            print(f"{status} {aspect}")
        
        # Performance summary
        print("\n⚡ Performance Summary:")
        print("-" * 40)
        
        fastest = min(self.results.values(), key=lambda x: x["duration"])
        slowest = max(self.results.values(), key=lambda x: x["duration"])
        avg_duration = sum(r["duration"] for r in self.results.values()) / len(self.results)
        
        print(f"Average test module duration: {avg_duration:.2f}s")
        print(f"Fastest module: {fastest['duration']:.2f}s")
        print(f"Slowest module: {slowest['duration']:.2f}s")
        
        # Recommendations
        print("\n💡 Security Testing Recommendations:")
        print("-" * 40)
        
        if passed_tests == total_tests:
            print("✅ All authentication flows validated successfully")
            print("✅ Security architecture is properly tested")
            print("✅ Ready for production deployment")
        else:
            print("⚠️  Some authentication tests failed")
            print("⚠️  Review failed tests before deployment")
            print("⚠️  Ensure security boundaries are properly validated")
        
        print("\n📚 Additional Testing Recommendations:")
        print("• Run tests regularly during development")
        print("• Extend tests for new authentication features")
        print("• Monitor authentication performance in production")
        print("• Review audit logs for security events")
    
    def _get_overall_success(self) -> bool:
        """Get overall test suite success status"""
        return all(result["success"] for result in self.results.values())


def run_authentication_test_suite() -> bool:
    """
    Main entry point for running the authentication test suite
    
    Returns:
        bool: True if all tests passed, False otherwise
    """
    
    runner = AuthenticationTestSuiteRunner()
    return runner.run_comprehensive_authentication_tests()


def run_specific_test_module(module_name: str) -> bool:
    """
    Run a specific authentication test module
    
    Args:
        module_name: Name of the module to run
        
    Returns:
        bool: True if test passed, False otherwise
    """
    
    test_modules = {
        "comprehensive": {
            "module": "test_authentication_flows_comprehensive",
            "function": "run_authentication_integration_tests"
        },
        "portal": {
            "module": "test_portal_authentication_security", 
            "function": "run_portal_authentication_tests"
        },
        "api": {
            "module": "test_api_authentication_decorators_integration",
            "function": "run_api_authentication_decorator_tests"
        },
        "sepa": {
            "module": "test_sepa_mandate_authentication_security",
            "function": "run_sepa_mandate_authentication_tests"
        }
    }
    
    if module_name not in test_modules:
        print(f"❌ Unknown test module: {module_name}")
        print(f"Available modules: {', '.join(test_modules.keys())}")
        return False
    
    config = test_modules[module_name]
    
    try:
        module = __import__(config["module"])
        test_function = getattr(module, config["function"])
        return test_function()
    except Exception as e:
        print(f"❌ Error running {module_name} tests: {e}")
        traceback.print_exc()
        return False


if __name__ == "__main__":
    """
    Command line interface for running authentication tests
    
    Usage:
        python run_authentication_test_suite.py              # Run all tests
        python run_authentication_test_suite.py comprehensive  # Run specific module
        python run_authentication_test_suite.py portal
        python run_authentication_test_suite.py api  
        python run_authentication_test_suite.py sepa
    """
    
    if len(sys.argv) > 1:
        # Run specific test module
        module_name = sys.argv[1]
        success = run_specific_test_module(module_name)
    else:
        # Run complete test suite
        success = run_authentication_test_suite()
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)