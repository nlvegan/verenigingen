"""
Custom fields for SEPA reconciliation integration
"""

import frappe


def create_sepa_custom_fields():
    """Create custom fields for Bank Transaction and related doctypes"""

    # Custom fields for Bank Transaction
    bank_transaction_fields = [
        {
            "fieldname": "custom_sepa_batch",
            "label": "SEPA Batch",
            "fieldtype": "Link",
            "options": "SEPA Direct Debit Batch",
            "insert_after": "bank_account",
            "read_only": 0,
            "description": "Related SEPA Direct Debit Batch",
        },
        {
            "fieldname": "custom_processing_status",
            "label": "Processing Status",
            "fieldtype": "Select",
            "options": "\nSEPA Identified\nFully Reconciled\nPartial - Manual Review Required\nExcess - Manual Review Required\nManually Reconciled\nReturn Processed",
            "insert_after": "custom_sepa_batch",
            "read_only": 0,
            "description": "SEPA processing status",
        },
        {
            "fieldname": "custom_manual_review_task",
            "label": "Manual Review Task",
            "fieldtype": "Link",
            "options": "ToDo",
            "insert_after": "custom_processing_status",
            "read_only": 1,
            "description": "Related manual review task",
        },
    ]

    # Custom fields for Payment Entry
    payment_entry_fields = [
        {
            "fieldname": "custom_bank_transaction",
            "label": "Bank Transaction",
            "fieldtype": "Link",
            "options": "Bank Transaction",
            "insert_after": "reference_date",
            "read_only": 0,
            "description": "Related bank transaction",
        },
        {
            "fieldname": "custom_sepa_batch",
            "label": "SEPA Batch",
            "fieldtype": "Link",
            "options": "SEPA Direct Debit Batch",
            "insert_after": "custom_bank_transaction",
            "read_only": 0,
            "description": "Related SEPA batch",
        },
        {
            "fieldname": "custom_sepa_batch_item",
            "label": "SEPA Batch Item",
            "fieldtype": "Data",
            "insert_after": "custom_sepa_batch",
            "read_only": 0,
            "description": "Related SEPA batch item reference",
        },
        {
            "fieldname": "custom_manual_reconciliation",
            "label": "Manual Reconciliation",
            "fieldtype": "Check",
            "insert_after": "custom_sepa_batch_item",
            "read_only": 0,
            "default": 0,
            "description": "Manually reconciled payment",
        },
        {
            "fieldname": "custom_original_payment",
            "label": "Original Payment",
            "fieldtype": "Link",
            "options": "Payment Entry",
            "insert_after": "custom_manual_reconciliation",
            "read_only": 0,
            "description": "Original payment being reversed",
        },
        {
            "fieldname": "custom_return_reason",
            "label": "Return Reason",
            "fieldtype": "Data",
            "insert_after": "custom_original_payment",
            "read_only": 0,
            "description": "Reason for payment return",
        },
    ]

    # Custom fields for SEPA Direct Debit Batch
    direct_debit_batch_fields = [
        {
            "fieldname": "custom_reconciliation_status",
            "label": "Reconciliation Status",
            "fieldtype": "Select",
            "options": "\nPending\nFully Reconciled\nPartially Reconciled\nManual Review Required\nReturns Processed",
            "insert_after": "status",
            "read_only": 0,
            "description": "Overall reconciliation status",
        },
        {
            "fieldname": "custom_related_bank_transactions",
            "label": "Related Bank Transactions",
            "fieldtype": "Long Text",
            "insert_after": "custom_reconciliation_status",
            "read_only": 0,
            "description": "Bank transaction references related to this batch",
        },
    ]

    # Create the custom fields
    create_custom_fields("Bank Transaction", bank_transaction_fields)
    create_custom_fields("Payment Entry", payment_entry_fields)
    create_custom_fields("SEPA Direct Debit Batch", direct_debit_batch_fields)


