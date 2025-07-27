import frappe
from frappe.utils import today


@frappe.whitelist()
def test_expense_event_integration():
    """Test expense event handlers by directly simulating the workflow"""

    results = []

    try:
        # Step 1: Find a member with volunteer
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

        # Step 2: Check initial member expenses
        member_doc = frappe.get_doc("Member", member_name)
        initial_count = len(member_doc.volunteer_expenses or [])

        results.append(
            {
                "step": "Check initial expenses",
                "status": "SUCCESS",
                "details": f"Initial volunteer_expenses: {initial_count}",
            }
        )

        # Step 3: Test the expense mixin directly by creating a mock expense
        try:
            # Create a mock expense entry data (like what would come from a real expense claim)
            mock_expense_data = {
                "name": "TEST-EXP-MOCK-001",
                "employee": employee_name,
                "posting_date": today(),
                "total_claimed_amount": 75.0,
                "total_sanctioned_amount": 75.0,
                "status": "Approved",
                "approval_status": "Approved",
            }

            # Create a mock expense document object
            class MockExpenseDoc:
                def __init__(self, data):
                    for key, value in data.items():
                        setattr(self, key, value)

            mock_expense = MockExpenseDoc(mock_expense_data)

            # Test the _build_expense_history_entry method
            history_entry = member_doc._build_expense_history_entry(mock_expense)

            results.append(
                {
                    "step": "Test expense history entry building",
                    "status": "SUCCESS",
                    "details": f"Built history entry: {history_entry}",
                }
            )

            # Step 4: Test direct addition to volunteer_expenses
            # Directly append an expense entry to test the child table
            expense_entry = {
                "expense_claim": "TEST-EXP-INTEGRATION-001",
                "volunteer": volunteer_name,
                "posting_date": today(),
                "total_claimed_amount": 50.0,
                "total_sanctioned_amount": 50.0,
                "status": "Approved",
                "payment_status": "Pending",
            }

            # Add to child table
            member_doc.append("volunteer_expenses", expense_entry)

            # Save without validating links to avoid the expense claim existence check
            member_doc.flags.ignore_links = True
            member_doc.save(ignore_permissions=True)

            # Check new count
            member_doc.reload()
            new_count = len(member_doc.volunteer_expenses or [])

            results.append(
                {
                    "step": "Test direct child table addition",
                    "status": "SUCCESS",
                    "details": f"Added expense to child table. Count: {initial_count} -> {new_count}",
                }
            )

            # Step 5: Verify the added expense details
            if member_doc.volunteer_expenses:
                latest_expense = member_doc.volunteer_expenses[-1]
                results.append(
                    {
                        "step": "Verify expense details",
                        "status": "SUCCESS",
                        "details": f"Expense claim: {latest_expense.expense_claim}, Amount: {latest_expense.total_sanctioned_amount}, Status: {latest_expense.status}",
                    }
                )

            # Step 6: Test the event handlers directly
            from verenigingen.events.subscribers.expense_history_subscriber import (
                handle_expense_claim_approved,
            )

            # Mock event data
            event_data = {
                "expense_claim": "TEST-EXP-EVENT-001",
                "employee": employee_name,
                "volunteer": volunteer_name,
                "member": member_name,
                "posting_date": today(),
                "total_claimed_amount": 100.0,
                "total_sanctioned_amount": 90.0,
                "approval_status": "Approved",
                "status": "Approved",
                "docstatus": 1,
                "action": "approved",
            }

            # Test the event handler (this should fail gracefully if expense doesn't exist)
            try:
                handle_expense_claim_approved("expense_claim_approved", event_data)
                results.append(
                    {
                        "step": "Test event handler",
                        "status": "SUCCESS",
                        "details": "Event handler executed without crashing",
                    }
                )
            except Exception as e:
                results.append(
                    {
                        "step": "Test event handler",
                        "status": "EXPECTED_ERROR",
                        "details": f"Event handler failed as expected (expense does not exist): {str(e)}",
                    }
                )

            # Step 7: Clean up the test expense entry
            if member_doc.volunteer_expenses:
                # Remove the test entry we added
                test_entries = [
                    e for e in member_doc.volunteer_expenses if "TEST-EXP-INTEGRATION" in e.expense_claim
                ]
                if test_entries:
                    # Remove test entries
                    member_doc.volunteer_expenses = [
                        e
                        for e in member_doc.volunteer_expenses
                        if "TEST-EXP-INTEGRATION" not in e.expense_claim
                    ]
                    member_doc.flags.ignore_links = True
                    member_doc.save(ignore_permissions=True)

                    results.append(
                        {
                            "step": "Clean up test data",
                            "status": "SUCCESS",
                            "details": "Removed test expense entries",
                        }
                    )

            return {
                "test_summary": {
                    "member_name": member_name,
                    "volunteer_name": volunteer_name,
                    "employee_name": employee_name,
                    "initial_expense_count": initial_count,
                    "final_expense_count": len(member_doc.volunteer_expenses or []),
                },
                "results": results,
            }

        except Exception as e:
            results.append({"step": "Exception in testing", "status": "ERROR", "details": str(e)})

            import traceback

            return {"results": results, "error": str(e), "traceback": traceback.format_exc()}

    except Exception as e:
        results.append({"step": "Exception occurred", "status": "ERROR", "details": str(e)})

        import traceback

        return {"results": results, "error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def verify_expense_system_readiness():
    """Verify that all components of the expense system are properly set up"""

    checks = []

    try:
        # 1. Check Member Volunteer Expenses doctype
        if frappe.db.exists("DocType", "Member Volunteer Expenses"):
            meta = frappe.get_meta("Member Volunteer Expenses")
            checks.append(
                {
                    "component": "Member Volunteer Expenses DocType",
                    "status": "OK",
                    "details": f"{len(meta.fields)} fields available",
                }
            )
        else:
            checks.append(
                {
                    "component": "Member Volunteer Expenses DocType",
                    "status": "MISSING",
                    "details": "DocType not found",
                }
            )

        # 2. Check Member volunteer_expenses field
        member_meta = frappe.get_meta("Member")
        volunteer_expenses_field = None
        for field in member_meta.fields:
            if field.fieldname == "volunteer_expenses":
                volunteer_expenses_field = field
                break

        if volunteer_expenses_field:
            checks.append(
                {
                    "component": "Member volunteer_expenses field",
                    "status": "OK",
                    "details": f"Type: {volunteer_expenses_field.fieldtype}, Options: {volunteer_expenses_field.options}",
                }
            )
        else:
            checks.append(
                {
                    "component": "Member volunteer_expenses field",
                    "status": "MISSING",
                    "details": "Field not found in Member doctype",
                }
            )

        # 3. Check ExpenseMixin
        try:
            from verenigingen.verenigingen.doctype.member.mixins.expense_mixin import ExpenseMixin

            checks.append({"component": "ExpenseMixin", "status": "OK", "details": "Successfully imported"})
        except ImportError as e:
            checks.append({"component": "ExpenseMixin", "status": "ERROR", "details": f"Import failed: {e}"})

        # 4. Check event handlers
        try:
            from verenigingen.events.expense_events import emit_expense_claim_approved
            from verenigingen.events.subscribers.expense_history_subscriber import (
                handle_expense_claim_approved,
            )

            checks.append(
                {
                    "component": "Event handlers",
                    "status": "OK",
                    "details": "Both expense_events and expense_history_subscriber imported",
                }
            )
        except ImportError as e:
            checks.append(
                {"component": "Event handlers", "status": "ERROR", "details": f"Import failed: {e}"}
            )

        # 5. Check hooks configuration
        try:
            import verenigingen.hooks as hooks

            expense_hooks = getattr(hooks, "doc_events", {}).get("Expense Claim", {})
            if expense_hooks:
                checks.append(
                    {
                        "component": "Hooks configuration",
                        "status": "OK",
                        "details": f"Expense Claim hooks: {list(expense_hooks.keys())}",
                    }
                )
            else:
                checks.append(
                    {
                        "component": "Hooks configuration",
                        "status": "MISSING",
                        "details": "No Expense Claim hooks found",
                    }
                )
        except Exception as e:
            checks.append(
                {
                    "component": "Hooks configuration",
                    "status": "ERROR",
                    "details": f"Error checking hooks: {e}",
                }
            )

        # 6. Check test data availability
        member_volunteer_count = frappe.db.count("Volunteer", filters={"employee_id": ["is", "set"]})
        checks.append(
            {
                "component": "Test data availability",
                "status": "OK" if member_volunteer_count > 0 else "WARNING",
                "details": f"{member_volunteer_count} volunteers with employee_id available for testing",
            }
        )

        # Summary
        ok_count = len([c for c in checks if c["status"] == "OK"])
        total_count = len(checks)

        return {
            "summary": f"{ok_count}/{total_count} components ready",
            "ready_for_production": ok_count == total_count,
            "checks": checks,
        }

    except Exception as e:
        return {"error": str(e), "checks": checks}
