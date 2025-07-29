#!/usr/bin/env python3
"""Debug API for field validation"""

import frappe


@frappe.whitelist()
def check_expense_claim_fields():
    """Check actual field names in Expense Claim DocType"""
    try:
        # Check if DocType exists
        expense_claim_doc = frappe.get_doc("DocType", "Expense Claim")

        # Get field names
        field_names = [field.fieldname for field in expense_claim_doc.fields if field.fieldname]

        # Look for amount-related fields
        amount_fields = [f for f in field_names if "amount" in f.lower() or "total" in f.lower()]

        result = {
            "doctype": "Expense Claim",
            "amount_fields": amount_fields,
            "has_total_claimed_amount": "total_claimed_amount" in field_names,
            "all_fields": field_names,
        }

        return result

    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
def check_member_fields():
    """Check actual field names in Member DocType"""
    try:
        member_doc = frappe.get_doc("DocType", "Member")
        field_names = [field.fieldname for field in member_doc.fields if field.fieldname]

        fee_fields = [f for f in field_names if "fee" in f.lower()]

        result = {
            "doctype": "Member",
            "fee_fields": fee_fields,
            "has_fee_override_by": "fee_override_by" in field_names,
            "has_fee_override_reason": "fee_override_reason" in field_names,
            "all_fields": field_names[:50],  # First 50 fields only
        }

        return result

    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
def check_volunteer_expense_fields():
    """Check actual field names in Volunteer Expense DocType"""
    try:
        volunteer_expense_doc = frappe.get_doc("DocType", "Volunteer Expense")
        field_names = [field.fieldname for field in volunteer_expense_doc.fields if field.fieldname]

        result = {
            "doctype": "Volunteer Expense",
            "has_approval_status": "approval_status" in field_names,
            "has_status": "status" in field_names,
            "has_total_claimed_amount": "total_claimed_amount" in field_names,
            "status_field_options": None,
            "all_fields": field_names,
        }

        # Get status field options
        for field in volunteer_expense_doc.fields:
            if field.fieldname == "status":
                result["status_field_options"] = field.options
                break

        return result

    except Exception as e:
        return {"error": str(e)}
