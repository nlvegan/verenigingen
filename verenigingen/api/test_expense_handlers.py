import frappe


@frappe.whitelist()
def test_expense_event_handlers():
    """Test expense event handlers directly by simulating event data"""

    results = []

    try:
        # Test 1: Import the event handlers
        from verenigingen.events.expense_events import _emit_expense_approval_event
        from verenigingen.events.subscribers.expense_history_subscriber import handle_expense_claim_approved

        results.append(
            {
                "test": "Import event handlers",
                "status": "SUCCESS",
                "message": "Event handlers imported successfully",
            }
        )

        # Test 2: Check if we have volunteers with members
        volunteers = frappe.get_all(
            "Volunteer", filters={"member": ["!=", ""]}, fields=["name", "member"], limit=1
        )

        if not volunteers:
            results.append(
                {
                    "test": "Find volunteer with member",
                    "status": "SKIP",
                    "message": "No volunteers with member links found",
                }
            )
            return {"results": results}

        volunteer = volunteers[0]
        results.append(
            {
                "test": "Find volunteer with member",
                "status": "SUCCESS",
                "message": f"Found volunteer {volunteer.name} linked to member {volunteer.member}",
            }
        )

        # Test 3: Simulate expense approval event
        mock_event_data = {
            "expense_claim": "TEST-EXP-001",
            "employee": "HR-EMP-00001",
            "volunteer": volunteer.name,
            "member": volunteer.member,
            "posting_date": "2025-07-24",
            "total_claimed_amount": 100.0,
            "total_sanctioned_amount": 100.0,
            "approval_status": "Approved",
            "status": "Approved",
            "docstatus": 1,
            "action": "approved",
            "expense_type": "Volunteer Expense",
        }

        # Call the event handler directly
        handle_expense_claim_approved("expense_claim_approved", mock_event_data)

        results.append(
            {
                "test": "Call expense approval handler",
                "status": "SUCCESS",
                "message": f"Called handler for member {volunteer.member}",
            }
        )

        # Test 4: Check if member has volunteer_expenses field
        member_doc = frappe.get_doc("Member", volunteer.member)

        if hasattr(member_doc, "volunteer_expenses"):
            results.append(
                {
                    "test": "Check member volunteer_expenses field",
                    "status": "SUCCESS",
                    "message": f"Member has volunteer_expenses field with {len(member_doc.volunteer_expenses or [])} entries",
                }
            )
        else:
            results.append(
                {
                    "test": "Check member volunteer_expenses field",
                    "status": "FAIL",
                    "message": "Member does not have volunteer_expenses field - migration needed",
                }
            )

        # Test 5: Check if expense mixin methods exist
        if hasattr(member_doc, "add_expense_to_history"):
            results.append(
                {
                    "test": "Check expense mixin methods",
                    "status": "SUCCESS",
                    "message": "Member has add_expense_to_history method",
                }
            )
        else:
            results.append(
                {
                    "test": "Check expense mixin methods",
                    "status": "FAIL",
                    "message": "Member missing add_expense_to_history method - ExpenseMixin not loaded",
                }
            )

        return {"results": results}

    except Exception as e:
        results.append({"test": "Exception occurred", "status": "ERROR", "message": str(e)})
        return {"results": results}


@frappe.whitelist()
def check_member_doctype_fields():
    """Check if Member doctype has the volunteer_expenses field"""

    try:
        member_meta = frappe.get_meta("Member")

        # Check if volunteer_expenses field exists
        volunteer_expenses_field = None
        for field in member_meta.fields:
            if field.fieldname == "volunteer_expenses":
                volunteer_expenses_field = field
                break

        if volunteer_expenses_field:
            return {
                "status": "SUCCESS",
                "message": "volunteer_expenses field found in Member doctype",
                "field_details": {
                    "fieldtype": volunteer_expenses_field.fieldtype,
                    "options": volunteer_expenses_field.options,
                    "label": volunteer_expenses_field.label,
                },
            }
        else:
            return {
                "status": "FAIL",
                "message": "volunteer_expenses field NOT found in Member doctype",
                "available_fields": [
                    f.fieldname for f in member_meta.fields if "expense" in f.fieldname.lower()
                ],
            }

    except Exception as e:
        return {"status": "ERROR", "message": str(e)}
