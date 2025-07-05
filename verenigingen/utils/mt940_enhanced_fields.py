"""
Enhanced MT940 Import: Custom Fields for Bank Transaction DocType

This module adds custom fields to the standard ERPNext Bank Transaction doctype
to store enhanced SEPA and MT940 data extracted from Dutch bank files.

Based on analysis of the Banking app's sophisticated MT940 implementation.
"""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def get_enhanced_mt940_custom_fields():
    """
    Define custom fields for enhanced MT940 data storage in Bank Transaction.

    These fields store additional SEPA and banking data that's available in MT940
    files but not captured by standard ERPNext Bank Transaction fields.
    """

    custom_fields = {
        "Bank Transaction": [
            {
                "fieldname": "enhanced_mt940_section",
                "fieldtype": "Section Break",
                "label": "Enhanced MT940 Data",
                "description": "Additional SEPA and banking data from MT940 import",
                "collapsible": 1,
                "collapsible_depends_on": "eval:doc.transaction_id",
                "insert_after": "bank_party_iban",
            },
            {
                "fieldname": "booking_key",
                "fieldtype": "Data",
                "label": "Booking Key",
                "length": 10,
                "description": "Bank-specific transaction code (e.g., 005=Transfer, 186=Direct Debit)",
                "insert_after": "enhanced_mt940_section",
                "read_only": 1,
            },
            {
                "fieldname": "mandate_reference",
                "fieldtype": "Data",
                "label": "SEPA Mandate Reference",
                "length": 35,
                "description": "SEPA Direct Debit Mandate Reference (MREF)",
                "insert_after": "booking_key",
                "read_only": 1,
            },
            {
                "fieldname": "column_break_mt940_1",
                "fieldtype": "Column Break",
                "insert_after": "mandate_reference",
            },
            {
                "fieldname": "creditor_reference",
                "fieldtype": "Data",
                "label": "Creditor Reference",
                "length": 35,
                "description": "SEPA Creditor Reference (CRED)",
                "insert_after": "column_break_mt940_1",
                "read_only": 1,
            },
            {
                "fieldname": "bank_reference_mt940",
                "fieldtype": "Data",
                "label": "Bank Reference",
                "length": 20,
                "description": "Bank's internal reference number",
                "insert_after": "creditor_reference",
                "read_only": 1,
            },
            {
                "fieldname": "enhanced_transaction_type",
                "fieldtype": "Data",
                "label": "Enhanced Transaction Type",
                "length": 50,
                "description": "Detailed transaction type from booking_text or Dutch banking codes",
                "insert_after": "bank_reference_mt940",
                "read_only": 1,
            },
            {
                "fieldname": "sepa_purpose_code",
                "fieldtype": "Data",
                "label": "SEPA Purpose Code",
                "length": 4,
                "description": "SEPA transaction purpose code (e.g., SALA, PENS, GOVT)",
                "insert_after": "enhanced_transaction_type",
                "read_only": 1,
            },
        ]
    }

    return custom_fields


@frappe.whitelist()
def create_enhanced_mt940_fields():
    """
    Create custom fields for enhanced MT940 data storage.

    This function can be called to add the custom fields to Bank Transaction doctype.
    """
    try:
        custom_fields = get_enhanced_mt940_custom_fields()
        create_custom_fields(custom_fields)

        frappe.msgprint(
            _("Enhanced MT940 custom fields created successfully for Bank Transaction doctype"),
            title=_("Custom Fields Created"),
            indicator="green",
        )

        return {
            "success": True,
            "message": "Enhanced MT940 custom fields created successfully",
            "fields_created": len(custom_fields["Bank Transaction"]),
        }

    except Exception as e:
        frappe.log_error(f"Error creating enhanced MT940 fields: {str(e)}", "MT940 Enhanced Fields")
        frappe.throw(
            _("Failed to create enhanced MT940 fields: {0}").format(str(e)), title=_("Field Creation Error")
        )


@frappe.whitelist()
def remove_enhanced_mt940_fields():
    """
    Remove custom fields for enhanced MT940 data.

    This function can be used to clean up the custom fields if needed.
    """
    try:
        custom_fields = get_enhanced_mt940_custom_fields()
        field_names = [field["fieldname"] for field in custom_fields["Bank Transaction"]]

        for fieldname in field_names:
            if frappe.db.exists("Custom Field", {"dt": "Bank Transaction", "fieldname": fieldname}):
                frappe.delete_doc("Custom Field", {"dt": "Bank Transaction", "fieldname": fieldname})

        frappe.msgprint(
            _("Enhanced MT940 custom fields removed successfully"),
            title=_("Custom Fields Removed"),
            indicator="orange",
        )

        return {
            "success": True,
            "message": "Enhanced MT940 custom fields removed successfully",
            "fields_removed": len(field_names),
        }

    except Exception as e:
        frappe.log_error(f"Error removing enhanced MT940 fields: {str(e)}", "MT940 Enhanced Fields")
        frappe.throw(
            _("Failed to remove enhanced MT940 fields: {0}").format(str(e)), title=_("Field Removal Error")
        )


def populate_enhanced_mt940_fields(bank_transaction_doc, enhanced_data):
    """
    Populate enhanced MT940 fields in a Bank Transaction document.

    Args:
        bank_transaction_doc: Bank Transaction document
        enhanced_data: Dictionary with enhanced MT940 data
    """
    if not enhanced_data:
        return

    # Map enhanced data to custom fields
    field_mapping = {
        "booking_key": enhanced_data.get("booking_key", ""),
        "mandate_reference": enhanced_data.get("mandate_reference", ""),
        "creditor_reference": enhanced_data.get("creditor_reference", ""),
        "bank_reference_mt940": enhanced_data.get("bank_reference", ""),
        "enhanced_transaction_type": enhanced_data.get("enhanced_transaction_type", ""),
        "sepa_purpose_code": enhanced_data.get("sepa_purpose_code", ""),
    }

    # Set fields if they exist in the doctype
    for fieldname, value in field_mapping.items():
        if hasattr(bank_transaction_doc, fieldname) and value:
            setattr(bank_transaction_doc, fieldname, value)


@frappe.whitelist()
def get_field_creation_status():
    """
    Check if enhanced MT940 fields have been created.

    Returns:
        dict: Status of field creation
    """
    try:
        custom_fields = get_enhanced_mt940_custom_fields()
        field_names = [field["fieldname"] for field in custom_fields["Bank Transaction"]]

        existing_fields = []
        missing_fields = []

        for fieldname in field_names:
            if frappe.db.exists("Custom Field", {"dt": "Bank Transaction", "fieldname": fieldname}):
                existing_fields.append(fieldname)
            else:
                missing_fields.append(fieldname)

        return {
            "success": True,
            "total_fields": len(field_names),
            "existing_fields": len(existing_fields),
            "missing_fields": len(missing_fields),
            "existing_field_list": existing_fields,
            "missing_field_list": missing_fields,
            "all_created": len(missing_fields) == 0,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


# Hooks integration for automatic field creation
def on_app_install():
    """
    Hook function to create enhanced MT940 fields when app is installed.
    """
    try:
        create_enhanced_mt940_fields()
        frappe.logger().info("Enhanced MT940 fields created during app installation")
    except Exception as e:
        frappe.logger().error(f"Failed to create enhanced MT940 fields during installation: {str(e)}")


def validate_enhanced_fields_exist():
    """
    Validate that enhanced MT940 fields exist before using them.

    Returns:
        bool: True if all fields exist, False otherwise
    """
    status = get_field_creation_status()
    return status.get("all_created", False)
