import frappe


@frappe.whitelist()
def debug_membership_linking():
    """Debug why dues schedules aren't being linked to memberships"""

    # Let's look at one of the created personas
    member_name = "Assoc-Member-2025-07-3097"  # monthly_to_annual_mike

    # Get the member's membership
    memberships = frappe.get_all(
        "Membership", filters={"member": member_name}, fields=["name", "member", "status", "docstatus"]
    )

    # Get the member's dues schedules
    schedules = frappe.get_all(
        "Membership Dues Schedule",
        filters={"member": member_name},
        fields=["name", "member", "membership", "status"],
    )

    if schedules and memberships:
        schedule = frappe.get_doc("Membership Dues Schedule", schedules[0]["name"])
        membership = frappe.get_doc("Membership", memberships[0]["name"])

        # Try to manually link them
        original_membership = schedule.membership
        schedule.membership = membership.name

        try:
            schedule.save()

            # Reload to see if it persisted
            schedule.reload()
            new_membership = schedule.membership

            return {
                "member": member_name,
                "membership_name": membership.name,
                "schedule_name": schedule.name,
                "original_membership": original_membership,
                "attempted_membership": membership.name,
                "persisted_membership": new_membership,
                "linking_worked": bool(new_membership == membership.name),
                "membership_status": membership.status,
                "membership_docstatus": membership.docstatus,
                "schedule_status": schedule.status,
                "error": None,
            }

        except Exception as e:
            return {
                "member": member_name,
                "error": str(e),
                "linking_worked": False,
                "membership_name": membership.name,
                "schedule_name": schedule.name,
            }

    return {"error": "No member/schedule found", "memberships": memberships, "schedules": schedules}
