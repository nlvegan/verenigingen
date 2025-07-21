#!/usr/bin/env python3

import frappe


@frappe.whitelist()
def debug_current_schedule_naming():
    """Debug how the current schedule was named"""

    member_name = "Assoc-Member-2025-07-0025"
    schedule_name = f"Auto-{member_name}-xehYos"

    try:
        schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)

        result = {
            "schedule_name": schedule.name,
            "schedule_name_field": schedule.schedule_name,
            "membership_type": schedule.membership_type,
            "template_reference": schedule.get("template_reference"),
            "is_template": schedule.is_template,
            "member": schedule.member,
            "created": str(schedule.creation),
            "created_by": schedule.owner,
            "modified": str(schedule.modified),
            "modified_by": schedule.modified_by,
            "version_log": [],
        }

        # Check if there are any version logs
        version_docs = frappe.get_all(
            "Version",
            filters={"docname": schedule_name, "ref_doctype": "Membership Dues Schedule"},
            fields=["name", "creation", "owner", "data"],
            order_by="creation desc",
        )

        for version in version_docs[:3]:  # Get last 3 versions
            result["version_log"].append(
                {
                    "creation": str(version.creation),
                    "owner": version.owner,
                    "has_data": bool(version.get("data")),
                }
            )

        return result

    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
def test_new_naming_pattern():
    """Test what the new naming pattern would look like"""

    member_name = "Assoc-Member-2025-07-0025"

    try:
        # Get member and template info
        member = frappe.get_doc("Member", member_name)

        # Get active membership
        membership = frappe.db.get_value(
            "Membership",
            {"member": member_name, "status": "Active", "docstatus": 1},
            ["name", "membership_type"],
            as_dict=True,
        )

        if not membership:
            return {"error": "No active membership found"}

        membership_type = membership.membership_type

        # Find next sequence number for this member-template combination
        existing_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name, "membership_type": membership_type, "is_template": 0},
            fields=["name", "schedule_name"],
            order_by="creation desc",
        )

        sequence_number = len(existing_schedules) + 1

        # Generate new naming pattern
        new_name = f"{member_name}-{membership_type}-{sequence_number:03d}"

        result = {
            "member_name": member_name,
            "membership_type": membership_type,
            "existing_schedules_count": len(existing_schedules),
            "next_sequence": sequence_number,
            "new_naming_pattern": new_name,
            "existing_schedules": [
                {"name": s.name, "schedule_name": s.schedule_name} for s in existing_schedules
            ],
        }

        return result

    except Exception as e:
        return {"error": str(e)}
