import frappe
from frappe.utils import today


@frappe.whitelist()
def test_expense_claim_workflow():
    """Test the expense claim approval workflow and event handlers"""

    # Get first employee
    employees = frappe.get_all("Employee", limit=1)
    if not employees:
        return {"error": "No employees found"}

    employee = employees[0].name
    result = {"employee": employee, "steps": []}

    try:
        # Create a simple test expense claim
        expense = frappe.new_doc("Expense Claim")
        expense.employee = employee
        expense.posting_date = today()
        expense.total_claimed_amount = 100.0
        expense.total_sanctioned_amount = 100.0

        # Add a dummy expense item
        expense.append(
            "expenses",
            {
                "expense_date": today(),
                "expense_type": "Travel",
                "description": "Test expense for workflow",
                "amount": 100.0,
                "sanctioned_amount": 100.0,
            },
        )

        expense.insert()
        result["expense_claim"] = expense.name
        result["steps"].append(
            {
                "step": "Created expense claim",
                "approval_status": expense.approval_status,
                "docstatus": expense.docstatus,
            }
        )

        # Submit the expense claim (should NOT add to member history yet)
        expense.submit()
        result["steps"].append(
            {
                "step": "Submitted expense claim",
                "approval_status": expense.approval_status,
                "docstatus": expense.docstatus,
                "note": "Should be Draft approval_status, docstatus=1",
            }
        )

        # Reload to get fresh data
        expense.reload()

        # Now simulate approval by updating approval_status
        # This should trigger on_update_after_submit and the event handler
        expense.approval_status = "Approved"
        expense.save()

        result["steps"].append(
            {
                "step": "Approved expense claim",
                "approval_status": expense.approval_status,
                "docstatus": expense.docstatus,
                "note": "Should have triggered expense_claim_approved event",
            }
        )

        # Check if event was processed by looking at error logs
        recent_logs = frappe.get_all(
            "Error Log",
            filters={"creation": [">", frappe.utils.add_minutes(frappe.utils.now(), -5)]},
            fields=["name", "error"],
            order_by="creation desc",
            limit=3,
        )

        result["recent_error_logs"] = [
            {"name": log.name, "error": log.error[:200] + "..." if len(log.error) > 200 else log.error}
            for log in recent_logs
        ]

        # Test rejection workflow
        expense.approval_status = "Rejected"
        expense.save()

        result["steps"].append(
            {
                "step": "Rejected expense claim",
                "approval_status": expense.approval_status,
                "docstatus": expense.docstatus,
                "note": "Should have triggered expense_claim_rejected event",
            }
        )

        return result

    except Exception as e:
        result["error"] = str(e)
        return result


@frappe.whitelist()
def check_expense_event_logs():
    """Check recent logs for expense-related events"""

    # Check error logs
    recent_error_logs = frappe.get_all(
        "Error Log",
        filters={"creation": [">", frappe.utils.add_minutes(frappe.utils.now(), -10)]},
        fields=["name", "error", "creation"],
        order_by="creation desc",
        limit=5,
    )

    expense_related_logs = []
    for log in recent_error_logs:
        if any(keyword in log.error.lower() for keyword in ["expense", "volunteer", "approval"]):
            expense_related_logs.append(
                {
                    "name": log.name,
                    "creation": log.creation,
                    "error": log.error[:500] + "..." if len(log.error) > 500 else log.error,
                }
            )

    return {"expense_related_logs": expense_related_logs, "total_recent_errors": len(recent_error_logs)}
