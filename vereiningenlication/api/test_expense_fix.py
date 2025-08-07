import frappe


@frappe.whitelist()
def test_expense_history_fix():
    """Test the expense history duplicate prevention fix"""

    try:
        # Find a volunteer with member record and employee_id
        volunteers = frappe.db.sql(
            """
            SELECT v.name, v.volunteer_name, v.member, v.employee_id
            FROM `tabVolunteer` v
            WHERE v.member IS NOT NULL
            AND v.employee_id IS NOT NULL
            AND v.status = 'Active'
            LIMIT 3
        """,
            as_dict=True,
        )

        results = {"status": "success", "volunteers_found": len(volunteers), "test_results": []}

        for volunteer in volunteers:
            # Get member document
            member_doc = frappe.get_doc("Member", volunteer.member)

            # Get expense claims for this volunteer
            expense_claims = frappe.get_all(
                "Expense Claim",
                filters={"employee": volunteer.employee_id},
                fields=["name", "status", "total_sanctioned_amount"],
                limit=1,
            )

            if not expense_claims:
                continue

            test_claim = expense_claims[0]

            # Count current history entries
            history_before = len(getattr(member_doc, "volunteer_expenses", []))

            # Call add_expense_to_history twice to test duplicate prevention
            member_doc.add_expense_to_history(test_claim.name)

            # Reload and count
            member_doc.reload()
            history_after_first = len(getattr(member_doc, "volunteer_expenses", []))

            # Call again (should not create duplicate)
            member_doc.add_expense_to_history(test_claim.name)

            # Reload and count
            member_doc.reload()
            history_after_second = len(getattr(member_doc, "volunteer_expenses", []))

            test_result = {
                "volunteer": volunteer.volunteer_name,
                "member": volunteer.member,
                "expense_claim": test_claim.name,
                "history_before": history_before,
                "history_after_first": history_after_first,
                "history_after_second": history_after_second,
                "duplicate_created": history_after_second > history_after_first,
                "fix_working": history_after_second == history_after_first,
            }

            results["test_results"].append(test_result)
            break  # Test just one volunteer

        return results

    except Exception as e:
        import traceback

        return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}
