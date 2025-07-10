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
            }
        ],
        "Purchase Invoice": [
            {
                "fieldname": "eboekhouden_invoice_number",
                "label": "E-Boekhouden Invoice Number",
                "fieldtype": "Data",
                "insert_after": "naming_series",
                "unique": 1,
                "allow_on_submit": 1,
            }
        ],
        "Customer": [
            {
                "fieldname": "eboekhouden_relation_code",
                "label": "E-Boekhouden Relation Code",
                "fieldtype": "Data",
                "insert_after": "customer_name",
                "unique": 1,
            }
        ],
        "Supplier": [
            {
                "fieldname": "eboekhouden_relation_code",
                "label": "E-Boekhouden Relation Code",
                "fieldtype": "Data",
                "insert_after": "supplier_name",
                "unique": 1,
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
                "fieldname": "eboekhouden_main_ledger_id",
                "label": "E-Boekhouden Main Ledger ID",
                "fieldtype": "Data",
                "insert_after": "eboekhouden_invoice_number",
                "allow_on_submit": 1,
            },
            {
                "fieldname": "eboekhouden_mutation_type",
                "label": "E-Boekhouden Mutation Type",
                "fieldtype": "Select",
                "options": "0\n1\n2\n3\n4\n5\n6\n7",
                "insert_after": "eboekhouden_main_ledger_id",
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
                "options": "0\n1\n2\n3\n4\n5\n6\n7",
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


if __name__ == "__main__":
    result = create_eboekhouden_tracking_fields()
    print(result)
