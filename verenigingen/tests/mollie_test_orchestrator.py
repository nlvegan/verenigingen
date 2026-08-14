#!/usr/bin/env python3
"""
Mollie Test Orchestrator
========================

Orchestrates execution of specialized Mollie test suites with categorized execution.
Complements the 3 consolidated test files by providing organized execution of
the remaining specialized test functionality.

Usage:
    # From within frappe-bench directory:
    python apps/verenigingen/verenigingen/tests/mollie_test_orchestrator.py --category core
    
    # Or using make commands:
    make test-mollie-core
    make test-mollie-performance  
    make test-mollie-security
    make test-mollie
"""

import os
import sys
import unittest
import argparse
from typing import Dict, List, Optional
import importlib.util
from pathlib import Path

# Ensure we're in the right context
if '/home/frappe/frappe-bench' not in sys.path:
    sys.path.insert(0, '/home/frappe/frappe-bench')

# Initialize Frappe context if not already initialized
try:
    import frappe
    if not frappe.db:
        # Try to initialize Frappe context
        try:
            frappe.init(site='dev.veganisme.net')
            frappe.connect()
        except Exception as e:
            print(f"⚠️  Warning: Could not initialize Frappe context: {e}")
            print("   Some tests may not work correctly outside bench environment")
except ImportError:
    print("⚠️  Warning: Frappe not available - running in standalone mode")


class MollieTestOrchestrator:
    """Orchestrates execution of categorized Mollie test suites"""
    
    def __init__(self, base_path: str = None):
        self.base_path = base_path or '/home/frappe/frappe-bench/apps/verenigingen/verenigingen/tests'
        self.test_categories = self._define_test_categories()
        
    def _define_test_categories(self) -> Dict[str, Dict[str, List[str]]]:
        """Define test categories with their associated test files"""
        return {
            'core': {
                'description': 'Core consolidated Mollie integration tests',
                'files': [
                    'test_mollie_core_integration.py',
                    'test_mollie_webhook_security.py', 
                    'test_mollie_refund_chargeback_integration.py'
                ]
            },
            'performance': {
                'description': 'Performance benchmarking and load testing',
                'files': [
                    'test_mollie_performance_benchmarks.py',
                    'performance/test_mollie_performance_benchmarks.py'
                ]
            },
            'security': {
                'description': 'Financial security and fraud protection',
                'files': [
                    'financial/test_mollie_financial_safeguards.py',
                    'unit/test_mollie_iban_validation_and_extraction.py'
                ]
            },
            'integration': {
                'description': 'Real API and bulk transaction integration',
                'files': [
                    'integration/test_mollie_subscription_real_api.py',
                    'integration/test_mollie_bulk_transaction_consumer_data_qa.py',
                    'integration/test_mollie_subscription_integration_phase4d.py'
                ]
            },
            'specialized': {
                'description': 'Edge cases and specialized business logic',
                'files': [
                    'test_mollie_edge_cases_integration.py',
                    'unit/test_mollie_bulk_transaction_core_functionality.py',
                    'mollie_api_data_factory.py'
                ]
            },
            'utilities': {
                'description': 'Test data factories and helper utilities',
                'files': [
                    'fixtures/mollie_test_factory.py',
                    '../utils/mollie_test_helpers.py',
                    '../api/test_mollie_integration.py'
                ]
            }
        }
    
    def list_categories(self) -> None:
        """List all available test categories"""
        print("📋 Available Mollie Test Categories:")
        print("=" * 50)
        
        for category, info in self.test_categories.items():
            print(f"\n🔹 {category.upper()}")
            print(f"   {info['description']}")
            print(f"   Files: {len(info['files'])}")
            
            # Show file availability
            available = 0
            for file_path in info['files']:
                full_path = os.path.join(self.base_path, file_path)
                if os.path.exists(full_path):
                    available += 1
            
            print(f"   Available: {available}/{len(info['files'])}")
            
        print(f"\n📊 Total: {sum(len(info['files']) for info in self.test_categories.values())} test files across {len(self.test_categories)} categories")
    
    def _load_test_module(self, file_path: str) -> Optional[unittest.TestSuite]:
        """Load a test module and return its test suite"""
        full_path = os.path.join(self.base_path, file_path)
        
        if not os.path.exists(full_path):
            print(f"⚠️  Test file not found: {file_path}")
            return None
            
        # Convert file path to module name for better error handling
        module_name = file_path.replace('/', '.').replace('.py', '')
        module_name = f"mollie_test_{abs(hash(file_path))}"
        
        try:
            # Load module dynamically with better error context
            spec = importlib.util.spec_from_file_location(module_name, full_path)
            if spec is None or spec.loader is None:
                print(f"❌ Could not load spec for: {file_path}")
                return None
                
            module = importlib.util.module_from_spec(spec)
            
            # Ensure Frappe context is available to the test module
            if 'frappe' in globals():
                module.frappe = frappe
            
            # Execute the module
            spec.loader.exec_module(module)
            
            # Discover tests in the module
            loader = unittest.TestLoader()
            suite = loader.loadTestsFromModule(module)
            
            if suite.countTestCases() > 0:
                return suite
            else:
                print(f"ℹ️  No test cases found in: {file_path}")
                return None
                
        except ImportError as e:
            print(f"⚠️  Import error for {file_path}: {e}")
            if "frappe" in str(e).lower():
                print("   💡 This test may require running from bench context")
            return None
        except Exception as e:
            print(f"❌ Error loading {file_path}: {e}")
            # Don't fail completely - some tests might work
            return None
    
    def run_category_tests(self, category: str, verbosity: int = 2) -> bool:
        """Run tests for a specific category"""
        if category not in self.test_categories:
            print(f"❌ Unknown category: {category}")
            print("Available categories:", list(self.test_categories.keys()))
            return False
        
        category_info = self.test_categories[category]
        print(f"🚀 Running {category.upper()} tests")
        print(f"📝 {category_info['description']}")
        print("=" * 60)
        
        # Create combined test suite for category
        combined_suite = unittest.TestSuite()
        loaded_files = []
        failed_files = []
        
        for file_path in category_info['files']:
            print(f"\n🔍 Loading: {file_path}")
            suite = self._load_test_module(file_path)
            
            if suite:
                combined_suite.addTest(suite)
                loaded_files.append(file_path)
                print(f"✅ Loaded: {suite.countTestCases()} test cases")
            else:
                failed_files.append(file_path)
        
        # Summary before execution
        total_tests = combined_suite.countTestCases()
        print(f"\n📊 Category Summary:")
        print(f"   • Files loaded: {len(loaded_files)}/{len(category_info['files'])}")
        print(f"   • Total test cases: {total_tests}")
        
        if failed_files:
            print(f"   • Failed to load: {failed_files}")
        
        if total_tests == 0:
            print("❌ No tests to run")
            return False
        
        # Run the tests
        print(f"\n🧪 Executing {total_tests} test cases...")
        print("=" * 60)
        
        runner = unittest.TextTestRunner(verbosity=verbosity, stream=sys.stdout)
        result = runner.run(combined_suite)
        
        # Final summary
        print("=" * 60)
        print(f"📈 {category.upper()} Results:")
        print(f"   • Tests run: {result.testsRun}")
        print(f"   • Failures: {len(result.failures)}")
        print(f"   • Errors: {len(result.errors)}")
        print(f"   • Skipped: {len(result.skipped)}")
        
        success = len(result.failures) == 0 and len(result.errors) == 0
        status = "✅ SUCCESS" if success else "❌ FAILED"
        print(f"   • Status: {status}")
        
        return success
    
    def run_all_tests(self, verbosity: int = 1) -> Dict[str, bool]:
        """Run all test categories"""
        print("🚀 Running All Mollie Test Categories")
        print("=" * 60)
        
        results = {}
        
        for category in self.test_categories.keys():
            print(f"\n{'='*20} {category.upper()} {'='*20}")
            results[category] = self.run_category_tests(category, verbosity=verbosity)
        
        # Final summary
        print("\n" + "=" * 60)
        print("📊 FINAL RESULTS SUMMARY")
        print("=" * 60)
        
        total_categories = len(results)
        passed_categories = sum(1 for success in results.values() if success)
        
        for category, success in results.items():
            status = "✅ PASS" if success else "❌ FAIL"
            print(f"   {category.ljust(15)}: {status}")
        
        print(f"\n📈 Overall: {passed_categories}/{total_categories} categories passed")
        
        overall_success = all(results.values())
        final_status = "✅ ALL TESTS PASSED" if overall_success else "❌ SOME TESTS FAILED"
        print(f"🏆 {final_status}")
        
        return results
    
    def validate_test_files(self) -> None:
        """Validate that all configured test files exist"""
        print("🔍 Validating Test File Configuration")
        print("=" * 50)
        
        all_files = []
        missing_files = []
        
        for category, info in self.test_categories.items():
            print(f"\n📁 {category.upper()}:")
            
            for file_path in info['files']:
                full_path = os.path.join(self.base_path, file_path)
                all_files.append(file_path)
                
                if os.path.exists(full_path):
                    print(f"   ✅ {file_path}")
                else:
                    print(f"   ❌ {file_path} (MISSING)")
                    missing_files.append(file_path)
        
        print(f"\n📊 Validation Summary:")
        print(f"   • Total configured files: {len(all_files)}")
        print(f"   • Available files: {len(all_files) - len(missing_files)}")
        print(f"   • Missing files: {len(missing_files)}")
        
        if missing_files:
            print(f"\n❌ Missing Files:")
            for file_path in missing_files:
                print(f"   • {file_path}")
        else:
            print(f"\n✅ All test files are available")


