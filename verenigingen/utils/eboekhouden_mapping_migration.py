"""
Enhanced E-Boekhouden migration using account mappings
This replaces process_purchase_invoices to support creating Journal Entries based on mappings
"""

import frappe

from .eboekhouden_soap_migration import (
    get_account_by_code,
    get_expense_account_by_code,
    get_or_create_supplier,
    parse_date,
)


def process_purchase_invoices_with_mapping(mutations, company, cost_center, migration_doc):
    """
    Process FactuurOntvangen (purchase invoices) using account mappings
    Creates either Purchase Invoices or Journal Entries based on mapping configuration
    """
    from verenigingen.verenigingen.doctype.e_boekhouden_account_mapping.e_boekhouden_account_mapping import (
        get_mapping_for_mutation,
    )

    created_purchase_invoices = 0
    created_journal_entries = 0
    errors = []

    for mut in mutations:
        try:
            # Skip if already imported
            invoice_no = mut.get("Factuurnummer")
            if not invoice_no:
                continue

            # Check if already exists as either type
            if frappe.db.exists("Purchase Invoice", {"eboekhouden_invoice_number": invoice_no}):
                continue
            if frappe.db.exists("Journal Entry", {"eboekhouden_invoice_number": invoice_no}):
                continue

            # Determine document type using account mappings
            document_type = "Purchase Invoice"  # Default
            transaction_category = "General Expenses"
            mapping_name = None

            # Check each mutation line for account mapping
            for regel in mut.get("MutatieRegels", []):
                account_code = regel.get("TegenrekeningCode")
                if account_code:
                    mapping = get_mapping_for_mutation(account_code, mut.get("Omschrijving", ""))
                    if mapping and mapping.get("name"):
                        document_type = mapping["document_type"]
                        transaction_category = mapping["transaction_category"]
                        mapping_name = mapping["name"]

                        # Record usage
                        mapping_doc = frappe.get_doc("E-Boekhouden Account Mapping", mapping_name)
                        mapping_doc.record_usage(mut.get("Omschrijving", ""))

                        break  # Use first matching mapping

            # Process based on document type
            if document_type == "Journal Entry":
                result = create_journal_entry_from_mutation(mut, company, cost_center, transaction_category)
                if result["success"]:
                    created_journal_entries += 1
                else:
                    errors.append(result["error"])
            else:
                result = create_purchase_invoice_from_mutation(mut, company, cost_center)
                if result["success"]:
                    created_purchase_invoices += 1
                else:
                    errors.append(result["error"])

        except Exception as e:
            errors.append(f"Invoice {mut.get('Factuurnummer')}: {str(e)}")
            migration_doc.log_error(
                f"Failed to process invoice {invoice_no}: {str(e)}", "purchase_invoice", mut
            )

    return {
        "created": created_purchase_invoices + created_journal_entries,
        "created_purchase_invoices": created_purchase_invoices,
        "created_journal_entries": created_journal_entries,
        "errors": errors,
    }


def create_purchase_invoice_from_mutation(mut, company, cost_center):
    """Create a Purchase Invoice from mutation data"""
    try:
        # Parse mutation data
        posting_date = parse_date(mut.get("Datum"))
        supplier_code = mut.get("RelatieCode")
        description = mut.get("Omschrijving", "")
        invoice_no = mut.get("Factuurnummer")

        # Get or create supplier with relation data for meaningful names
        supplier = get_or_create_supplier(supplier_code, description, relation_data=None)

        # Create purchase invoice
        pi = frappe.new_doc("Purchase Invoice")
        pi.company = company
        pi.supplier = supplier
        pi.posting_date = posting_date
        pi.bill_date = posting_date
        pi.eboekhouden_invoice_number = invoice_no
        pi.remarks = description

        # Calculate and set due date
        try:
            payment_terms = int(mut.get("Betalingstermijn", 30))
        except (ValueError, TypeError):
            payment_terms = 30

        if payment_terms < 0:
            payment_terms = 0

        calculated_due_date = frappe.utils.add_days(posting_date, payment_terms)
        if frappe.utils.getdate(calculated_due_date) < frappe.utils.getdate(posting_date):
            pi.due_date = posting_date
        else:
            pi.due_date = calculated_due_date

        # Set the credit to account
        rekening_code = mut.get("Rekening")
        if rekening_code:
            credit_account = get_account_by_code(rekening_code, company)
            if credit_account:
                # Ensure it's marked as payable
                current_type = frappe.db.get_value("Account", credit_account, "account_type")
                if current_type != "Payable":
                    frappe.db.set_value("Account", credit_account, "account_type", "Payable")
                    frappe.db.commit()
                pi.credit_to = credit_account
            else:
                default_payable = frappe.db.get_value("Company", company, "default_payable_account")
                if default_payable:
                    pi.credit_to = default_payable
        else:
            default_payable = frappe.db.get_value("Company", company, "default_payable_account")
            if default_payable:
                pi.credit_to = default_payable

        pi.cost_center = cost_center

        # Add line items using smart tegenrekening mapping
        from verenigingen.utils.smart_tegenrekening_mapper import create_invoice_line_for_tegenrekening

        for regel in mut.get("MutatieRegels", []):
            amount = float(regel.get("BedragExclBTW", 0))
            if amount > 0:
                line_dict = create_invoice_line_for_tegenrekening(
                    tegenrekening_code=regel.get("TegenrekeningCode"),
                    amount=amount,
                    description=regel.get("Omschrijving", "") or mut.get("Omschrijving", ""),
                    transaction_type="purchase",
                )
                pi.append("items", line_dict)

        pi.insert(ignore_permissions=True)
        pi.submit()

        return {"success": True}

    except Exception as e:
        return {"success": False, "error": f"Purchase Invoice {mut.get('Factuurnummer')}: {str(e)}"}


