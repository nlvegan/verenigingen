import frappe


@frappe.whitelist()
def debug_member_2910():
    """Debug member 2910 dues schedules"""
    member_name = "Assoc-Member-2025-07-2910"

    result = {"member_name": member_name, "schedules": [], "amendments": [], "error": None}

    try:
        # Check if member exists
        if not frappe.db.exists("Member", member_name):
            result["error"] = "Member not found"
            return result

        member = frappe.get_doc("Member", member_name)
        result["member_info"] = {
            "name": member.name,
            "full_name": f"{member.first_name} {member.last_name}",
            "email": member.email,
        }

        # Get dues schedules
        schedules = frappe.db.sql(
            """
            SELECT name, status, billing_frequency, amount
            FROM `tabMembership Dues Schedule`
            WHERE member = %s
        """,
            member_name,
            as_dict=True,
        )

        result["schedules"] = schedules
        result["schedule_count"] = len(schedules)

        # Get amendments
        amendments = frappe.db.sql(
            """
            SELECT name, status, amendment_type
            FROM `tabContribution Amendment Request`
            WHERE member = %s
        """,
            member_name,
            as_dict=True,
        )

        result["amendments"] = amendments
        result["amendment_count"] = len(amendments)

    except Exception as e:
        result["error"] = str(e)

    return result