def main():
    """Main CLI interface"""
    parser = argparse.ArgumentParser(
        description="Mollie Test Orchestrator - Execute categorized Mollie test suites",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python mollie_test_orchestrator.py --list-categories
  python mollie_test_orchestrator.py --category core
  python mollie_test_orchestrator.py --category performance --verbose
  python mollie_test_orchestrator.py --validate
  python mollie_test_orchestrator.py --all
        """
    )
    
    parser.add_argument('--category', '-c', 
                       help='Run tests for specific category')
    parser.add_argument('--all', '-a', action='store_true',
                       help='Run all test categories')
    parser.add_argument('--list-categories', '-l', action='store_true',
                       help='List available test categories')
    parser.add_argument('--validate', '-v', action='store_true',
                       help='Validate test file configuration')
    parser.add_argument('--verbose', action='store_true',
                       help='Verbose test output')
    
    args = parser.parse_args()
    
    orchestrator = MollieTestOrchestrator()
    
    # Handle different command modes
    if args.list_categories:
        orchestrator.list_categories()
        
    elif args.validate:
        orchestrator.validate_test_files()
        
    elif args.all:
        verbosity = 2 if args.verbose else 1
        results = orchestrator.run_all_tests(verbosity=verbosity)
        sys.exit(0 if all(results.values()) else 1)
        
    elif args.category:
        verbosity = 2 if args.verbose else 1
        success = orchestrator.run_category_tests(args.category, verbosity=verbosity)
        sys.exit(0 if success else 1)
        
    else:
        parser.print_help()
        print("\n💡 Tip: Start with --list-categories to see available options")


if __name__ == "__main__":
    main()