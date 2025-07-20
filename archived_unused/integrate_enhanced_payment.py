"""
Integration script to update the main migration file to use enhanced payment processing.

This script modifies the eboekhouden_rest_full_migration.py file to use the new
PaymentEntryHandler instead of the hardcoded implementation.
"""

import frappe
from frappe import _


@frappe.whitelist()
def integrate_enhanced_payment_handler():
    """
    Update the main migration file to use enhanced payment processing.

    This function modifies _create_payment_entry to use the new handler.
    """
    file_path = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/eboekhouden/eboekhouden_rest_full_migration.py"

    # Read the current file
    with open(file_path, "r") as f:
        content = f.read()

    # Find the _create_payment_entry function
    old_function = '''def _create_payment_entry(mutation, company, cost_center, debug_info):
    """Create Payment Entry from mutation"""
    mutation_id = mutation.get("id")
    # mutation.get("description", "eBoekhouden Import {mutation_id}")
    amount = frappe.utils.flt(mutation.get("amount", 0), 2)
    relation_id = mutation.get("relationId")
    invoice_number = mutation.get("invoiceNumber")
    mutation_type = mutation.get("type", 3)

    payment_type = "Receive" if mutation_type == 3 else "Pay"

    pe = frappe.new_doc("Payment Entry")
    pe.company = company
    pe.posting_date = mutation.get("date")
    pe.payment_type = payment_type
    pe.eboekhouden_mutation_nr = str(mutation_id)

    if payment_type == "Receive":
        pe.paid_to = "10000 - Kas - NVV"
        pe.received_amount = amount
        if relation_id:
            pe.party_type = "Customer"
            pe.party = relation_id
            pe.paid_from = frappe.db.get_value(
                "Account", {"account_type": "Receivable", "company": company}, "name"
            )
    else:
        pe.paid_from = "10000 - Kas - NVV"
        pe.paid_amount = amount
        if relation_id:
            pe.party_type = "Supplier"
            pe.party = relation_id
            pe.paid_to = frappe.db.get_value(
                "Account", {"account_type": "Payable", "company": company}, "name"
            )

    pe.reference_no = invoice_number if invoice_number else "EB-{mutation_id}"
    pe.reference_date = mutation.get("date")

    pe.save()
    pe.submit()
    debug_info.append(f"Created Payment Entry {pe.name}")
    return pe'''

    # New implementation that uses the enhanced handler
    new_function = '''def _create_payment_entry(mutation, company, cost_center, debug_info):
    """
    Create Payment Entry from mutation.

    This function now uses the enhanced PaymentEntryHandler for:
    - Proper bank account mapping from ledger IDs
    - Multi-invoice payment support
    - Automatic payment reconciliation
    """
    # Check if enhanced processing is enabled
    use_enhanced = frappe.db.get_single_value("E-Boekhouden Settings", "use_enhanced_payment_processing")
    if use_enhanced is None:
        use_enhanced = True  # Default to enhanced if setting doesn't exist

    if use_enhanced:
        # Use enhanced payment handler
        from verenigingen.utils.eboekhouden.enhanced_payment_import import create_enhanced_payment_entry

        payment_name = create_enhanced_payment_entry(mutation, company, cost_center, debug_info)
        if payment_name:
            return frappe.get_doc("Payment Entry", payment_name)
        else:
            # Fall back to basic implementation if enhanced fails
            debug_info.append("WARNING: Enhanced payment creation failed, using basic implementation")

    # Basic implementation (legacy)
    mutation_id = mutation.get("id")
    amount = frappe.utils.flt(mutation.get("amount", 0), 2)
    relation_id = mutation.get("relationId")
    invoice_number = mutation.get("invoiceNumber")
    mutation_type = mutation.get("type", 3)

    payment_type = "Receive" if mutation_type == 3 else "Pay"

    pe = frappe.new_doc("Payment Entry")
    pe.company = company
    pe.posting_date = mutation.get("date")
    pe.payment_type = payment_type
    pe.eboekhouden_mutation_nr = str(mutation_id)

    # DEPRECATED: Hardcoded bank accounts
    if payment_type == "Receive":
        pe.paid_to = "10000 - Kas - NVV"  # Should use ledger mapping
        pe.received_amount = amount
        if relation_id:
            pe.party_type = "Customer"
            pe.party = _get_or_create_customer(relation_id, debug_info)
            pe.paid_from = frappe.db.get_value(
                "Account", {"account_type": "Receivable", "company": company}, "name"
            )
    else:
        pe.paid_from = "10000 - Kas - NVV"  # Should use ledger mapping
        pe.paid_amount = amount
        if relation_id:
            pe.party_type = "Supplier"
            pe.party = _get_or_create_supplier(relation_id, "", debug_info)
            pe.paid_to = frappe.db.get_value(
                "Account", {"account_type": "Payable", "company": company}, "name"
            )

    pe.reference_no = invoice_number if invoice_number else f"EB-{mutation_id}"
    pe.reference_date = mutation.get("date")

    pe.save()
    pe.submit()
    debug_info.append(f"Created Payment Entry {pe.name} (Basic Implementation)")
    return pe'''

    # Replace the function
    if old_function in content:
        content = content.replace(old_function, new_function)

        # Write back the modified content
        with open(file_path, "w") as f:
            f.write(content)

        return {"success": True, "message": "Successfully integrated enhanced payment handler"}
    else:
        return {"success": False, "message": "Could not find the _create_payment_entry function to replace"}


@frappe.whitelist()
def add_enhanced_payment_setting():
    """Add the enhanced payment processing setting to E-Boekhouden Settings."""
    try:
        # Check if the field already exists
        if not frappe.db.has_column("E-Boekhouden Settings", "use_enhanced_payment_processing"):
            # Add the field
            frappe.db.sql(
                """
                ALTER TABLE `tabE-Boekhouden Settings`
                ADD COLUMN `use_enhanced_payment_processing` INT(1) DEFAULT 1
            """
            )

            # Clear cache
            frappe.clear_cache(doctype="E-Boekhouden Settings")

        # Set the default value
        frappe.db.set_single_value("E-Boekhouden Settings", "use_enhanced_payment_processing", 1)

        return {"success": True, "message": "Added enhanced payment processing setting"}

    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    # Run the integration
    result = integrate_enhanced_payment_handler()
    print(result)
