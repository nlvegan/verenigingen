#!/usr/bin/env python3
"""
Complete ERPNext Expense Claims Integration Test
Tests the full workflow from volunteer creation to expense submission and ERPNext integration
"""

import json
import os
import sys

import frappe
from frappe.test_runner import make_test_records
from frappe.utils import getdate, now_datetime, today


def setup_test_environment():
    """Set up test environment"""
    print("Setting up test environment...")

    # Connect to Frappe
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    # Check if we have the required apps installed
    apps = frappe.get_installed_apps()
    required_apps = ["verenigingen", "erpnext"]

    for app in required_apps:
        if app not in apps:
            print(f"❌ Required app '{app}' not installed")
            return False
        else:
            print(f"✅ App '{app}' is installed")

    return True


def test_cost_center_creation():
    """Test cost center creation for chapters and teams"""
    print("\n--- Testing Cost Center Creation ---")

    try:
        # Test chapter cost center creation
        test_chapter_name = "Test Chapter for Integration"

        # Create or get test chapter
        if frappe.db.exists("Chapter", test_chapter_name):
            chapter = frappe.get_doc("Chapter", test_chapter_name)
        else:
            chapter = frappe.get_doc(
                {
                    "doctype": "Chapter",
                    "chapter_name": test_chapter_name,
                    "chapter_code": "TEST_INTEG",
                    "status": "Active"}
            )
            chapter.insert(ignore_permissions=True)

        # Trigger save to create cost center
        chapter.save()

        if hasattr(chapter, "cost_center") and chapter.cost_center:
            print(f"✅ Chapter cost center created: {chapter.cost_center}")

            # Verify cost center exists in ERPNext
            if frappe.db.exists("Cost Center", chapter.cost_center):
                print(f"✅ Cost center {chapter.cost_center} exists in ERPNext")
                return chapter
            else:
                print(f"❌ Cost center {chapter.cost_center} not found in ERPNext")
                return None
        else:
            print(f"❌ Chapter cost center not created")
            return None

    except Exception as e:
        print(f"❌ Error testing cost center creation: {str(e)}")
        return None


def test_employee_creation():
    """Test employee creation for volunteers"""
    print("\n--- Testing Employee Creation ---")

    try:
        # Create test member first
        test_member_name = "Integration Test Member"
        test_email = "integration.test@example.org"

        if frappe.db.exists("Member", {"email": test_email}):
            member = frappe.get_doc("Member", {"email": test_email})
        else:
            member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "full_name": test_member_name,
                    "first_name": "Integration",
                    "last_name": "Test",
                    "email": test_email,
                    "status": "Active",
                    "application_status": "Approved"}
            )
            member.insert(ignore_permissions=True)

        # Create volunteer from member
        from verenigingen.verenigingen.doctype.volunteer.volunteer import create_volunteer_from_member

        volunteer = create_volunteer_from_member(member)

        if volunteer and volunteer.employee_id:
            print(f"✅ Employee created for volunteer: {volunteer.employee_id}")

            # Verify employee exists in ERPNext
            if frappe.db.exists("Employee", volunteer.employee_id):
                employee = frappe.get_doc("Employee", volunteer.employee_id)
                print(f"✅ Employee {employee.name} exists in ERPNext with name: {employee.employee_name}")
                return volunteer, employee
            else:
                print(f"❌ Employee {volunteer.employee_id} not found in ERPNext")
                return None, None
        else:
            print(f"❌ Employee not created for volunteer")
            return None, None

    except Exception as e:
        print(f"❌ Error testing employee creation: {str(e)}")
        return None, None


def test_expense_category_creation():
    """Test expense category to expense type mapping"""
    print("\n--- Testing Expense Category Creation ---")

    try:
        # Test category creation
        test_category_name = "Integration Test Category"

        if frappe.db.exists("Expense Category", test_category_name):
            category = frappe.get_doc("Expense Category", test_category_name)
        else:
            category = frappe.get_doc(
                {
                    "doctype": "Expense Category",
                    "category_name": test_category_name,
                    "description": "Test category for integration testing"}
            )
            category.insert(ignore_permissions=True)

        # Test expense type creation via helper function
        from verenigingen.templates.pages.volunteer.expenses import get_or_create_expense_type

        expense_type = get_or_create_expense_type(test_category_name)

        if expense_type:
            print(f"✅ Expense type created/found: {expense_type}")

            # Verify expense type exists in ERPNext
            if frappe.db.exists("Expense Claim Type", expense_type):
                print(f"✅ Expense type {expense_type} exists in ERPNext")
                return category, expense_type
            else:
                print(f"❌ Expense type {expense_type} not found in ERPNext")
                return None, None
        else:
            print(f"❌ Expense type not created")
            return None, None

    except Exception as e:
        print(f"❌ Error testing expense category creation: {str(e)}")
        return None, None


