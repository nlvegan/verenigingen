"""
API endpoint to test the financial history security fix
"""

import frappe

from verenigingen.utils.security.api_security_framework import OperationType, development_only_api


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def test_member_financial_history(member_name="Assoc-Member-2025-07-0870"):
    """
    Test the financial history operation that was failing with bypass_validations error
    """
    try:
        # Check if member exists
        if not frappe.db.exists("Member", member_name):
            return {
                "success": False,
                "error": f"Member {member_name} does not exist",
                "member_name": member_name,
            }

        # Load member document
        member = frappe.get_doc("Member", member_name)

        # Import and create the financial history manager
        from verenigingen.utils.member_financial_history_manager import get_payment_history_manager

        manager = get_payment_history_manager(member)

        # Create a test entry function
        def test_entry_builder():
            return {
                "invoice": "SECURITY-FIX-TEST-001",
                "invoice_date": "2025-01-01",
                "amount": 25.00,
                "status": "Paid",
                "payment_date": "2025-01-01",
                "payment_method": "SEPA Direct Debit",
                "description": "Security fix verification test",
                "customer": member.customer if member.customer else None,
            }

        # Attempt the operation that was previously failing
        result = manager.add_or_update_entry("SECURITY-FIX-TEST-001", test_entry_builder)

        return {
            "success": True,
            "result": result,
            "message": "Financial history operation completed successfully",
            "member_name": member_name,
            "test_completed": True,
        }

    except NameError as e:
        # Check specifically for the bypass_validations error
        error_msg = str(e)
        if "bypass_validations" in error_msg:
            return {
                "success": False,
                "error": "CRITICAL: The original NameError still exists",
                "error_type": "NameError",
                "error_message": error_msg,
                "member_name": member_name,
                "fix_status": "FAILED - bypass_validations variable not found",
            }
        else:
            return {
                "success": False,
                "error": f"Different NameError: {error_msg}",
                "error_type": "NameError",
                "member_name": member_name,
            }

    except Exception as e:
        error_msg = str(e)

        # Check for chapter validation errors (which should be handled now)
        is_chapter_error = "Chapter:" in error_msg and "Could not find Row" in error_msg

        return {
            "success": False,
            "error": error_msg,
            "error_type": type(e).__name__,
            "member_name": member_name,
            "is_chapter_validation_error": is_chapter_error,
            "note": "Chapter validation errors should be handled by bypass_validations"
            if is_chapter_error
            else None,
        }
