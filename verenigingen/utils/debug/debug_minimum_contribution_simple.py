import frappe


@frappe.whitelist()
def debug_minimum_contribution_simple():
    """Simple debug for minimum contribution issue"""

    schedule_name = "Schedule-Assoc-Member-2025-07-2910-Daily Access-001"

    # Check if schedule exists
    schedule_exists = frappe.db.exists("Membership Dues Schedule", schedule_name)

    if not schedule_exists:
        # Let's find what schedules exist for this member
        member_name = "Assoc-Member-2025-07-2910"
        member_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name},
            fields=["name", "minimum_amount", "suggested_amount", "dues_rate", "membership_type"],
        )

        return {
            "schedule_exists": False,
            "searched_name": schedule_name,
            "member_schedules": member_schedules,
            "member": member_name,
        }

    # If schedule exists, get details
    schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)

    return {
        "schedule_exists": True,
        "schedule": {
            "name": schedule.name,
            "minimum_amount": schedule.minimum_amount,
            "suggested_amount": schedule.suggested_amount,
            "dues_rate": schedule.dues_rate,
            "membership_type": schedule.membership_type,
            "member": schedule.member,
            "template_reference": schedule.template_reference,
            "contribution_mode": schedule.contribution_mode,
        },
    }


@frappe.whitelist()
def check_daily_access_membership_type():
    """Check Daily Access membership type settings"""

    try:
        membership_type = frappe.get_doc("Membership Type", "Daily Access")
        return {
            "found": True,
            "name": membership_type.name,
            "amount": membership_type.minimum_amount,
            "dues_schedule_template": membership_type.dues_schedule_template,
            "billing_period": membership_type.billing_period,
        }
    except frappe.DoesNotExistError:
        return {"found": False, "error": "Daily Access membership type not found"}
