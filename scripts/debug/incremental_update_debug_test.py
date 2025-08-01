import frappe
from frappe.utils import add_days, now_datetime, today


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def test_member_incremental_update():
    """Test the incremental update functionality with the specific member"""
    try:
        member_name = "Assoc-Member-2025-07-0030"
        result = {"member_name": member_name, "status": "testing", "details": []}

        # Get the member document
        member_doc = frappe.get_doc("Member", member_name)
        result["details"].append(f"Member found: {member_doc.name}")
        result["details"].append(f"Member employee: {getattr(member_doc, 'employee', 'None')}")
        result["details"].append(f"Member donor: {getattr(member_doc, 'donor', 'None')}")

        # Check current volunteer expenses
        current_expenses = getattr(member_doc, "volunteer_expenses", [])
        result["details"].append(f"Current volunteer expense entries: {len(current_expenses)}")

        for idx, expense in enumerate(current_expenses):
            result["details"].append(
                f"  {idx+1}. {expense.expense_claim} - {expense.status} - {expense.total_sanctioned_amount}"
            )

        # Check if member has employee and what expense claims exist
        if hasattr(member_doc, "employee") and member_doc.employee:
            result["details"].append(f"Checking expense claims for employee: {member_doc.employee}")

            # Get expense claims from database
            expense_claims = frappe.get_all(
                "Expense Claim",
                filters={"employee": member_doc.employee},
                fields=[
                    "name",
                    "posting_date",
                    "total_claimed_amount",
                    "total_sanctioned_amount",
                    "status",
                    "approval_status",
                    "docstatus",
                ],
                order_by="posting_date desc",
                limit=25,
            )

            result["details"].append(f"Found {len(expense_claims)} expense claims in database:")
            for claim in expense_claims:
                result["details"].append(
                    f"  - {claim.name}: {claim.status} (docstatus: {claim.docstatus}) - {claim.total_sanctioned_amount}"
                )

        # Test the incremental update method
        result["details"].append("Testing incremental_update_history_tables method...")

        # Check if method exists
        if hasattr(member_doc, "incremental_update_history_tables"):
            result["details"].append("Method exists on member document")

            # Call the method
            method_result = member_doc.incremental_update_history_tables()
            result["details"].append(f"Method result: {method_result}")
            result["method_result"] = method_result

            # Check the updated expenses after the call
            member_doc.reload()
            updated_expenses = getattr(member_doc, "volunteer_expenses", [])
            result["details"].append(f"Volunteer expense entries after update: {len(updated_expenses)}")
            for idx, expense in enumerate(updated_expenses):
                result["details"].append(
                    f"  {idx+1}. {expense.expense_claim} - {expense.status} - {expense.total_sanctioned_amount}"
                )

        else:
            result["details"].append(
                "ERROR: incremental_update_history_tables method not found on member document"
            )

        result["status"] = "success"
        return result

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        import traceback

        result["traceback"] = traceback.format_exc()
        return result


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def test_expense_mixin_build_method():
    """Test the _build_expense_history_entry method"""
    try:
        member_name = "Assoc-Member-2025-07-0030"
        result = {"member_name": member_name, "status": "testing", "details": []}

        member_doc = frappe.get_doc("Member", member_name)

        if hasattr(member_doc, "employee") and member_doc.employee:
            # Get an expense claim to test with
            expense_claims = frappe.get_all(
                "Expense Claim", filters={"employee": member_doc.employee}, fields=["name"], limit=1
            )

            if expense_claims:
                expense_name = expense_claims[0].name
                result["details"].append(f"Testing _build_expense_history_entry with: {expense_name}")

                expense_doc = frappe.get_doc("Expense Claim", expense_name)
                result["details"].append(f"Expense claim details:")
                result["details"].append(f"  Name: {expense_doc.name}")
                result["details"].append(f"  Employee: {expense_doc.employee}")
                result["details"].append(f"  Posting Date: {expense_doc.posting_date}")
                result["details"].append(f"  Total Claimed: {expense_doc.total_claimed_amount}")
                result["details"].append(f"  Total Sanctioned: {expense_doc.total_sanctioned_amount}")
                result["details"].append(f"  Status: {expense_doc.status}")
                result["details"].append(f"  DocStatus: {expense_doc.docstatus}")

                # Test the build method
                if hasattr(member_doc, "_build_expense_history_entry"):
                    entry = member_doc._build_expense_history_entry(expense_doc)
                    result["details"].append(f"Built entry: {entry}")
                    result["built_entry"] = entry
                else:
                    result["details"].append("ERROR: _build_expense_history_entry method not found")
            else:
                result["details"].append("No expense claims found for this employee")
        else:
            result["details"].append(f"Member {member_name} has no employee linked")

        result["status"] = "success"
        return result

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        import traceback

        result["traceback"] = traceback.format_exc()
        return result
