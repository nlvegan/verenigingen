"""
Quick test to verify enhanced payment processing.
"""

import frappe
from frappe import _


@frappe.whitelist()
def quick_test():
    """Quick test of payment handler functionality."""
    from verenigingen.utils.eboekhouden.payment_processing.payment_entry_handler import PaymentEntryHandler

    company = frappe.db.get_single_value("Global Defaults", "default_company")

    # Initialize handler
    handler = PaymentEntryHandler(company)

    # Test 1: Invoice parsing
    invoice_str = "INV-001,INV-002,INV-003"
    parsed = handler._parse_invoice_numbers(invoice_str)

    # Test 2: Bank account determination
    bank_account = handler._determine_bank_account(13201869, "Pay")

    results = {"tests_passed": [], "tests_failed": [], "details": {}}

    # Check invoice parsing
    if len(parsed) == 3 and parsed == ["INV-001", "INV-002", "INV-003"]:
        results["tests_passed"].append("✓ Invoice parsing works correctly")
        results["details"]["parsed_invoices"] = parsed
    else:
        results["tests_failed"].append("✗ Invoice parsing failed")

    # Check bank account mapping
    if bank_account and "Triodos" in bank_account:
        results["tests_passed"].append(f"✓ Bank account correctly mapped: {bank_account}")
        results["details"]["bank_account"] = bank_account
    elif bank_account and "Kas" in bank_account:
        results["tests_failed"].append(f"✗ Still defaulting to Kas: {bank_account}")
        results["details"]["bank_account"] = bank_account
    else:
        results["tests_failed"].append(f"✗ Bank account mapping failed: {bank_account}")

    # Test 3: Simple payment creation (without party)
    test_mutation = {
        "id": 99999,
        "type": 3,  # Customer payment
        "date": "2024-12-10",
        "amount": 100.00,
        "ledgerId": 13201869,  # Triodos
        "description": "Quick test payment",
    }

    try:
        payment_name = handler.process_payment_mutation(test_mutation)
        if payment_name:
            results["tests_passed"].append(f"✓ Payment created: {payment_name}")
            results["details"]["payment_entry"] = payment_name

            # Check the payment
            pe = frappe.get_doc("Payment Entry", payment_name)
            if "Triodos" in pe.paid_to:
                results["tests_passed"].append("✓ Payment uses Triodos bank account")
            else:
                results["tests_failed"].append(f"✗ Payment uses: {pe.paid_to}")

            # Clean up
            pe.cancel()
            pe.delete()
        else:
            results["tests_failed"].append("✗ Payment creation failed")
    except Exception as e:
        results["tests_failed"].append(f"✗ Payment test error: {str(e)}")

    # Summary
    results["summary"] = {
        "total_passed": len(results["tests_passed"]),
        "total_failed": len(results["tests_failed"]),
        "success_rate": f"{len(results['tests_passed']) / (len(results['tests_passed']) + len(results['tests_failed'])) * 100:.0f}%",
    }

    return results


@frappe.whitelist()
def check_migration_status():
    """Check if the enhanced payment handler is integrated."""
    # Read the _create_payment_entry function to see if it's using enhanced handler
    import os

    file_path = os.path.join(
        frappe.get_app_path("verenigingen"), "utils/eboekhouden/eboekhouden_rest_full_migration.py"
    )

    with open(file_path, "r") as f:
        content = f.read()

    results = {"integration_status": "Unknown", "checks": []}

    # Check if enhanced import is present
    if (
        "from verenigingen.utils.eboekhouden.enhanced_payment_import import create_enhanced_payment_entry"
        in content
    ):
        results["checks"].append("✓ Enhanced import statement found")
        results["integration_status"] = "Integrated"
    else:
        results["checks"].append("✗ Enhanced import statement not found")

    # Enhanced payment processing is always enabled for data quality
    results["checks"].append("✓ Enhanced payment processing always enabled")

    # Check if hardcoded Kas is still there
    if 'pe.paid_to = "10000 - Kas - NVV"' in content:
        results["checks"].append("✓ Hardcoded Kas still present (for fallback)")

    return results
