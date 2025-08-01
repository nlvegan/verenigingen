#!/usr/bin/env python
"""Debug HTML field rendering issue"""

import frappe
from frappe import _


@frappe.whitelist()
def test_html_field():
    """Test HTML field rendering in Member doctype"""
    # Get a member with address
    member_name = frappe.db.get_value("Member", {"primary_address": ["!=", ""]}, "name")

    if not member_name:
        return {"error": "No member with address found"}

    member = frappe.get_doc("Member", member_name)

    # Get other members at address
    other_members = member.get_other_members_at_address()

    # Check current field values BEFORE calling onload
    result = {
        "member": member.name,
        "full_name": member.full_name,
        "primary_address": member.primary_address,
        "other_members_count": len(other_members) if isinstance(other_members, list) else 0,
        "other_members_data": other_members,
        "field_values_before_onload": {
            "address_display": bool(getattr(member, "address_display", None)),
            "current_chapter_display": bool(getattr(member, "current_chapter_display", None)),
            "other_members_at_address": bool(getattr(member, "other_members_at_address", None)),
        },
        "field_content_before": {
            "other_members_at_address": getattr(member, "other_members_at_address", "")[:200]
            if getattr(member, "other_members_at_address", "")
            else None
        },
    }

    # Call onload to trigger the field population
    member.onload()

    # Check field values AFTER calling onload
    result["field_values_after_onload"] = {
        "address_display": bool(getattr(member, "address_display", None)),
        "current_chapter_display": bool(getattr(member, "current_chapter_display", None)),
        "other_members_at_address": bool(getattr(member, "other_members_at_address", None)),
    }

    result["field_content_after"] = {
        "other_members_at_address": getattr(member, "other_members_at_address", "")[:200]
        if getattr(member, "other_members_at_address", "")
        else None
    }

    # Test the update method directly
    member.update_other_members_at_address_display()

    result["field_values_after_update"] = {
        "other_members_at_address": bool(getattr(member, "other_members_at_address", None)),
    }

    result["field_content_after_update"] = {
        "other_members_at_address": getattr(member, "other_members_at_address", "")[:200]
        if getattr(member, "other_members_at_address", "")
        else None
    }

    return result


@frappe.whitelist()
def check_field_permissions():
    """Check if there are any permission issues with HTML fields"""
    meta = frappe.get_meta("Member")

    html_fields = []
    for field in meta.fields:
        if field.fieldtype == "HTML":
            html_fields.append(
                {
                    "fieldname": field.fieldname,
                    "label": field.label,
                    "read_only": field.read_only,
                    "hidden": field.hidden,
                    "permlevel": field.permlevel,
                    "depends_on": field.depends_on,
                    "section": field.parent_field if hasattr(field, "parent_field") else None,
                }
            )

    return {"html_fields": html_fields, "user": frappe.session.user, "roles": frappe.get_roles()}
