"""
Create custom fields for E-Boekhouden migration tracking
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def create_eboekhouden_tracking_fields():
    """Create custom fields for tracking E-Boekhouden data"""

    custom_fields = {
        "Sales Invoice": [
            {
                "fieldname": "eboekhouden_invoice_number",
                "label": "E-Boekhouden Invoice Number",
                "fieldtype": "Data",
                "insert_after": "naming_series",
                "unique": 1,
                "allow_on_submit": 1,
                "module": "E-Boekhouden",
            },
            {
                "fieldname": "eboekhouden_mutation_nr",
                "label": "E-Boekhouden Mutation Nr",
                "fieldtype": "Data",
                "insert_after": "cost_center",
                "unique": 1,
                "allow_on_submit": 1,
                "module": "E-Boekhouden",
            },
        ],
        "Purchase Invoice": [
            {
                "fieldname": "eboekhouden_invoice_number",
                "label": "E-Boekhouden Invoice Number",
                "fieldtype": "Data",
                "insert_after": "naming_series",
                "unique": 1,
                "allow_on_submit": 1,
                "module": "E-Boekhouden",
            },
            {
                "fieldname": "eboekhouden_mutation_nr",
                "label": "E-Boekhouden Mutation Nr",
                "fieldtype": "Data",
                "insert_after": "cost_center",
                "unique": 1,
                "allow_on_submit": 1,
                "module": "E-Boekhouden",
            },
        ],
        "Customer": [
            {
                "fieldname": "eboekhouden_relation_code",
                "label": "E-Boekhouden Relation Code",
                "fieldtype": "Data",
                "insert_after": "customer_name",
                "unique": 1,
                "module": "E-Boekhouden",
            }
        ],
        "Supplier": [
            {
                "fieldname": "eboekhouden_relation_code",
                "label": "E-Boekhouden Relation Code",
                "fieldtype": "Data",
                "insert_after": "supplier_name",
                "unique": 1,
                "module": "E-Boekhouden",
            }
        ],
        "Journal Entry": [
            {
                "fieldname": "eboekhouden_mutation_nr",
                "label": "E-Boekhouden Mutation Number",
                "fieldtype": "Data",
                "insert_after": "naming_series",
                "unique": 1,
                "allow_on_submit": 1,
                "module": "E-Boekhouden",
            },
            {
                "fieldname": "eboekhouden_relation_code",
                "label": "E-Boekhouden Relation Code",
                "fieldtype": "Data",
                "insert_after": "eboekhouden_mutation_nr",
                "allow_on_submit": 1,
            },
            {
                "fieldname": "eboekhouden_invoice_number",
                "label": "E-Boekhouden Invoice Number",
                "fieldtype": "Data",
                "insert_after": "eboekhouden_relation_code",
                "allow_on_submit": 1,
            },
            {
                "fieldname": "custom_eboekhouden_main_ledger_id",
                "label": "E-Boekhouden Main Ledger ID",
                "fieldtype": "Data",
                "insert_after": "eboekhouden_invoice_number",
                "allow_on_submit": 1,
            },
            {
                "fieldname": "eboekhouden_mutation_type",
                "label": "E-Boekhouden Mutation Type",
                "fieldtype": "Select",
                "options": "\n0\n1\n2\n3\n4\n5\n6\n7",
                "insert_after": "custom_eboekhouden_main_ledger_id",
                "allow_on_submit": 1,
                "description": "0=Opening, 1=PurchInv, 2=SalesInv, 3=CustPayment, 4=SuppPayment, 5=MoneyReceived, 6=MoneySent, 7=Memorial",
            },
        ],
        "Payment Entry": [
            {
                "fieldname": "eboekhouden_mutation_nr",
                "label": "E-Boekhouden Mutation Number",
                "fieldtype": "Data",
                "insert_after": "naming_series",
                "unique": 1,
                "allow_on_submit": 1,
            },
            {
                "fieldname": "eboekhouden_mutation_type",
                "label": "E-Boekhouden Mutation Type",
                "fieldtype": "Select",
                "options": "\n0\n1\n2\n3\n4\n5\n6\n7",
                "insert_after": "eboekhouden_mutation_nr",
                "allow_on_submit": 1,
                "description": "0=Opening, 1=PurchInv, 2=SalesInv, 3=CustPayment, 4=SuppPayment, 5=MoneyReceived, 6=MoneySent, 7=Memorial",
            },
        ],
    }

    try:
        create_custom_fields(custom_fields, ignore_validate=True)
        frappe.db.commit()
        return {"success": True, "message": "Custom fields created successfully"}
    except Exception as e:
        frappe.log_error(f"Failed to create custom fields: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def ensure_eboekhouden_fields():
    """Ensure all E-Boekhouden tracking fields exist"""
    return create_eboekhouden_tracking_fields()


@frappe.whitelist()
def update_mutation_type_field_options():
    """Update E-Boekhouden Mutation Type field to include empty option"""
    try:
        updates_made = []

        # Update the custom field for Payment Entry
        try:
            custom_field_pe = frappe.get_doc(
                "Custom Field", {"dt": "Payment Entry", "fieldname": "eboekhouden_mutation_type"}
            )
            if custom_field_pe:
                custom_field_pe.options = "\n0\n1\n2\n3\n4\n5\n6\n7"
                custom_field_pe.save()
                updates_made.append("Payment Entry field updated")
        except frappe.DoesNotExistError:
            updates_made.append("Payment Entry field not found")

        # Update the custom field for Journal Entry
        try:
            custom_field_je = frappe.get_doc(
                "Custom Field", {"dt": "Journal Entry", "fieldname": "eboekhouden_mutation_type"}
            )
            if custom_field_je:
                custom_field_je.options = "\n0\n1\n2\n3\n4\n5\n6\n7"
                custom_field_je.save()
                updates_made.append("Journal Entry field updated")
        except frappe.DoesNotExistError:
            updates_made.append("Journal Entry field not found")

        frappe.db.commit()

        return {
            "success": True,
            "message": "E-Boekhouden Mutation Type fields updated to include empty option",
            "updates": updates_made,
        }

    except Exception as e:
        frappe.log_error(f"Error updating mutation type field: {str(e)}")
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    result = create_eboekhouden_tracking_fields()
    print(result)
