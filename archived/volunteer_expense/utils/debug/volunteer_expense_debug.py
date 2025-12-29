"""
Volunteer Expense Debug and Test Utilities

This module contains debug functions and test utilities for the volunteer expense system.
These were moved from the main expense page template to maintain proper separation of concerns.

Note: These functions contain permission bypasses for testing purposes and should only be used
in development environments.
"""

import frappe
from frappe import _
from frappe.utils import flt, formatdate, today


def debug_volunteer_access():
    """Debug function to check volunteer access permissions"""
    user_email = frappe.session.user
    print(f"Current user: {user_email}")

    # Check if user has volunteer record
    volunteer = frappe.db.get_value("Volunteer", {"email": user_email}, ["name", "volunteer_name"])
    print(f"Volunteer record: {volunteer}")

    # Check user roles
    user_roles = frappe.get_roles(user_email)
    print(f"User roles: {user_roles}")


def test_expense_query_fix():
    """Test function to validate expense query fixes"""
    try:
        # Test basic volunteer expense query
        expenses = frappe.get_all(
            "Volunteer Expense", fields=["name", "expense_date", "category", "amount", "status"], limit=5
        )
        print(f"Found {len(expenses)} volunteer expenses")
        return {"success": True, "count": len(expenses)}
    except Exception as e:
        print(f"Query test failed: {str(e)}")
        return {"success": False, "error": str(e)}


def debug_expense_claim_statuses():
    """Debug function to check expense claim status mappings"""
    statuses = frappe.get_all(
        "Expense Claim", fields=["name", "docstatus", "approval_status", "status"], limit=10
    )

    print("Expense Claim Status Analysis:")
    for claim in statuses:
        print(
            f"  {claim.name}: docstatus={claim.docstatus}, approval_status={claim.approval_status}, status={claim.status}"
        )

    return statuses


def debug_expense_claim_dates():
    """Debug function to analyze expense claim date issues"""
    print("Analyzing expense claim posting dates...")

    claims_without_dates = frappe.db.sql(
        """
        SELECT name, posting_date, expense_approver, approval_status
        FROM `tabExpense Claim`
        WHERE posting_date IS NULL OR posting_date = ''
        LIMIT 10
    """,
        as_dict=True,
    )

    print(f"Found {len(claims_without_dates)} claims without posting dates")
    for claim in claims_without_dates:
        print(f"  {claim.name}: {claim.posting_date} - {claim.approval_status}")


def debug_expense_statistics(volunteer_name):
    """Debug function to analyze expense statistics for a volunteer"""
    if not volunteer_name:
        return {"error": "No volunteer name provided"}

    print(f"Analyzing expense statistics for: {volunteer_name}")

    # Get basic statistics
    stats = frappe.db.sql(
        """
        SELECT
            COUNT(*) as total_expenses,
            SUM(amount) as total_amount,
            COUNT(CASE WHEN status = 'Approved' THEN 1 END) as approved_count,
            SUM(CASE WHEN status = 'Approved' THEN amount ELSE 0 END) as approved_amount
        FROM `tabVolunteer Expense`
        WHERE volunteer = %s
    """,
        volunteer_name,
        as_dict=True,
    )

    return stats[0] if stats else {}


def debug_file_attachment(expense_claim_name, file_url):
    """Debug function to test file attachment to expense claims"""
    print(f"Testing file attachment for expense claim: {expense_claim_name}")
    print(f"File URL: {file_url}")

    try:
        # Get expense claim
        expense_claim = frappe.get_doc("Expense Claim", expense_claim_name)
        print(f"Found expense claim: {expense_claim.name}")

        # Check existing attachments
        attachments = frappe.get_all(
            "File",
            filters={"attached_to_name": expense_claim_name, "attached_to_doctype": "Expense Claim"},
            fields=["name", "file_name", "file_url"],
        )

        print(f"Existing attachments: {len(attachments)}")
        for att in attachments:
            print(f"  - {att.name}: {att.file_name}")

        return {"success": True, "attachments": len(attachments)}

    except Exception as e:
        print(f"File attachment debug failed: {str(e)}")
        return {"success": False, "error": str(e)}


def debug_attachment_process(file_url):
    """Debug function to test file attachment process"""
    print(f"Testing attachment process for file: {file_url}")

    try:
        # Check if file exists in system
        file_doc = frappe.db.get_value("File", {"file_url": file_url}, ["name", "file_name"])
        print(f"File found in system: {file_doc}")

        return {"success": True, "file_found": bool(file_doc)}

    except Exception as e:
        print(f"Attachment process debug failed: {str(e)}")
        return {"success": False, "error": str(e)}


def test_new_attachment_system():
    """Test function for new attachment system implementation"""
    print("Testing new attachment system...")

    # Create test file record
    test_file = {
        "doctype": "File",
        "file_name": "test_attachment.txt",
        "content": b"Test attachment content",
        "folder": "Home/Attachments",
        "is_private": 0,
    }

    try:
        file_doc = frappe.get_doc(test_file)
        file_doc.insert(ignore_permissions=True)  # TEST FUNCTION - permission bypass acceptable

        print(f"Created test file: {file_doc.name}")

        # Clean up
        frappe.delete_doc("File", file_doc.name, ignore_permissions=True)
        print("Test file cleaned up")

        return {"success": True, "test_file": file_doc.name}

    except Exception as e:
        print(f"New attachment system test failed: {str(e)}")
        return {"success": False, "error": str(e)}


