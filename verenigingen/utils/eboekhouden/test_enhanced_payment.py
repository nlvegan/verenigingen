"""
Test script for enhanced payment processing.
"""

import frappe
from frappe import _


@frappe.whitelist()
def test_enhanced_payment_with_mutation_5473():
    """
    Test the enhanced payment handler with mutation 5473 (multi-invoice supplier payment).

    This mutation has:
    - 2 invoices: "7771-2024-15525,7771-2024-15644"
    - 2 row allocations: 60.50 and 61.29
    - Ledger 13201869 (should map to Triodos)
    """
    from verenigingen.utils.eboekhouden.payment_processing import PaymentEntryHandler

    # Test mutation data
    mutation = {
        "id": 5473,
        "type": 4,  # Supplier payment
        "date": "2024-12-10",
        "amount": 121.79,
        "ledgerId": 13201869,  # Triodos bank
        "relationId": "TEST-ENHANCED-SUPP",
        "invoiceNumber": "TEST-PI-001,TEST-PI-002",
        "description": "Test enhanced payment with multiple invoices",
        "rows": [{"ledgerId": 13201853, "amount": -60.50}, {"ledgerId": 13201853, "amount": -61.29}],
    }

    company = frappe.db.get_single_value("Global Defaults", "default_company")

    # Create test supplier
    if not frappe.db.exists("Supplier", "TEST-ENHANCED-SUPP"):
        supplier = frappe.new_doc("Supplier")
        supplier.supplier_name = "Test Enhanced Supplier"
        supplier.supplier_group = frappe.db.get_value("Supplier Group", {}, "name")
        supplier.save()

    # Process with enhanced handler
    handler = PaymentEntryHandler(company)
    payment_name = handler.process_payment_mutation(mutation)

    if payment_name:
        pe = frappe.get_doc("Payment Entry", payment_name)

        result = {
            "success": True,
            "payment_entry": payment_name,
            "payment_type": pe.payment_type,
            "amount": pe.paid_amount,
            "bank_account": pe.paid_from,
            "party": pe.party,
            "reference": pe.reference_no,
            "debug_log": handler.get_debug_log(),
        }

        # Highlight improvements
        improvements = []
        if "Triodos" in pe.paid_from:
            improvements.append("✓ Correctly mapped to Triodos bank (not hardcoded Kas)")
        if "TEST-PI-001,TEST-PI-002" in pe.reference_no:
            improvements.append("✓ Preserved multi-invoice reference")
        if len(handler._parse_invoice_numbers(mutation["invoiceNumber"])) == 2:
            improvements.append("✓ Parsed 2 separate invoices")

        result["improvements"] = improvements

        return result
    else:
        return {"success": False, "error": "Failed to create payment", "debug_log": handler.get_debug_log()}


@frappe.whitelist()
def compare_payment_methods():
    """
    Compare hardcoded vs enhanced payment processing.
    """
    # Get a recent payment created with hardcoded method
    hardcoded_payments = frappe.db.sql(
        """
        SELECT
            name,
            eboekhouden_mutation_nr,
            paid_to,
            paid_from,
            payment_type,
            party,
            reference_no
        FROM `tabPayment Entry`
        WHERE paid_to = '10000 - Kas - NVV'
           OR paid_from = '10000 - Kas - NVV'
        AND eboekhouden_mutation_nr IS NOT NULL
        ORDER BY creation DESC
        LIMIT 5
    """,
        as_dict=True,
    )

    comparison = {
        "hardcoded_examples": [],
        "improvements_possible": 0,
        "total_analyzed": len(hardcoded_payments),
    }

    for payment in hardcoded_payments:
        bank_account = payment.paid_to if payment.payment_type == "Receive" else payment.paid_from

        example = {
            "payment": payment.name,
            "mutation_id": payment.eboekhouden_mutation_nr,
            "current_bank": bank_account,
            "issues": [],
        }

        if "Kas" in bank_account:
            example["issues"].append("Hardcoded to Kas account")
            comparison["improvements_possible"] += 1

        if payment.reference_no and "," in payment.reference_no:
            example["issues"].append("Multi-invoice reference not properly handled")

        comparison["hardcoded_examples"].append(example)

    return comparison


@frappe.whitelist()
def check_ledger_mappings():
    """
    Check if we have proper ledger mappings for common bank accounts.
    """
    # Common bank ledger IDs from the API analysis
    common_ledgers = [
        13201869,  # Triodos (from mutations)
        13201853,  # Payable account
        13201852,  # Receivable account
    ]

    mappings = []
    for ledger_id in common_ledgers:
        mapping = frappe.db.get_value(
            "E-Boekhouden Ledger Mapping",
            {"ledger_id": ledger_id},
            ["ledger_code", "ledger_name", "erpnext_account"],
            as_dict=True,
        )

        if mapping:
            # Check account type
            account_type = frappe.db.get_value("Account", mapping["erpnext_account"], "account_type")
            mapping["account_type"] = account_type
            mapping["ledger_id"] = ledger_id
            mappings.append(mapping)
        else:
            mappings.append(
                {
                    "ledger_id": ledger_id,
                    "status": "NOT MAPPED",
                    "action_needed": "Create mapping for this ledger",
                }
            )

    return {
        "ledger_mappings": mappings,
        "recommendation": "Ensure all bank ledgers are properly mapped to ERPNext accounts",
    }
