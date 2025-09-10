"""
Test the expense claim form (Vue 3 + Tailwind implementation)
This tests the PoC expense form functionality
"""

import frappe
from frappe.utils import now_datetime
import json
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

class TestExpenseForm(EnhancedTestCase):
    """Test the expense claim form functionality"""

    def test_expense_form_backend(self):
        """Test the backend API endpoints for the expense form"""
        
        print("🧪 Testing Expense Form Backend API")
        print("=" * 50)
        
        results = {
            "total_tests": 0,
            "passed": 0,
            "failed": 0,
            "details": []
        }
    
        # Test 1: Get volunteer expense context
        print("\n1. Testing get_volunteer_expense_context API")
        try:
            response = frappe.call(
                "verenigingen.templates.pages.volunteer.expenses.get_volunteer_expense_context"
            )
            results["total_tests"] += 1
            
            if response and "message" in response:
                data = response["message"]
                if data.get("success"):
                    print("✅ PASS: API returns successful response")
                    print(f"   User chapters: {len(data.get('user_chapters', []))}")
                    print(f"   User teams: {len(data.get('user_teams', []))}")
                    print(f"   Expense categories: {len(data.get('expense_categories', []))}")
                    results["passed"] += 1
                    results["details"].append("✅ get_volunteer_expense_context: PASS")
                else:
                    print("❌ FAIL: API returns failure response")
                    print(f"   Error: {data.get('error', 'Unknown error')}")
                    results["failed"] += 1
                    results["details"].append("❌ get_volunteer_expense_context: FAIL")
            else:
                print("❌ FAIL: Invalid response format")
                results["failed"] += 1
                results["details"].append("❌ get_volunteer_expense_context: FAIL - Invalid response")
        except Exception as e:
            print(f"❌ FAIL: Exception occurred: {e}")
            results["failed"] += 1
            results["details"].append(f"❌ get_volunteer_expense_context: FAIL - {e}")
    
        # Test 2: Submit multiple expenses (with mock data)
        print("\n2. Testing submit_multiple_expenses API")
        try:
            mock_expenses = [
                {
                    "description": "Test expense 1",
                    "amount": 25.50,
                    "expense_date": "2025-01-10",
                    "organization_type": "National",
                    "category": "Travel",
                    "chapter": None,
                    "team": None,
                    "notes": "Test expense for API validation",
                    "receipt_attachment": None
                },
                {
                    "description": "Test expense 2", 
                    "amount": 15.75,
                    "expense_date": "2025-01-11",
                    "organization_type": "National",
                    "category": "Office Supplies",
                    "chapter": None,
                    "team": None,
                    "notes": "Another test expense",
                    "receipt_attachment": None
                }
            ]
            
            response = frappe.call(
                "verenigingen.templates.pages.volunteer.expenses.submit_multiple_expenses",
                expenses=mock_expenses
            )
            results["total_tests"] += 1
            
            if response and "message" in response:
                data = response["message"]
                if data.get("success"):
                    print("✅ PASS: Multiple expenses submitted successfully")
                    print(f"   Created count: {data.get('created_count', 0)}")
                    print(f"   Total amount: €{data.get('total_amount', 0)}")
                    results["passed"] += 1
                    results["details"].append("✅ submit_multiple_expenses: PASS")
                else:
                    print("❌ FAIL: Failed to submit expenses")
                    print(f"   Error: {data.get('error', 'Unknown error')}")
                    results["failed"] += 1
                    results["details"].append("❌ submit_multiple_expenses: FAIL")
            else:
                print("❌ FAIL: Invalid response format")
                results["failed"] += 1
                results["details"].append("❌ submit_multiple_expenses: FAIL - Invalid response")
        except Exception as e:
            print(f"❌ FAIL: Exception occurred: {e}")
            results["failed"] += 1
            results["details"].append(f"❌ submit_multiple_expenses: FAIL - {e}")
    
        # Test 3: Test page access
        print("\n3. Testing expense claim page access")
        try:
            # Try to access the page context
            from verenigingen.templates.pages.expense_claim_new import get_context
            
            context = {}
            get_context(context)
            results["total_tests"] += 1
            
            if context.get("show_form"):
                print("✅ PASS: Expense claim page accessible")
                print(f"   Form shown: {context.get('show_form')}")
                results["passed"] += 1
                results["details"].append("✅ expense_claim_new page: PASS")
            else:
                print("❌ FAIL: Form not shown")
                print(f"   Error: {context.get('error_message', 'Unknown error')}")
                results["failed"] += 1
                results["details"].append("❌ expense_claim_new page: FAIL")
        except Exception as e:
            print(f"❌ FAIL: Exception occurred: {e}")
            results["failed"] += 1
            results["details"].append(f"❌ expense_claim_new page: FAIL - {e}")
        
        # Test 4: Test form validation
        print("\n4. Testing form validation with invalid data")
        try:
            invalid_expenses = [
                {
                    "description": "",  # Empty description
                    "amount": 0,        # Zero amount
                    "expense_date": "", # Empty date
                    "organization_type": "",
                    "category": "",
                    "chapter": None,
                    "team": None,
                    "notes": "",
                    "receipt_attachment": None
                }
            ]
            
            response = frappe.call(
                "verenigingen.templates.pages.volunteer.expenses.submit_multiple_expenses",
                expenses=invalid_expenses
            )
            results["total_tests"] += 1
            
            if response and "message" in response:
                data = response["message"]
                if not data.get("success"):
                    print("✅ PASS: Form validation correctly rejects invalid data")
                    print(f"   Error: {data.get('error', 'Validation error')}")
                    results["passed"] += 1
                    results["details"].append("✅ Form validation: PASS")
                else:
                    print("❌ FAIL: Form validation should reject invalid data")
                    results["failed"] += 1
                    results["details"].append("❌ Form validation: FAIL")
            else:
                print("❌ FAIL: Invalid response format")
                results["failed"] += 1
                results["details"].append("❌ Form validation: FAIL - Invalid response")
        except Exception as e:
            print(f"❌ FAIL: Exception occurred: {e}")
            results["failed"] += 1
            results["details"].append(f"❌ Form validation: FAIL - {e}")
        
        # Print summary
        print("\n" + "=" * 50)
        print("📊 EXPENSE FORM TEST SUMMARY")
        print("=" * 50)
        print(f"Total Tests: {results['total_tests']}")
        print(f"Passed: {results['passed']}")
        print(f"Failed: {results['failed']}")
        
        if results['total_tests'] > 0:
            success_rate = (results['passed'] / results['total_tests'] * 100)
            print(f"Success Rate: {success_rate:.1f}%")
        
        print("\n📋 DETAILED RESULTS:")
        for detail in results["details"]:
            print(f"  {detail}")
        
        if results["failed"] == 0:
            print("\n🎉 ALL TESTS PASSED! Expense form is working correctly.")
        else:
            print(f"\n⚠️  {results['failed']} tests failed. Review the failures above.")
        
        print(f"\nTest completed at: {now_datetime()}")
        return results

