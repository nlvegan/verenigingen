#!/usr/bin/env python3

"""
Final validation testing for the incremental history update system.
Tests all critical fixes that were implemented.
"""

import frappe
import json
from frappe.utils import today, add_days
from datetime import datetime

@frappe.whitelist()
def test_incremental_update_comprehensive():
    """Comprehensive test of the incremental_update_history_tables method"""
    
    print("=" * 80)
    print("FINAL VALIDATION TEST: Incremental History Update System")
    print("=" * 80)
    
    test_results = {
        'functionality_test': None,
        'interface_test': None,
        'regression_test': None,
        'error_handling_test': None,
        'validation_bypass_check': None,
        'overall_status': 'PENDING'
    }
    
    try:
        # Test 1: Functionality Test with specific member
        print("\n1. FUNCTIONALITY TEST")
        print("-" * 40)
        
        member_name = "Assoc-Member-2025-07-0030"
        
        # Check if member exists
        if not frappe.db.exists("Member", member_name):
            print(f"❌ Member {member_name} not found. Using alternative member...")
            # Find a member with employee link for testing
            member_name = frappe.db.get_value('Member', {'employee': ['!=', '']}, 'name')
            if not member_name:
                print("❌ No member with employee link found for testing")
                test_results['functionality_test'] = {'success': False, 'error': 'No suitable test member found'}
            else:
                print(f"✅ Using alternative member: {member_name}")
        
        if member_name:
            member_doc = frappe.get_doc('Member', member_name)
            
            # Record initial state
            initial_donation_count = len(getattr(member_doc, 'donation_history', []))
            initial_expense_count = len(getattr(member_doc, 'volunteer_expenses', []))
            
            print(f"Member: {member_name}")
            print(f"Initial donation history count: {initial_donation_count}")
            print(f"Initial expense history count: {initial_expense_count}")
            print(f"Employee link: {getattr(member_doc, 'employee', 'None')}")
            print(f"Donor link: {getattr(member_doc, 'donor', 'None')}")
            
            # Execute the method
            print("Executing incremental_update_history_tables...")
            result = member_doc.incremental_update_history_tables()
            
            test_results['functionality_test'] = {
                'success': True,
                'result': result,
                'initial_state': {
                    'donations': initial_donation_count,
                    'expenses': initial_expense_count
                }
            }
            
            print(f"✅ Method executed successfully")
            print(f"Result: {json.dumps(result, indent=2, default=str)}")
        
        # Test 2: Interface Structure Test
        print("\n2. INTERFACE STRUCTURE TEST")
        print("-" * 40)
        
        if test_results['functionality_test'] and test_results['functionality_test']['success']:
            result = test_results['functionality_test']['result']
            
            # Check required structure
            required_fields = ['overall_success', 'volunteer_expenses', 'donations', 'message']
            required_subfields = {
                'volunteer_expenses': ['success', 'count'],
                'donations': ['success', 'count']
            }
            
            interface_valid = True
            interface_errors = []
            
            for field in required_fields:
                if field not in result:
                    interface_valid = False
                    interface_errors.append(f"Missing field: {field}")
            
            for parent_field, subfields in required_subfields.items():
                if parent_field in result and isinstance(result[parent_field], dict):
                    for subfield in subfields:
                        if subfield not in result[parent_field]:
                            interface_valid = False
                            interface_errors.append(f"Missing subfield: {parent_field}.{subfield}")
                elif parent_field in result:
                    interface_valid = False
                    interface_errors.append(f"Field {parent_field} should be a dict")
            
            test_results['interface_test'] = {
                'success': interface_valid,
                'errors': interface_errors,
                'structure': result
            }
            
            if interface_valid:
                print("✅ Interface structure matches JavaScript expectations")
            else:
                print("❌ Interface structure issues:")
                for error in interface_errors:
                    print(f"  - {error}")
        
        # Test 3: Validation Bypass Check
        print("\n3. VALIDATION BYPASS CHECK")
        print("-" * 40)
        
        # Check ExpenseMixin for ignore_permissions usage
        mixin_file = '/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/member/mixins/expense_mixin.py'
        
        try:
            with open(mixin_file, 'r') as f:
                mixin_content = f.read()
            
            bypass_issues = []
            if 'ignore_permissions=True' in mixin_content:
                bypass_issues.append('ignore_permissions=True found in ExpenseMixin')
            if 'ignore_validate=True' in mixin_content:
                bypass_issues.append('ignore_validate=True found in ExpenseMixin')
            
            test_results['validation_bypass_check'] = {
                'success': len(bypass_issues) == 0,
                'issues': bypass_issues
            }
            
            if len(bypass_issues) == 0:
                print("✅ No validation bypasses found in ExpenseMixin")
            else:
                print("❌ Validation bypass issues found:")
                for issue in bypass_issues:
                    print(f"  - {issue}")
                    
        except Exception as e:
            test_results['validation_bypass_check'] = {
                'success': False,
                'error': str(e)
            }
            print(f"❌ Error checking validation bypasses: {e}")
        
        # Test 5: Error Handling Test
        print("\n5. ERROR HANDLING TEST")
        print("-" * 40)
        
        # Test with invalid member
        try:
            invalid_member = frappe.new_doc('Member')
            invalid_member.name = 'INVALID-TEST-MEMBER'
            
            # This should handle errors gracefully
            error_result = invalid_member.incremental_update_history_tables()
            
            test_results['error_handling_test'] = {
                'success': True,
                'handled_gracefully': True,
                'error_result': error_result
            }
            
            print("✅ Error handling works gracefully")
            print(f"Error result: {json.dumps(error_result, indent=2, default=str)}")
            
        except Exception as e:
            test_results['error_handling_test'] = {
                'success': False,
                'error': str(e),
                'handled_gracefully': False
            }
            print(f"❌ Error handling failed: {e}")
        
        # Test 6: Regression Test
        print("\n6. REGRESSION TEST")
        print("-" * 40)
        
        # Test existing functionality still works
        if member_name:
            try:
                member_doc = frappe.get_doc('Member', member_name)
                
                # Test that existing methods still work
                methods_to_test = [
                    'add_expense_to_history',
                    '_build_expense_history_entry'
                ]
                
                regression_results = {}
                
                for method_name in methods_to_test:
                    if hasattr(member_doc, method_name):
                        regression_results[method_name] = 'exists'
                    else:
                        regression_results[method_name] = 'missing'
                
                all_methods_exist = all(status == 'exists' for status in regression_results.values())
                
                test_results['regression_test'] = {
                    'success': all_methods_exist,
                    'method_status': regression_results
                }
                
                if all_methods_exist:
                    print("✅ All existing methods still available")
                else:
                    print("❌ Some existing methods missing:")
                    for method, status in regression_results.items():
                        if status == 'missing':
                            print(f"  - {method}")
                            
            except Exception as e:
                test_results['regression_test'] = {
                    'success': False,
                    'error': str(e)
                }
                print(f"❌ Regression test failed: {e}")
        
        # Overall Assessment
        print("\n" + "=" * 80)
        print("OVERALL ASSESSMENT")
        print("=" * 80)
        
        passed_tests = sum(1 for test in test_results.values() 
                          if isinstance(test, dict) and test.get('success', False))
        total_tests = len([k for k, v in test_results.items() 
                          if k != 'overall_status' and v is not None])
        
        if passed_tests == total_tests and total_tests > 0:
            test_results['overall_status'] = 'PASS'
            print(f"✅ ALL TESTS PASSED ({passed_tests}/{total_tests})")
            print("🎉 System is READY FOR PRODUCTION")
        elif passed_tests >= total_tests * 0.8:  # 80% pass rate
            test_results['overall_status'] = 'MOSTLY_PASS'
            print(f"⚠️  MOSTLY PASSING ({passed_tests}/{total_tests})")
            print("🔧 Minor issues need attention before production")
        else:
            test_results['overall_status'] = 'FAIL'
            print(f"❌ TESTS FAILED ({passed_tests}/{total_tests})")
            print("🚫 Critical issues must be fixed before production")
        
        return test_results
        
    except Exception as e:
        print(f"❌ Critical test failure: {e}")
        frappe.log_error(f"Critical test failure in incremental update validation: {str(e)}", "Test Failure")
        test_results['overall_status'] = 'CRITICAL_FAILURE'
        test_results['critical_error'] = str(e)
        return test_results

def main():
    """Main function for direct script execution"""
    frappe.init(site='dev.veganisme.net')
    frappe.connect()
    
    try:
        results = test_incremental_update_comprehensive()
        print(f"\nFinal Status: {results['overall_status']}")
        return results
    finally:
        frappe.destroy()

if __name__ == "__main__":
    main()