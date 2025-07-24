import frappe
from frappe.utils import flt, today


@frappe.whitelist()
def test_complete_expense_workflow():
    """Test the complete expense claim workflow with real data to verify event handlers"""

    results = []

    try:
        # Step 1: Find a member with a volunteer record
        member_volunteer_data = frappe.db.sql(
            """
            SELECT m.name as member_name, v.name as volunteer_name, v.employee_id
            FROM tabMember m
            INNER JOIN tabVolunteer v ON v.member = m.name
            WHERE v.employee_id IS NOT NULL AND v.employee_id != ''
            LIMIT 1
        """,
            as_dict=True,
        )

        if not member_volunteer_data:
            return {"error": "No member with volunteer and employee found"}

        member_name = member_volunteer_data[0]["member_name"]
        volunteer_name = member_volunteer_data[0]["volunteer_name"]
        employee_name = member_volunteer_data[0]["employee_id"]

        results.append(
            {
                "step": "Find test data",
                "status": "SUCCESS",
                "details": f"Member: {member_name}, Volunteer: {volunteer_name}, Employee: {employee_name}",
            }
        )

        # Step 2: Check initial state of member volunteer expenses
        member_doc = frappe.get_doc("Member", member_name)
        initial_expense_count = len(member_doc.volunteer_expenses or [])

        results.append(
            {
                "step": "Check initial member expenses",
                "status": "SUCCESS",
                "details": f"Initial volunteer_expenses count: {initial_expense_count}",
            }
        )

        # Step 3: Create a test expense claim
        expense_claim = frappe.new_doc("Expense Claim")
        expense_claim.employee = employee_name
        expense_claim.posting_date = today()
        expense_claim.company = "Nederlandse Vereniging voor Veganisme"

        # Add expense details
        expense_claim.append(
            "expenses",
            {
                "expense_date": today(),
                "expense_type": "Travel",
                "description": "Test volunteer travel expense",
                "amount": 50.0,
                "sanctioned_amount": 50.0,
            },
        )

        # Calculate totals
        expense_claim.total_claimed_amount = 50.0
        expense_claim.total_sanctioned_amount = 50.0

        expense_claim.insert()

        results.append(
            {
                "step": "Create expense claim",
                "status": "SUCCESS",
                "details": f"Created expense claim: {expense_claim.name}, Status: {expense_claim.approval_status}",
            }
        )

        # Step 4: Submit the expense claim (should NOT trigger member history update yet)
        expense_claim.submit()

        # Check member expenses after submit (should be unchanged)
        member_doc.reload()
        after_submit_count = len(member_doc.volunteer_expenses or [])

        results.append(
            {
                "step": "Submit expense claim",
                "status": "SUCCESS",
                "details": f"Submitted expense claim. Member expenses count: {after_submit_count} (should equal initial: {initial_expense_count})",
            }
        )

        # Step 5: Approve the expense claim (should trigger member history update)
        expense_claim.reload()
        expense_claim.approval_status = "Approved"
        expense_claim.save()  # This should trigger on_update_after_submit

        # Give a moment for the event to process
        frappe.db.commit()

        # Check member expenses after approval (should be increased)
        member_doc.reload()
        after_approval_count = len(member_doc.volunteer_expenses or [])

        results.append(
            {
                "step": "Approve expense claim",
                "status": "SUCCESS",
                "details": f"Approved expense claim. Member expenses count: {after_approval_count} (should be {initial_expense_count + 1})",
            }
        )

        # Step 6: Verify the expense entry details
        if member_doc.volunteer_expenses and after_approval_count > initial_expense_count:
            # Find the new expense entry
            new_expense = None
            for expense in member_doc.volunteer_expenses:
                if expense.expense_claim == expense_claim.name:
                    new_expense = expense
                    break

            if new_expense:
                results.append(
                    {
                        "step": "Verify expense entry details",
                        "status": "SUCCESS",
                        "details": f"Found expense entry: Claim={new_expense.expense_claim}, Volunteer={new_expense.volunteer}, Amount={new_expense.total_sanctioned_amount}, Status={new_expense.status}, Payment Status={new_expense.payment_status}",
                    }
                )
            else:
                results.append(
                    {
                        "step": "Verify expense entry details",
                        "status": "FAIL",
                        "details": "Expense entry not found in member history",
                    }
                )
        else:
            results.append(
                {
                    "step": "Verify expense entry details",
                    "status": "FAIL",
                    "details": f"Member expenses count did not increase. Expected: {initial_expense_count + 1}, Got: {after_approval_count}",
                }
            )

        # Step 7: Test rejection workflow
        # Create another expense claim to test rejection
        expense_claim_2 = frappe.new_doc("Expense Claim")
        expense_claim_2.employee = employee_name
        expense_claim_2.posting_date = today()
        expense_claim_2.company = "Nederlandse Vereniging voor Veganisme"

        expense_claim_2.append(
            "expenses",
            {
                "expense_date": today(),
                "expense_type": "Travel",
                "description": "Test rejection workflow",
                "amount": 25.0,
                "sanctioned_amount": 25.0,
            },
        )

        expense_claim_2.total_claimed_amount = 25.0
        expense_claim_2.total_sanctioned_amount = 25.0

        expense_claim_2.insert()
        expense_claim_2.submit()

        # Approve first, then reject
        expense_claim_2.reload()
        expense_claim_2.approval_status = "Approved"
        expense_claim_2.save()

        # Check count after second approval
        member_doc.reload()
        after_second_approval = len(member_doc.volunteer_expenses or [])

        # Now reject it
        expense_claim_2.reload()
        expense_claim_2.approval_status = "Rejected"
        expense_claim_2.save()

        # Check count after rejection
        member_doc.reload()
        after_rejection = len(member_doc.volunteer_expenses or [])

        results.append(
            {
                "step": "Test rejection workflow",
                "status": "SUCCESS",
                "details": f"After 2nd approval: {after_second_approval}, After rejection: {after_rejection} (should be {after_second_approval - 1})",
            }
        )

        # Step 8: Check recent error logs for any issues
        recent_logs = frappe.get_all(
            "Error Log",
            filters={"creation": [">", frappe.utils.add_to_date(frappe.utils.now(), minutes=-5)]},
            fields=["name", "error"],
            order_by="creation desc",
            limit=3,
        )

        expense_related_logs = []
        for log in recent_logs:
            if any(keyword in log.error.lower() for keyword in ["expense", "volunteer", "approval"]):
                expense_related_logs.append(
                    {
                        "name": log.name,
                        "error_preview": log.error[:200] + "..." if len(log.error) > 200 else log.error,
                    }
                )

        if expense_related_logs:
            results.append(
                {
                    "step": "Check for errors",
                    "status": "WARNING",
                    "details": f"Found {len(expense_related_logs)} expense-related error logs",
                }
            )
        else:
            results.append(
                {
                    "step": "Check for errors",
                    "status": "SUCCESS",
                    "details": "No expense-related errors found in recent logs",
                }
            )

        return {
            "test_summary": {
                "member_name": member_name,
                "volunteer_name": volunteer_name,
                "expense_claims_created": [expense_claim.name, expense_claim_2.name],
                "initial_expense_count": initial_expense_count,
                "final_expense_count": len(member_doc.volunteer_expenses or []),
            },
            "results": results,
            "expense_related_logs": expense_related_logs,
        }

    except Exception as e:
        results.append({"step": "Exception occurred", "status": "ERROR", "details": str(e)})

        # Get traceback for debugging
        import traceback

        traceback_str = traceback.format_exc()

        return {"results": results, "error": str(e), "traceback": traceback_str}


@frappe.whitelist()
def cleanup_test_expense_claims():
    """Clean up test expense claims created during testing"""

    try:
        # Find test expense claims (those with "Test" in description)
        test_claims = frappe.get_all(
            "Expense Claim",
            filters={"expenses.description": ["like", "%Test%"]},
            fields=["name", "docstatus"],
        )

        cleaned_up = []
        for claim in test_claims:
            try:
                doc = frappe.get_doc("Expense Claim", claim.name)
                if doc.docstatus == 1:  # Submitted
                    doc.cancel()
                doc.delete()
                cleaned_up.append(claim.name)
            except Exception as e:
                frappe.log_error(f"Error cleaning up expense claim {claim.name}: {str(e)}")

        return {"status": "SUCCESS", "cleaned_up": cleaned_up, "count": len(cleaned_up)}

    except Exception as e:
        return {"status": "ERROR", "error": str(e)}
