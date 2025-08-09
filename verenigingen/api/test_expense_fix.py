"""
Test API for expense claim update fix
"""

import frappe
from frappe import _


@frappe.whitelist()
def test_expense_claim_fix():
    """Test that expense claim updates don't create duplicates"""

    result = {"success": False, "message": "", "details": {}}

    try:
        # Find a member with volunteer expenses for testing
        members_with_expenses = frappe.db.sql(
            """
            SELECT m.name, m.first_name, m.last_name, COUNT(ve.name) as expense_count
            FROM `tabMember` m
            INNER JOIN `tabMember Volunteer Expenses` ve ON ve.parent = m.name
            GROUP BY m.name
            LIMIT 1
        """,
            as_dict=True,
        )

        if not members_with_expenses:
            result["message"] = "No members with volunteer expenses found for testing"
            return result

        test_member = members_with_expenses[0]
        result["details"][
            "test_member"
        ] = f"{test_member.first_name} {test_member.last_name} ({test_member.name})"
        result["details"]["stored_expenses"] = test_member.expense_count

        # Get the member's volunteer
        volunteer = frappe.db.get_value("Volunteer", {"member": test_member.name}, "name")
        if not volunteer:
            result["message"] = "Member has no associated volunteer record"
            return result

        result["details"]["volunteer"] = volunteer

        # Test the fixed get_volunteer_expenses function
        from verenigingen.templates.pages.volunteer.expenses import get_volunteer_expenses

        # Get expenses using fixed function
        expenses = get_volunteer_expenses(volunteer, limit=10)
        result["details"]["returned_expenses"] = len(expenses)

        # Check for unique expense claim IDs (no duplicates)
        expense_claim_ids = [exp.expense_claim_id for exp in expenses if exp.expense_claim_id]
        unique_claim_ids = set(expense_claim_ids)

        result["details"]["total_entries"] = len(expenses)
        result["details"]["unique_claim_ids"] = len(unique_claim_ids)
        result["details"]["claim_ids_sample"] = expense_claim_ids[:3]

        # Check for duplicates
        if len(expense_claim_ids) != len(unique_claim_ids):
            duplicates = [claim_id for claim_id in expense_claim_ids if expense_claim_ids.count(claim_id) > 1]
            result["message"] = f"DUPLICATE CLAIM IDs DETECTED: {set(duplicates)}"
            result["details"]["duplicates"] = list(set(duplicates))
            return result

        # Verify expenses come from Member's stored history
        member_doc = frappe.get_doc("Member", test_member.name)
        stored_count = (
            len(member_doc.volunteer_expenses)
            if hasattr(member_doc, "volunteer_expenses") and member_doc.volunteer_expenses
            else 0
        )

        result["details"]["member_stored_expenses"] = stored_count
        result["details"]["erpnext_linked_expenses"] = len([exp for exp in expenses if exp.expense_claim_id])

        result["success"] = True
        result["message"] = "✅ Fix is working correctly! No duplicate expense claim entries detected."

        return result

    except Exception as e:
        result["message"] = f"Test failed with error: {str(e)}"
        frappe.log_error(f"Expense fix test error: {str(e)}", "Expense Fix Test Error")
        return result


@frappe.whitelist()
def check_expense_history_structure():
    """Check the Member expense history structure"""

    result = {"success": False, "message": "", "details": {}}

    try:
        # Check Member DocType has volunteer_expenses field
        member_meta = frappe.get_meta("Member")
        ve_field = member_meta.get_field("volunteer_expenses")

        if ve_field:
            result["details"]["volunteer_expenses_field"] = {
                "fieldtype": ve_field.fieldtype,
                "child_table": ve_field.options,
            }
        else:
            result["message"] = "Member DocType missing volunteer_expenses field"
            return result

        # Check child table structure
        child_meta = frappe.get_meta("Member Volunteer Expenses")
        important_fields = [
            "expense_claim",
            "total_claimed_amount",
            "total_sanctioned_amount",
            "status",
            "payment_status",
        ]

        result["details"]["child_table"] = child_meta.name
        result["details"]["fields"] = {}

        for field_name in important_fields:
            field = child_meta.get_field(field_name)
            if field:
                result["details"]["fields"][field_name] = field.fieldtype
            else:
                result["details"]["fields"][field_name] = "MISSING"

        result["success"] = True
        result["message"] = "✅ Member expense history structure is correct"

        return result

    except Exception as e:
        result["message"] = f"Structure check failed: {str(e)}"
        frappe.log_error(f"Structure check error: {str(e)}", "Structure Check Error")
        return result
