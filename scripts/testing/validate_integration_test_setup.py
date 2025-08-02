#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E-Boekhouden Integration Test Setup Validator

This script validates that the integration test environment is properly set up
and can run the tests successfully. It performs comprehensive checks before
attempting to run the actual tests.

Usage:
    bench --site dev.veganisme.net execute scripts.testing.validate_integration_test_setup
"""

import os
import sys
import traceback
from datetime import datetime

try:
    import frappe
    from frappe.utils import now_datetime
except ImportError as e:
    print(f"❌ CRITICAL: Cannot import Frappe: {e}")
    print("Make sure you're running this in the Frappe environment")
    sys.exit(1)


def validate_frappe_environment():
    """Validate Frappe environment is working"""
    print("🔍 Validating Frappe environment...")
    
    try:
        # Test database connection
        result = frappe.db.sql("SELECT 1 as test")
        if not result or result[0][0] != 1:
            raise Exception("Database query failed")
            
        # Test basic Frappe operations
        current_time = now_datetime()
        if not current_time:
            raise Exception("Frappe utils not working")
            
        print("   ✅ Database connection: OK")
        print("   ✅ Frappe utils: OK")
        print(f"   ✅ Current time: {current_time}")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Frappe environment: {e}")
        return False


def validate_required_modules():
    """Validate required modules can be imported"""
    print("🔍 Validating required modules...")
    
    required_modules = [
        ("Security Helper", "verenigingen.e_boekhouden.utils.security_helper"),
        ("Payment Handler", "verenigingen.e_boekhouden.utils.payment_processing.payment_entry_handler"),
        ("Enhanced Test Factory", "verenigingen.tests.fixtures.enhanced_test_factory"),
        ("Integration Tests", "verenigingen.tests.test_e_boekhouden_migration_integration"),
    ]
    
    all_ok = True
    
    for name, module_path in required_modules:
        try:
            __import__(module_path)
            print(f"   ✅ {name}: OK")
        except ImportError as e:
            print(f"   ❌ {name}: {e}")
            all_ok = False
        except Exception as e:
            print(f"   ⚠️  {name}: Import OK but has issues: {e}")
            
    return all_ok


def validate_required_doctypes():
    """Validate required DocTypes exist"""
    print("🔍 Validating required DocTypes...")
    
    required_doctypes = [
        "E-Boekhouden Migration",
        "E-Boekhouden Ledger Mapping", 
        "Company",
        "Account",
        "Customer",
        "Supplier",
        "Payment Entry",
        "Sales Invoice",
        "Purchase Invoice"
    ]
    
    all_ok = True
    
    for doctype in required_doctypes:
        try:
            if frappe.db.exists("DocType", doctype):
                print(f"   ✅ {doctype}: EXISTS")
            else:
                print(f"   ❌ {doctype}: NOT FOUND")
                all_ok = False
        except Exception as e:
            print(f"   ❌ {doctype}: ERROR - {e}")
            all_ok = False
            
    return all_ok


def validate_test_infrastructure():
    """Validate test infrastructure components"""
    print("🔍 Validating test infrastructure...")
    
    try:
        # Test Enhanced Test Factory
        from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestDataFactory
        
        factory = EnhancedTestDataFactory(seed=12345, use_faker=True)
        test_email = factory.generate_test_email("validation")
        test_name = factory.generate_test_name("TestPerson")
        
        if not test_email or "@test.invalid" not in test_email:
            raise Exception("Test email generation failed")
            
        if not test_name or "TEST" not in test_name:
            raise Exception("Test name generation failed")
            
        print("   ✅ Enhanced Test Factory: OK")
        print(f"   ✅ Test email generation: {test_email}")
        print(f"   ✅ Test name generation: {test_name}")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Test infrastructure: {e}")
        return False


def validate_security_helper():
    """Validate security helper functions"""
    print("🔍 Validating security helper...")
    
    try:
        from verenigingen.e_boekhouden.utils.security_helper import (
            migration_context, validate_and_insert, has_migration_permission
        )
        
        # Test basic function availability
        if not callable(migration_context):
            raise Exception("migration_context not callable")
            
        if not callable(validate_and_insert):
            raise Exception("validate_and_insert not callable")
            
        if not callable(has_migration_permission):
            raise Exception("has_migration_permission not callable")
            
        # Test permission check (should not error)
        try:
            has_permission = has_migration_permission("general")
            print(f"   ✅ Permission check: {has_permission}")
        except Exception as e:
            print(f"   ⚠️  Permission check failed (expected): {e}")
            
        print("   ✅ Security helper functions: OK")
        return True
        
    except Exception as e:
        print(f"   ❌ Security helper: {e}")
        return False


def validate_payment_handler():
    """Validate payment entry handler"""
    print("🔍 Validating payment entry handler...")
    
    try:
        from verenigingen.e_boekhouden.utils.payment_processing.payment_entry_handler import PaymentEntryHandler
        
        # Test basic initialization
        handler = PaymentEntryHandler(company="Test Company")
        
        if not hasattr(handler, 'process_payment_mutation'):
            raise Exception("PaymentEntryHandler missing process_payment_mutation method")
            
        if not hasattr(handler, 'debug_log'):
            raise Exception("PaymentEntryHandler missing debug_log attribute")
            
        print("   ✅ PaymentEntryHandler initialization: OK")
        print("   ✅ Required methods: OK")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Payment handler: {e}")
        return False


def test_simple_document_creation():
    """Test simple document creation to validate permissions"""
    print("🔍 Testing simple document creation...")
    
    try:
        # Try to create a simple test document
        from verenigingen.e_boekhouden.utils.security_helper import validate_and_insert
        
        # Create a test company
        test_company_name = f"VALIDATION-TEST-{int(datetime.now().timestamp())}"
        
        if not frappe.db.exists("Company", test_company_name):
            company = frappe.new_doc("Company")
            company.company_name = test_company_name
            company.abbr = "VTEST"
            company.default_currency = "EUR"
            company.country = "Netherlands"
            
            # Use security helper
            validate_and_insert(company)
            
            print(f"   ✅ Test company created: {company.name}")
            
            # Clean up immediately
            frappe.delete_doc("Company", company.name, ignore_permissions=True, force=True)
            frappe.db.commit()
            
            print("   ✅ Test company cleaned up: OK")
        else:
            print("   ✅ Company creation test: SKIPPED (already exists)")
            
        return True
        
    except Exception as e:
        print(f"   ❌ Document creation test: {e}")
        return False


def run_basic_integration_test():
    """Run a very basic integration test"""
    print("🔍 Running basic integration test...")
    
    try:
        # Import test classes
        from verenigingen.tests.test_e_boekhouden_migration_integration import TestEBoekhoudenSecurityIntegration
        
        # Create test instance
        test_instance = TestEBoekhoudenSecurityIntegration()
        
        # Try to run setUp (this validates the test can initialize)
        test_instance.setUp()
        
        print("   ✅ Test class instantiation: OK")
        print("   ✅ Test setUp: OK")
        
        # Try to validate environment method
        if hasattr(test_instance, '_ensure_test_company'):
            company = test_instance._ensure_test_company()
            if company:
                print(f"   ✅ Test company setup: {company}")
                
                # Clean up
                if frappe.db.exists("Company", company):
                    frappe.delete_doc("Company", company, ignore_permissions=True, force=True)
                    frappe.db.commit()
            
        return True
        
    except Exception as e:
        print(f"   ❌ Basic integration test: {e}")
        traceback.print_exc()
        return False


def validate_test_runner():
    """Validate the test runner script"""
    print("🔍 Validating test runner...")
    
    try:
        # Check if test runner file exists
        runner_path = "/home/frappe/frappe-bench/apps/verenigingen/scripts/testing/run_e_boekhouden_integration_tests.py"
        
        if not os.path.exists(runner_path):
            print(f"   ❌ Test runner not found: {runner_path}")
            return False
            
        print(f"   ✅ Test runner file exists: {runner_path}")
        
        # Try to import the test runner module
        sys.path.insert(0, os.path.dirname(runner_path))
        
        try:
            import run_e_boekhouden_integration_tests
            
            if hasattr(run_e_boekhouden_integration_tests, 'EBoekhoudenIntegrationTestRunner'):
                print("   ✅ Test runner class: OK")
                
                # Try to instantiate
                runner = run_e_boekhouden_integration_tests.EBoekhoudenIntegrationTestRunner()
                if hasattr(runner, 'validate_environment'):
                    print("   ✅ Test runner instantiation: OK")
                    
        except ImportError as e:
            print(f"   ❌ Test runner import: {e}")
            return False
            
        return True
        
    except Exception as e:
        print(f"   ❌ Test runner validation: {e}")
        return False


def main():
    """Main validation function"""
    print("🚀 E-BOEKHOUDEN INTEGRATION TEST SETUP VALIDATOR")
    print("=" * 60)
    print(f"Validation started at: {now_datetime()}")
    print()
    
    # Run all validations
    validations = [
        ("Frappe Environment", validate_frappe_environment),
        ("Required Modules", validate_required_modules),
        ("Required DocTypes", validate_required_doctypes),
        ("Test Infrastructure", validate_test_infrastructure),
        ("Security Helper", validate_security_helper),
        ("Payment Handler", validate_payment_handler),
        ("Document Creation", test_simple_document_creation),
        ("Basic Integration Test", run_basic_integration_test),
        ("Test Runner", validate_test_runner),
    ]
    
    results = {}
    
    for name, validation_func in validations:
        print(f"📋 {name.upper()}")
        try:
            results[name] = validation_func()
        except Exception as e:
            print(f"   💥 CRASHED: {e}")
            results[name] = False
        print()
    
    # Summary
    print("=" * 60)
    print("📊 VALIDATION SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for result in results.values() if result)
    total = len(results)
    
    for name, result in results.items():
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{status} {name}")
        
    print()
    print(f"📈 OVERALL RESULT: {passed}/{total} validations passed")
    
    if passed == total:
        print("🎉 ALL VALIDATIONS PASSED!")
        print()
        print("✅ Your environment is ready for E-Boekhouden integration testing!")
        print()
        print("Next steps:")
        print("1. Run the full test suite:")
        print("   bench --site dev.veganisme.net execute scripts.testing.run_e_boekhouden_integration_tests")
        print()
        print("2. Or run individual suites:")
        print("   bench --site dev.veganisme.net execute scripts.testing.run_e_boekhouden_integration_tests --suite security")
        print("   bench --site dev.veganisme.net execute scripts.testing.run_e_boekhouden_integration_tests --suite payment")
        
        return True
    else:
        print("💥 SOME VALIDATIONS FAILED!")
        print()
        print("Please fix the failed validations before running the integration tests.")
        print("Common solutions:")
        print("1. Ensure all required modules are installed")
        print("2. Run migrations: bench --site dev.veganisme.net migrate")
        print("3. Install the app: bench --site dev.veganisme.net install-app verenigingen")
        print("4. Check for missing DocTypes or permissions")
        
        return False


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n⚠️  Validation interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n💥 Validation crashed: {e}")
        traceback.print_exc()
        sys.exit(1)