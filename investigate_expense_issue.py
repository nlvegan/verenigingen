#!/usr/bin/env python3

import frappe


def investigate_member_expenses():
    """Investigate why expense claims are not showing in member child table"""

    member_name = "Assoc-Member-2025-07-0030"

    try:
        # Get the member
        member = frappe.get_doc("Member", member_name)
        print(f"Member found: {member.full_name}")
        print(f"Employee: {member.employee}")

        # Check volunteer expenses child table
        print(f"Volunteer expenses count: {len(member.volunteer_expenses or [])}")
        if member.volunteer_expenses:
            for exp in member.volunteer_expenses:
                print(f"  - {exp.expense_claim}: {exp.total_sanctioned_amount} ({exp.status})")
        else:
            print("  No volunteer expenses in child table")

        # Find the volunteer record
        if member.employee:
            volunteer = frappe.db.get_value(
                "Volunteer", {"employee": member.employee}, ["name", "member"], as_dict=True
            )
            if volunteer:
                print(f"Volunteer: {volunteer.name}, linked to member: {volunteer.member}")

                # Find expense claims for this employee
                expense_claims = frappe.get_all(
                    "Expense Claim",
                    filters={"employee": member.employee},
                    fields=[
                        "name",
                        "status",
                        "approval_status",
                        "total_sanctioned_amount",
                        "posting_date",
                        "docstatus",
                    ],
                )

                print(f"Expense claims for employee {member.employee}: {len(expense_claims)}")
                for exp in expense_claims:
                    print(
                        f"  - {exp.name}: {exp.status}/{exp.approval_status}, Amount: {exp.total_sanctioned_amount}, Date: {exp.posting_date}, DocStatus: {exp.docstatus}"
                    )

                    # Check if we can manually add this expense
                    if exp.approval_status == "Approved" and exp.docstatus == 1:
                        print("    -> Should be in member history (approved and submitted)")
                        # Try to manually trigger the expense history update
                        try:
                            member.add_expense_to_history(exp.name)
                            print(f"    -> Manually added {exp.name} to history")
                        except Exception as e:
                            print(f"    -> Error adding manually: {e}")
            else:
                print("No volunteer record found for this employee")
        else:
            print("No employee linked to this member")

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    investigate_member_expenses()
