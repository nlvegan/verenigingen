#!/usr/bin/env python3
"""
Test Runner for Membership Amendment Features

This script runs all tests related to the new membership amendment functionality:
- Self-service fee adjustments
- Membership type changes
- Amendment request workflows
"""

import sys
import os
import time
import argparse
from datetime import datetime

# Add app path to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

import frappe
from frappe.utils import cint


def run_test_suite(suite_name, test_module, verbose=False):
    """Run a specific test suite and return results"""
    print(f"\n{'='*60}")
    print(f"Running {suite_name}")
    print(f"{'='*60}")
    
    start_time = time.time()
    
    try:
        # Run the tests
        result = frappe.test_runner.run_tests(
            app="verenigingen",
            module=test_module,
            verbose=verbose,
            failfast=False
        )
        
        elapsed_time = time.time() - start_time
        
        # Determine success
        success = result is None or (hasattr(result, 'wasSuccessful') and result.wasSuccessful())
        
        print(f"\n{suite_name} {'PASSED' if success else 'FAILED'} in {elapsed_time:.2f} seconds")
        
        return {
            'suite': suite_name,
            'module': test_module,
            'success': success,
            'time': elapsed_time,
            'result': result
        }
        
    except Exception as e:
        print(f"\nERROR running {suite_name}: {str(e)}")
        return {
            'suite': suite_name,
            'module': test_module,
            'success': False,
            'time': time.time() - start_time,
            'error': str(e)
        }


def main():
    """Main test runner function"""
    parser = argparse.ArgumentParser(description='Run membership amendment tests')
    parser.add_argument('--site', required=True, help='Site name')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--suite', choices=['fee', 'type', 'workflow', 'integration', 'all'], 
                       default='all', help='Test suite to run')
    
    args = parser.parse_args()
    
    # Connect to site
    frappe.init(site=args.site)
    frappe.connect()
    
    print(f"\nRunning Membership Amendment Tests")
    print(f"Site: {args.site}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Suite: {args.suite}")
    
    # Define test suites
    test_suites = {
        'fee': [
            ('Self-Service Fee Adjustment Tests', 'verenigingen.tests.test_self_service_fee_adjustment'),
        ],
        'type': [
            ('Membership Type Change Tests', 'verenigingen.tests.test_membership_type_change'),
        ],
        'workflow': [
            ('Enhanced Membership Lifecycle Tests', 'verenigingen.tests.workflows.test_enhanced_membership_lifecycle'),
        ],
        'integration': [
            ('Member Portal Integration Tests', 'verenigingen.tests.integration.test_member_portal_features'),
        ]
    }
    
    # Determine which suites to run
    if args.suite == 'all':
        suites_to_run = []
        for suite_tests in test_suites.values():
            suites_to_run.extend(suite_tests)
    else:
        suites_to_run = test_suites.get(args.suite, [])
    
    # Run the tests
    results = []
    for suite_name, test_module in suites_to_run:
        result = run_test_suite(suite_name, test_module, args.verbose)
        results.append(result)
        
        # Add a small delay between suites
        time.sleep(1)
    
    # Print summary
    print(f"\n{'='*60}")
    print("TEST SUMMARY")
    print(f"{'='*60}")
    
    total_time = sum(r['time'] for r in results)
    passed = sum(1 for r in results if r['success'])
    failed = len(results) - passed
    
    print(f"\nTotal test suites: {len(results)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Total time: {total_time:.2f} seconds")
    
    # Detailed results
    if failed > 0:
        print("\nFailed suites:")
        for result in results:
            if not result['success']:
                print(f"  - {result['suite']}")
                if 'error' in result:
                    print(f"    Error: {result['error']}")
    
    # Test personas validation
    if args.suite in ['all', 'integration']:
        print(f"\n{'='*60}")
        print("VALIDATING TEST PERSONAS")
        print(f"{'='*60}")
        
        try:
            from vereinigingen.tests.fixtures.test_personas import TestPersonas
            
            personas = [
                ('Fee Adjuster Fiona', TestPersonas.create_fee_adjuster_fiona),
                ('Type Changer Thomas', TestPersonas.create_type_changer_thomas),
            ]
            
            for persona_name, creator_func in personas:
                try:
                    print(f"\nCreating {persona_name}...", end='')
                    test_data = creator_func()
                    print(" SUCCESS")
                    
                    # Validate key components
                    if 'member' in test_data:
                        print(f"  - Member: {test_data['member'].name}")
                    if 'membership' in test_data:
                        print(f"  - Membership: {test_data['membership'].name}")
                    if 'dues_schedule' in test_data:
                        print(f"  - Dues Schedule: {test_data['dues_schedule'].name}")
                        
                except Exception as e:
                    print(f" FAILED: {str(e)}")
                    
        except ImportError:
            print("Could not import test personas module")
    
    # Feature validation
    print(f"\n{'='*60}")
    print("FEATURE VALIDATION")
    print(f"{'='*60}")
    
    # Check if new fields exist in Contribution Amendment Request
    try:
        from frappe.model.meta import get_meta
        
        car_meta = get_meta("Contribution Amendment Request")
        required_fields = [
            "current_membership_type",
            "requested_membership_type",
            "dues_schedule"
        ]
        
        print("\nContribution Amendment Request fields:")
        for field in required_fields:
            exists = any(f.fieldname == field for f in car_meta.fields)
            print(f"  - {field}: {'✓' if exists else '✗'}")
            
    except Exception as e:
        print(f"Could not validate doctype fields: {str(e)}")
    
    # Check if Membership Dues Schedule doctype exists
    try:
        if frappe.db.exists("DocType", "Membership Dues Schedule"):
            print("\nMembership Dues Schedule doctype: ✓")
            
            # Check key fields
            mds_meta = get_meta("Membership Dues Schedule")
            key_fields = ["is_template", "schedule_name", "template_reference"]
            
            print("Key template fields:")
            for field in key_fields:
                exists = any(f.fieldname == field for f in mds_meta.fields)
                print(f"  - {field}: {'✓' if exists else '✗'}")
        else:
            print("\nMembership Dues Schedule doctype: ✗ (Not found)")
            
    except Exception as e:
        print(f"Could not validate Membership Dues Schedule: {str(e)}")
    
    # Exit with appropriate code
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()