def test_expense_claim_creation(volunteer, employee, chapter, expense_type):
    """Test creating ERPNext Expense Claim from portal submission"""
    print("\n--- Testing Expense Claim Creation ---")

    try:
        # Prepare expense data
        expense_data = {
            "description": "Integration Test Expense",
            "amount": 25.50,
            "expense_date": today(),
            "category": expense_type,
            "organization": chapter.name if chapter else None,
            "notes": "Test expense for integration testing"}

        # Test the expense submission function
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        # Mock the session context for volunteer
        frappe.session.user = volunteer.user if volunteer.user else "Administrator"

        # Submit expense
        result = submit_expense(expense_data)

        if result and result.get("success"):
            expense_claim_name = result.get("expense_claim_name")
            print(f"✅ Expense claim created: {expense_claim_name}")

            # Verify expense claim exists in ERPNext
            if frappe.db.exists("Expense Claim", expense_claim_name):
                expense_claim = frappe.get_doc("Expense Claim", expense_claim_name)
                print(f"✅ Expense claim details:")
                print(f"   - Employee: {expense_claim.employee}")
                print(f"   - Total Amount: {expense_claim.total_sanctioned_amount}")
                print(f"   - Status: {expense_claim.approval_status}")

                if hasattr(expense_claim, "cost_center") and expense_claim.cost_center:
                    print(f"   - Cost Center: {expense_claim.cost_center}")

                return expense_claim
            else:
                print(f"❌ Expense claim {expense_claim_name} not found in ERPNext")
                return None
        else:
            error_msg = result.get("message", "Unknown error") if result else "No result returned"
            print(f"❌ Expense submission failed: {error_msg}")
            return None

    except Exception as e:
        print(f"❌ Error testing expense claim creation: {str(e)}")
        print(f"   Exception details: {type(e).__name__}: {str(e)}")
        return None


def test_expense_statistics(volunteer):
    """Test expense statistics retrieval"""
    print("\n--- Testing Expense Statistics ---")

    try:
        from verenigingen.templates.pages.volunteer.expenses import get_expense_statistics

        stats = get_expense_statistics(volunteer.name)

        if stats:
            print(f"✅ Expense statistics retrieved:")
            print(f"   - Total Submitted: €{stats.get('total_submitted', 0):.2f}")
            print(f"   - Total Approved: €{stats.get('total_approved', 0):.2f}")
            print(f"   - Pending Count: {stats.get('pending_count', 0)}")
            print(f"   - Approved Count: {stats.get('approved_count', 0)}")
            return True
        else:
            print(f"❌ No expense statistics returned")
            return False

    except Exception as e:
        print(f"❌ Error testing expense statistics: {str(e)}")
        return False


def test_portal_visibility(volunteer):
    """Test expense visibility on volunteer form and member portal"""
    print("\n--- Testing Portal Visibility ---")

    try:
        # Test volunteer form expense visibility
        from verenigingen.templates.pages.volunteer.expenses import get_volunteer_expenses

        expenses = get_volunteer_expenses(volunteer.name, limit=5)

        if expenses is not None:
            print(f"✅ Retrieved {len(expenses)} expenses for volunteer form")

            # Test member portal context
            from verenigingen.templates.pages.member_portal import get_context

            # Mock request context
            class MockContext:
                def __init__(self):
                    self.no_cache = 1
                    self.show_sidebar = True
                    self.title = "Member Portal"

            # Test context generation
            context = MockContext()

            # Mock session for member
            if volunteer.member:
                member = frappe.get_doc("Member", volunteer.member)
                if member.user:
                    frappe.session.user = member.user

                    # Get portal context
                    portal_context = get_context(context)

                    if hasattr(portal_context, "expense_stats") and portal_context.expense_stats:
                        print(f"✅ Member portal has expense statistics")

                    if hasattr(portal_context, "recent_expenses") and portal_context.recent_expenses:
                        print(
                            f"✅ Member portal has recent expenses: {len(portal_context.recent_expenses)} items"
                        )

                    return True

            return True
        else:
            print(f"❌ Could not retrieve expenses for volunteer")
            return False

    except Exception as e:
        print(f"❌ Error testing portal visibility: {str(e)}")
        return False


def run_comprehensive_test():
    """Run the complete integration test"""
    print("🚀 Starting ERPNext Expense Claims Integration Test")
    print("=" * 60)

    if not setup_test_environment():
        return False

    success_count = 0
    total_tests = 6

    # Test 1: Cost Center Creation
    chapter = test_cost_center_creation()
    if chapter:
        success_count += 1

    # Test 2: Employee Creation
    volunteer, employee = test_employee_creation()
    if volunteer and employee:
        success_count += 1

    # Test 3: Expense Category Creation
    category, expense_type = test_expense_category_creation()
    if category and expense_type:
        success_count += 1

    # Test 4: Expense Claim Creation (main integration test)
    expense_claim = None
    if volunteer and employee and expense_type:
        expense_claim = test_expense_claim_creation(volunteer, employee, chapter, expense_type)
        if expense_claim:
            success_count += 1

    # Test 5: Expense Statistics
    if volunteer:
        if test_expense_statistics(volunteer):
            success_count += 1

    # Test 6: Portal Visibility
    if volunteer:
        if test_portal_visibility(volunteer):
            success_count += 1

    print("\n" + "=" * 60)
    print(f"🎯 Integration Test Results: {success_count}/{total_tests} tests passed")

    if success_count == total_tests:
        print("✅ All integration tests PASSED! ERPNext integration is working correctly.")
        return True
    else:
        print(f"❌ {total_tests - success_count} tests FAILED. Please review the errors above.")
        return False


if __name__ == "__main__":
    try:
        success = run_comprehensive_test()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"💥 Test runner crashed: {str(e)}")
        sys.exit(1)
    finally:
        if "frappe" in globals():
            frappe.destroy()