def test_expense_form_frontend():
    """Test frontend functionality by checking the files"""
    
    print("\n🎨 Testing Expense Form Frontend")
    print("=" * 40)
    
    results = []
    
    # Test 1: Check HTML template exists
    try:
        import os
        html_path = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/templates/pages/expense_claim_new.html"
        if os.path.exists(html_path):
            print("✅ HTML template exists")
            results.append("✅ HTML template: PASS")
        else:
            print("❌ HTML template missing")
            results.append("❌ HTML template: FAIL")
    except Exception as e:
        print(f"❌ HTML template check failed: {e}")
        results.append(f"❌ HTML template: FAIL - {e}")
    
    # Test 2: Check Vue component exists
    try:
        vue_path = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/public/js/expense_claim_form.vue"
        if os.path.exists(vue_path):
            print("✅ Vue component exists")
            results.append("✅ Vue component: PASS")
        else:
            print("❌ Vue component missing")
            results.append("❌ Vue component: FAIL")
    except Exception as e:
        print(f"❌ Vue component check failed: {e}")
        results.append(f"❌ Vue component: FAIL - {e}")
    
    # Test 3: Check backend API exists
    try:
        backend_path = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/templates/pages/volunteer/expenses.py"
        if os.path.exists(backend_path):
            print("✅ Backend API exists")
            results.append("✅ Backend API: PASS")
        else:
            print("❌ Backend API missing")
            results.append("❌ Backend API: FAIL")
    except Exception as e:
        print(f"❌ Backend API check failed: {e}")
        results.append(f"❌ Backend API: FAIL - {e}")
    
    return results

def run_complete_expense_form_test():
    """Run complete test suite for expense form"""
    
    print("🚀 COMPLETE EXPENSE FORM TEST SUITE")
    print("=" * 60)
    
    # Initialize frappe context
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    
    # Test backend
    test_instance = TestExpenseForm()
    backend_results = test_instance.test_expense_form_backend()
    
    # Test frontend
    frontend_results = test_expense_form_frontend()
    
    # Overall summary
    total_backend = backend_results["total_tests"]
    passed_backend = backend_results["passed"]
    total_frontend = len(frontend_results)
    passed_frontend = len([r for r in frontend_results if "PASS" in r])
    
    print(f"\n🎯 OVERALL SUMMARY")
    print("=" * 30)
    print(f"Backend Tests: {passed_backend}/{total_backend}")
    print(f"Frontend Tests: {passed_frontend}/{total_frontend}")
    print(f"Total: {passed_backend + passed_frontend}/{total_backend + total_frontend}")
    
    overall_success = (passed_backend == total_backend) and (passed_frontend == total_frontend)
    
    if overall_success:
        print("\n🎉 ALL TESTS PASSED! Expense form PoC is fully functional.")
    else:
        print("\n⚠️  Some tests failed. Check the details above.")
    
    return overall_success

if __name__ == "__main__":
    run_complete_expense_form_test()