def create_custom_fields(doctype, fields):
    """Create custom fields for a specific doctype"""

    for field in fields:
        # Check if field already exists
        if not frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": field["fieldname"]}):
            custom_field = frappe.get_doc(
                {
                    "doctype": "Custom Field",
                    "dt": doctype,
                    "fieldname": field["fieldname"],
                    "label": field["label"],
                    "fieldtype": field["fieldtype"],
                    "options": field.get("options", ""),
                    "insert_after": field["insert_after"],
                    "read_only": field.get("read_only", 0),
                    "default": field.get("default", ""),
                    "description": field.get("description", ""),
                }
            )
            custom_field.insert()
            print(f"Created custom field: {doctype}.{field['fieldname']}")
        else:
            print(f"Custom field already exists: {doctype}.{field['fieldname']}")


def create_sepa_bank_transaction_link_doctype():
    """Create child table doctype for linking bank transactions to SEPA batches"""

    doctype_name = "SEPA Bank Transaction Link"

    # Check if doctype already exists
    if frappe.db.exists("DocType", doctype_name):
        print(f"DocType {doctype_name} already exists")
        return

    # Create the child table doctype
    doctype = frappe.get_doc(
        {
            "doctype": "DocType",
            "name": doctype_name,
            "module": "Verenigingen",
            "istable": 1,  # Child table
            "fields": [
                {
                    "fieldname": "bank_transaction",
                    "label": "Bank Transaction",
                    "fieldtype": "Link",
                    "options": "Bank Transaction",
                    "in_list_view": 1,
                    "reqd": 1,
                },
                {
                    "fieldname": "transaction_date",
                    "label": "Transaction Date",
                    "fieldtype": "Date",
                    "in_list_view": 1,
                    "fetch_from": "bank_transaction.date",
                },
                {
                    "fieldname": "amount",
                    "label": "Amount",
                    "fieldtype": "Currency",
                    "in_list_view": 1,
                    "fetch_from": "bank_transaction.deposit",
                },
                {
                    "fieldname": "processing_status",
                    "label": "Processing Status",
                    "fieldtype": "Data",
                    "in_list_view": 1,
                    "fetch_from": "bank_transaction.custom_processing_status",
                },
                {
                    "fieldname": "description",
                    "label": "Description",
                    "fieldtype": "Data",
                    "fetch_from": "bank_transaction.description",
                },
            ],
        }
    )

    doctype.insert()
    print(f"Created DocType: {doctype_name}")


@frappe.whitelist()
def setup_sepa_custom_fields():
    """Setup all SEPA custom fields - can be called via API"""
    try:
        create_sepa_custom_fields()
        frappe.db.commit()
        return {"success": True, "message": "SEPA custom fields created successfully"}
    except Exception as e:
        frappe.log_error(f"Error creating SEPA custom fields: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def create_direct_debit_fields_only():
    """Create only SEPA Direct Debit Batch custom fields"""
    try:
        fields = [
            {
                "fieldname": "custom_reconciliation_status",
                "label": "Reconciliation Status",
                "fieldtype": "Select",
                "options": "\nPending\nFully Reconciled\nPartially Reconciled\nManual Review Required\nReturns Processed",
                "insert_after": "status",
                "read_only": 0,
                "description": "Overall reconciliation status",
            },
            {
                "fieldname": "custom_related_bank_transactions",
                "label": "Related Bank Transactions",
                "fieldtype": "Long Text",
                "insert_after": "custom_reconciliation_status",
                "read_only": 0,
                "description": "Bank transaction references related to this batch",
            },
        ]

        for field in fields:
            existing = frappe.db.exists(
                "Custom Field", {"dt": "SEPA Direct Debit Batch", "fieldname": field["fieldname"]}
            )

            if not existing:
                custom_field = frappe.get_doc(
                    {
                        "doctype": "Custom Field",
                        "dt": "SEPA Direct Debit Batch",
                        "fieldname": field["fieldname"],
                        "label": field["label"],
                        "fieldtype": field["fieldtype"],
                        "options": field.get("options", ""),
                        "insert_after": field["insert_after"],
                        "read_only": field.get("read_only", 0),
                        "description": field.get("description", ""),
                    }
                )
                custom_field.insert()

        frappe.db.commit()
        return {"success": True, "message": "SEPA Direct Debit Batch fields created"}

    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    frappe.init()
    frappe.connect()
    create_sepa_custom_fields()
