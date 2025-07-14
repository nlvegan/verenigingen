"""
Simple test for enhanced payment handler without invoice creation.
"""

import frappe
from frappe import _


@frappe.whitelist()
def test_payment_handler_simple():
    """
    Test the payment handler with a simple mutation.
    """
    from verenigingen.utils.eboekhouden.payment_processing import PaymentEntryHandler

    company = frappe.db.get_single_value("Global Defaults", "default_company")

    # Test mutation based on real data
    mutation = {
        "id": 5473,
        "type": 4,  # Supplier payment
        "date": "2024-12-10",
        "amount": 121.79,
        "ledgerId": 13201869,  # Should map to bank account
        "relationId": "TEST-SIMPLE-SUPP",
        "invoiceNumber": "TEST-INV-001,TEST-INV-002",  # Multi-invoice
        "description": "Test payment for enhanced handler",
        "rows": [{"ledgerId": 13201853, "amount": -60.50}, {"ledgerId": 13201853, "amount": -61.29}],
    }

    # Create test supplier if needed
    if not frappe.db.exists("Supplier", "TEST-SIMPLE-SUPP"):
        try:
            supplier = frappe.new_doc("Supplier")
            supplier.supplier_name = "Test Simple Supplier"
            supplier.supplier_group = frappe.db.get_value("Supplier Group", {}, "name")
            supplier.save()
        except frappe.DuplicateEntryError:
            # Supplier exists with different ID, find it
            supplier_id = frappe.db.get_value("Supplier", {"supplier_name": "Test Simple Supplier"}, "name")
            if supplier_id:
                mutation["relationId"] = supplier_id

    # Initialize handler
    handler = PaymentEntryHandler(company)

    # Test invoice parsing
    invoices = handler._parse_invoice_numbers(mutation["invoiceNumber"])

    # Test bank account determination
    bank_account = handler._determine_bank_account(mutation["ledgerId"], "Pay")

    # Process payment
    payment_name = handler.process_payment_mutation(mutation)

    results = {
        "success": payment_name is not None,
        "payment_entry": payment_name,
        "parsed_invoices": invoices,
        "invoice_count": len(invoices),
        "determined_bank_account": bank_account,
        "is_kas_account": "Kas" in bank_account if bank_account else False,
        "debug_log": handler.get_debug_log()[-10:],  # Last 10 entries
    }

    if payment_name:
        pe = frappe.get_doc("Payment Entry", payment_name)
        results.update(
            {
                "payment_type": pe.payment_type,
                "amount": pe.paid_amount,
                "actual_bank_account": pe.paid_from,
                "party": pe.party,
                "reference": pe.reference_no,
                "references_count": len(pe.references),
            }
        )

        # Check improvements
        improvements = []
        if not results["is_kas_account"]:
            improvements.append(f"✓ Bank account correctly determined: {bank_account}")
        else:
            improvements.append("✗ Still using Kas account")

        if len(invoices) == 2:
            improvements.append("✓ Correctly parsed 2 invoices from comma-separated string")

        if pe.reference_no == mutation["invoiceNumber"]:
            improvements.append("✓ Preserved multi-invoice reference")

        results["improvements"] = improvements

    return results


@frappe.whitelist()
def check_eboekhouden_ledger_mappings():
    """
    Check if we have the necessary ledger mappings.
    """
    # Check for common ledger IDs from the API
    ledgers = [13201869, 13201853, 13201852]

    mappings = []
    for ledger_id in ledgers:
        mapping = frappe.db.get_value(
            "E-Boekhouden Ledger Mapping",
            {"ledger_id": ledger_id},
            ["ledger_code", "ledger_name", "erpnext_account"],
            as_dict=True,
        )

        if mapping:
            # Get account type
            if mapping.get("erpnext_account"):
                account_type = frappe.db.get_value("Account", mapping["erpnext_account"], "account_type")
                mapping["account_type"] = account_type
            mapping["ledger_id"] = ledger_id
            mapping["status"] = "Mapped"
        else:
            mapping = {
                "ledger_id": ledger_id,
                "status": "NOT MAPPED",
                "action": "Create mapping for this ledger",
            }

        mappings.append(mapping)

    # Check available bank accounts
    bank_accounts = frappe.db.sql(
        """
        SELECT name, account_number
        FROM `tabAccount`
        WHERE account_type IN ('Bank', 'Cash')
        AND company = %s
        AND is_group = 0
        LIMIT 5
    """,
        frappe.db.get_single_value("Global Defaults", "default_company"),
        as_dict=True,
    )

    return {
        "ledger_mappings": mappings,
        "available_bank_accounts": bank_accounts,
        "recommendation": "Map ledger 13201869 to a bank account for proper payment processing",
    }


@frappe.whitelist()
def create_test_ledger_mapping():
    """
    Create a test ledger mapping for demonstration.
    """
    company = frappe.db.get_single_value("Global Defaults", "default_company")

    # Find a bank account
    bank_account = frappe.db.get_value(
        "Account", {"account_type": "Bank", "company": company, "is_group": 0}, "name"
    )

    if not bank_account:
        return {"success": False, "error": "No bank account found in the system"}

    # Check if mapping already exists
    if frappe.db.exists("E-Boekhouden Ledger Mapping", {"ledger_id": 13201869}):
        return {
            "success": True,
            "message": "Ledger mapping already exists",
            "existing_mapping": frappe.db.get_value(
                "E-Boekhouden Ledger Mapping",
                {"ledger_id": 13201869},
                ["ledger_code", "ledger_name", "erpnext_account"],
                as_dict=True,
            ),
        }

    # Create mapping
    mapping = frappe.new_doc("E-Boekhouden Ledger Mapping")
    mapping.ledger_id = 13201869
    mapping.ledger_code = "10440"  # Triodos code
    mapping.ledger_name = "Test Bank Account"
    mapping.erpnext_account = bank_account
    mapping.save()

    return {
        "success": True,
        "message": "Created ledger mapping",
        "mapping": {"ledger_id": 13201869, "erpnext_account": bank_account},
    }
