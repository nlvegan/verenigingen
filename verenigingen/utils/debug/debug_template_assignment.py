import frappe


@frappe.whitelist()
def debug_schedule_creation_history():
    """Investigate why Schedule-Assoc-Member-2025-07-2910-Daily Access-001 was created with wrong template"""

    schedule_name = "Schedule-Assoc-Member-2025-07-2910-Daily Access-001"
    member_name = "Assoc-Member-2025-07-2910"

    # Get schedule details
    schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)

    result = {
        "schedule_info": {
            "name": schedule.name,
            "creation": schedule.creation,
            "owner": schedule.owner,
            "template_reference": schedule.template_reference,
            "membership_type": schedule.membership_type,
            "member": schedule.member,
        }
    }

    # Get member's membership history
    memberships = frappe.get_all(
        "Membership",
        filters={"member": member_name},
        fields=["name", "creation", "status", "membership_type", "docstatus", "owner"],
        order_by="creation desc",
    )
    result["member_memberships"] = memberships

    # Check what the Daily Access membership type was linked to at different times
    # Get version history for Daily Access membership type
    try:
        versions = frappe.get_all(
            "Version",
            filters={"ref_doctype": "Membership Type", "docname": "Daily Access"},
            fields=["creation", "owner", "data"],
            order_by="creation desc",
            limit=10,
        )
        result["membership_type_versions"] = []
        for version in versions:
            import json

            try:
                version_data = json.loads(version.data)
                if "changed" in version_data:
                    for change in version_data["changed"]:
                        if change[0] == "dues_schedule_template":
                            result["membership_type_versions"].append(
                                {
                                    "creation": version.creation,
                                    "owner": version.owner,
                                    "field": change[0],
                                    "old_value": change[1],
                                    "new_value": change[2],
                                }
                            )
            except:
                pass
    except Exception as e:
        result["membership_type_versions"] = {"error": str(e)}

    # Check if there are any auto-creation logs or rules that might explain this
    # Look for templates that match the membership type name
    matching_templates = frappe.get_all(
        "Membership Dues Schedule",
        filters={"is_template": 1, "membership_type": "Daily Access"},
        fields=["name", "creation", "membership_type", "minimum_amount", "suggested_amount"],
    )
    result["templates_for_daily_access"] = matching_templates

    return result


@frappe.whitelist()
def check_template_creation_logic():
    """Check how templates are selected during dues schedule creation"""

    # Look at the create_from_template method logic
    # Check if there's auto-creation of templates

    # Find all templates that contain "Daily Access" in name
    daily_access_templates = frappe.get_all(
        "Membership Dues Schedule",
        filters={"is_template": 1, "name": ["like", "%Daily Access%"]},
        fields=["name", "creation", "membership_type", "owner"],
    )

    # Check for any automatic template creation logic
    result = {"daily_access_templates": daily_access_templates}

    # Check if there's a pattern in template naming that might cause confusion
    all_templates = frappe.get_all(
        "Membership Dues Schedule",
        filters={"is_template": 1},
        fields=["name", "membership_type", "creation"],
        order_by="creation desc",
    )

    # Group by membership type to see patterns
    by_type = {}
    for template in all_templates:
        if template.membership_type not in by_type:
            by_type[template.membership_type] = []
        by_type[template.membership_type].append(template)

    result["templates_by_membership_type"] = by_type

    return result