def create_journal_entry_from_mutation(mut, company, cost_center, transaction_category):
    """Create a Journal Entry from mutation data"""
    try:
        je = frappe.new_doc("Journal Entry")
        je.company = company
        je.posting_date = parse_date(mut.get("Datum"))
        je.user_remark = f"{transaction_category}: {mut.get('Omschrijving', '')}"
        je.eboekhouden_invoice_number = mut.get("Factuurnummer")
        je.eboekhouden_mutation_nr = mut.get("MutatieNr")

        # Get supplier info
        supplier_code = mut.get("RelatieCode")
        description = mut.get("Omschrijving", "")

        # Add payable entry (credit side)
        rekening_code = mut.get("Rekening")
        if rekening_code:
            payable_account = get_account_by_code(rekening_code, company)
            if not payable_account:
                payable_account = frappe.db.get_value("Company", company, "default_payable_account")
        else:
            payable_account = frappe.db.get_value("Company", company, "default_payable_account")

        # Calculate total amount
        total_amount = 0
        for regel in mut.get("MutatieRegels", []):
            # Use inclusive amount for journal entries
            amount = float(regel.get("BedragInclBTW", 0) or regel.get("BedragExclBTW", 0))
            total_amount += amount

        if total_amount > 0:
            # Add credit entry (payable)
            je.append(
                "accounts",
                {
                    "account": payable_account,
                    "credit_in_account_currency": total_amount,
                    "cost_center": cost_center,
                    "party_type": "Supplier" if supplier_code else None,
                    "party": get_or_create_supplier(supplier_code, description, relation_data=None)
                    if supplier_code
                    else None,
                    "user_remark": description,
                },
            )

            # Add debit entries (expenses)
            for regel in mut.get("MutatieRegels", []):
                amount = float(regel.get("BedragInclBTW", 0) or regel.get("BedragExclBTW", 0))
                if amount > 0:
                    expense_account = get_expense_account_by_code(regel.get("TegenrekeningCode"), company)
                    je.append(
                        "accounts",
                        {
                            "account": expense_account,
                            "debit_in_account_currency": amount,
                            "cost_center": cost_center,
                            "user_remark": regel.get("Omschrijving", description),
                        },
                    )

        je.insert(ignore_permissions=True)
        je.submit()

        return {"success": True}

    except Exception as e:
        return {"success": False, "error": f"Journal Entry for Invoice {mut.get('Factuurnummer')}: {str(e)}"}


@frappe.whitelist()
def get_mapping_statistics():
    """Get statistics about mapping usage"""
    stats = {
        "total_mappings": frappe.db.count("E-Boekhouden Account Mapping", {"is_active": 1}),
        "journal_entry_mappings": frappe.db.count(
            "E-Boekhouden Account Mapping", {"is_active": 1, "document_type": "Journal Entry"}
        ),
        "purchase_invoice_mappings": frappe.db.count(
            "E-Boekhouden Account Mapping", {"is_active": 1, "document_type": "Purchase Invoice"}
        ),
        "most_used_mappings": [],
        "unused_mappings": [],
    }

    # Get most used mappings
    most_used = frappe.get_all(
        "E-Boekhouden Account Mapping",
        filters={"is_active": 1, "usage_count": [">", 0]},
        fields=["name", "account_code", "account_name", "document_type", "usage_count"],
        order_by="usage_count desc",
        limit=10,
    )
    stats["most_used_mappings"] = most_used

    # Get unused mappings
    unused = frappe.get_all(
        "E-Boekhouden Account Mapping",
        filters={"is_active": 1, "usage_count": ["in", [0, None]]},
        fields=["name", "account_code", "account_name", "document_type"],
        limit=10,
    )
    stats["unused_mappings"] = unused

    return stats


def add_custom_fields_for_journal_entries():
    """Add custom fields to Journal Entry for E-Boekhouden tracking"""

    # Add eboekhouden_invoice_number to Journal Entry if not exists
    if not frappe.db.has_column("Journal Entry", "eboekhouden_invoice_number"):
        frappe.get_doc(
            {
                "doctype": "Custom Field",
                "dt": "Journal Entry",
                "fieldname": "eboekhouden_invoice_number",
                "fieldtype": "Data",
                "label": "E-Boekhouden Invoice Number",
                "unique": 1,
                "no_copy": 1,
                "insert_after": "user_remark",
            }
        ).insert(ignore_permissions=True)

    return {"success": True, "message": "Custom fields added to Journal Entry"}
