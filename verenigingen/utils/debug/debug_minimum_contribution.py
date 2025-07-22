import frappe


@frappe.whitelist()
def debug_minimum_contribution_issue():
    """Debug the minimum contribution requirement discrepancy"""

    # Check if the specific schedule exists
    schedule_name = "Schedule-Assoc-Member-2025-07-2910-Daily Access-001"

    # Get the dues schedule
    schedule = frappe.db.get_value(
        "Membership Dues Schedule",
        schedule_name,
        [
            "name",
            "minimum_amount",
            "suggested_amount",
            "dues_rate",
            "membership_type",
            "member",
            "template_reference",
        ],
        as_dict=True,
    )

    if not schedule:
        return {"error": f"Dues schedule {schedule_name} not found"}

    result = {"schedule_info": schedule}

    # Get membership type info
    if schedule.membership_type:
        membership_type = frappe.db.get_value(
            "Membership Type",
            schedule.membership_type,
            ["name", "amount", "dues_schedule_template", "minimum_amount", "suggested_amount"],
            as_dict=True,
        )
        result["membership_type"] = membership_type

        # If there's a template, get template info
        if membership_type and membership_type.dues_schedule_template:
            template = frappe.db.get_value(
                "Membership Dues Schedule",
                membership_type.dues_schedule_template,
                ["name", "minimum_amount", "suggested_amount", "dues_rate", "is_template"],
                as_dict=True,
            )
            result["template"] = template

    # Get member info
    if schedule.member:
        member = frappe.db.get_value(
            "Member", schedule.member, ["name", "member_id", "full_name"], as_dict=True
        )
        result["member"] = member

    # Check if there are validation rules or custom logic that might be enforcing 5€
    # Look for any validation logic in the membership dues schedule
    return result


@frappe.whitelist()
def check_contribution_validation_rules():
    """Check where the 5€ minimum might be coming from"""

    # Check if there are any contribution tiers or rules
    tiers = frappe.get_all(
        "Membership Tier", fields=["name", "tier_name", "minimum_amount", "suggested_amount"], limit=10
    )

    # Check contribution settings
    try:
        settings = frappe.get_single("Contribution Settings")
        settings_data = {
            "name": settings.name,
            "minimum_contribution": getattr(settings, "minimum_contribution", None),
            "default_minimum": getattr(settings, "default_minimum", None),
        }
    except:
        settings_data = {"error": "Contribution Settings not found"}

    # Check for any global minimums in Verenigingen Settings
    try:
        verenigingen_settings = frappe.get_single("Verenigingen Settings")
        verenigingen_data = {
            "name": verenigingen_settings.name,
            # Look for any minimum amount fields
        }

        # Get all fields from the settings
        meta = frappe.get_meta("Verenigingen Settings")
        for field in meta.fields:
            if "minimum" in field.fieldname.lower() or "amount" in field.fieldname.lower():
                verenigingen_data[field.fieldname] = getattr(verenigingen_settings, field.fieldname, None)

    except Exception as e:
        verenigingen_data = {"error": str(e)}

    return {
        "membership_tiers": tiers,
        "contribution_settings": settings_data,
        "verenigingen_settings": verenigingen_data,
    }