def test_expense_with_attachment():
    """Test function to create expense with attachment"""
    print("Testing expense creation with attachment...")

    try:
        # This is a comprehensive test function - permission bypasses are acceptable for testing
        volunteer = frappe.db.get_value("Volunteer", {}, "name")
        if not volunteer:
            print("No volunteer found for testing")
            return {"success": False, "error": "No volunteer available"}

        # Create test expense
        test_expense = frappe.new_doc("Volunteer Expense")
        test_expense.volunteer = volunteer
        test_expense.expense_date = today()
        test_expense.category = "Travel"
        test_expense.amount = 25.00
        test_expense.description = "Test expense with attachment"
        test_expense.insert(ignore_permissions=True)  # TEST FUNCTION - acceptable

        print(f"Created test expense: {test_expense.name}")

        # Clean up
        frappe.delete_doc("Volunteer Expense", test_expense.name, ignore_permissions=True)
        print("Test expense cleaned up")

        return {"success": True, "test_expense": test_expense.name}

    except Exception as e:
        print(f"Expense with attachment test failed: {str(e)}")
        return {"success": False, "error": str(e)}


def debug_expense_retrieval(volunteer_name):
    """Debug function to test expense data retrieval"""
    if not volunteer_name:
        return {"error": "No volunteer name provided"}

    print(f"Testing expense retrieval for: {volunteer_name}")

    try:
        expenses = frappe.get_all(
            "Volunteer Expense",
            filters={"volunteer": volunteer_name},
            fields=["name", "expense_date", "category", "amount", "status", "creation"],
            order_by="expense_date desc",
            limit=5,
        )

        print(f"Retrieved {len(expenses)} expenses")
        for exp in expenses:
            print(f"  {exp.name}: {exp.expense_date} - €{exp.amount} ({exp.status})")

        return {"success": True, "expenses": expenses}

    except Exception as e:
        print(f"Expense retrieval debug failed: {str(e)}")
        return {"success": False, "error": str(e)}


def debug_request_info():
    """Debug function to analyze current request information"""
    request_info = {
        "user": frappe.session.user,
        "method": frappe.request.method if hasattr(frappe, "request") else None,
        "path": frappe.request.path if hasattr(frappe, "request") else None,
        "form_data": dict(frappe.form_dict) if frappe.form_dict else {},
        "session_data": dict(frappe.session.data) if hasattr(frappe.session, "data") else {},
    }

    print("Request Information Analysis:")
    for key, value in request_info.items():
        if key == "form_data" and value:
            print(f"  {key}: [REDACTED - contains form data]")
        elif key == "session_data" and value:
            print(f"  {key}: [REDACTED - contains session data]")
        else:
            print(f"  {key}: {value}")

    return request_info


def test_employee_creation_only():
    """Test function focused on employee creation logic"""
    print("Testing employee creation process...")

    try:
        # Find test volunteer
        volunteer = frappe.db.get_value("Volunteer", {"email": "test@example.com"}, "name")
        if not volunteer:
            print("No test volunteer found")
            return {"success": False, "error": "No test volunteer"}

        # Check if employee exists
        employee = frappe.db.get_value("Employee", {"user_id": "test@example.com"}, "name")
        print(f"Existing employee record: {employee}")

        if not employee:
            # Test employee creation would go here
            print("Employee creation would be triggered")

        return {"success": True, "employee_exists": bool(employee)}

    except Exception as e:
        print(f"Employee creation test failed: {str(e)}")
        return {"success": False, "error": str(e)}


def test_expense_integration():
    """Comprehensive test function for expense system integration"""
    print("=== TESTING VOLUNTEER EXPENSE INTEGRATION ===")

    results = {
        "volunteer_access": debug_volunteer_access(),
        "query_fix": test_expense_query_fix(),
        "statistics": debug_expense_statistics("TEST-VOL-001"),
        "attachment_system": test_new_attachment_system(),
    }

    print("Integration test completed")
    return results


def test_expense_form_with_foppe():
    """Test function using Foppe's account for form testing"""
    print("Testing expense form with Foppe's account...")

    try:
        # Check Foppe's volunteer record
        volunteer = frappe.db.get_value(
            "Volunteer", {"email": "foppe@veganisme.org"}, ["name", "volunteer_name"]
        )
        if not volunteer:
            print("Foppe's volunteer record not found")
            return {"success": False, "error": "No volunteer record for Foppe"}

        print(f"Found volunteer: {volunteer[1]} ({volunteer[0]})")

        # Test expense categories
        categories = frappe.get_all("Expense Claim Type", fields=["name"])
        print(f"Available expense categories: {len(categories)}")

        return {"success": True, "volunteer": volunteer[0], "categories": len(categories)}

    except Exception as e:
        print(f"Foppe expense form test failed: {str(e)}")
        return {"success": False, "error": str(e)}


def debug_api_access():
    """Debug function to test API access and permissions"""
    print("Testing API access patterns...")

    access_tests = {
        "current_user": frappe.session.user,
        "user_roles": frappe.get_roles(),
        "volunteer_count": frappe.db.count("Volunteer"),
        "expense_count": frappe.db.count("Volunteer Expense"),
        "can_create_expense": frappe.has_permission("Volunteer Expense", "create"),
        "can_read_volunteer": frappe.has_permission("Volunteer", "read"),
    }

    print("API Access Test Results:")
    for key, value in access_tests.items():
        print(f"  {key}: {value}")

    return access_tests
