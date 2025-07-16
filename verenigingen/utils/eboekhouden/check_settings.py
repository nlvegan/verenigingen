"""Check E-Boekhouden settings."""

import frappe


@frappe.whitelist()
def check_settings():
    """Check E-Boekhouden settings and payment configuration."""

    # Check if Global Defaults has the company
    company = frappe.db.get_single_value("Global Defaults", "default_company")

    # Check for E-Boekhouden specific settings
    settings_exist = frappe.db.exists("DocType", "E-Boekhouden Settings")

    results = {
        "company": company,
        "settings_doctype_exists": settings_exist,
        "payment_entries_with_kas": 0,
        "payment_entries_with_bank": 0,
    }

    # Count payment entries
    kas_count = frappe.db.count(
        "Payment Entry", {"paid_to": "10000 - Kas - NVV", "eboekhouden_mutation_nr": ["is", "set"]}
    )

    bank_count = frappe.db.count(
        "Payment Entry", {"paid_to": ["like", "%Triodos%"], "eboekhouden_mutation_nr": ["is", "set"]}
    )

    results["payment_entries_with_kas"] = kas_count
    results["payment_entries_with_bank"] = bank_count

    # Check if enhanced processing would work
    results["enhanced_ready"] = company is not None

    return results


@frappe.whitelist()
def test_payment_without_settings():
    """Test payment processing without relying on E-Boekhouden Settings."""
    from verenigingen.utils.eboekhouden.payment_processing.payment_entry_handler import PaymentEntryHandler

    # Use Global Defaults company
    company = frappe.db.get_single_value("Global Defaults", "default_company")
    if not company:
        return {"error": "No default company set"}

    # Test mutation
    mutation = {
        "id": 5473,
        "type": 4,  # Supplier payment
        "date": "2024-12-10",
        "amount": 121.79,
        "ledgerId": 13201869,  # Triodos
        "relationId": "ENHANCED-TEST-001",
        "invoiceNumber": "INV-001,INV-002",
        "description": "Final test of enhanced payment",
        "rows": [{"ledgerId": 13201853, "amount": -60.50}, {"ledgerId": 13201853, "amount": -61.29}],
    }

    # Create supplier if needed
    supplier_name = f"Enhanced Test Supplier {frappe.utils.random_string(4)}"
    supplier = frappe.new_doc("Supplier")
    supplier.supplier_name = supplier_name
    supplier.supplier_group = frappe.db.get_value("Supplier Group", {}, "name")
    supplier.save()
    mutation["relationId"] = supplier.name

    # Process payment
    handler = PaymentEntryHandler(company)
    payment_name = handler.process_payment_mutation(mutation)

    if payment_name:
        pe = frappe.get_doc("Payment Entry", payment_name)

        return {
            "success": True,
            "payment_entry": payment_name,
            "bank_account": pe.paid_from,
            "is_triodos": "Triodos" in pe.paid_from,
            "amount": pe.paid_amount,
            "party": pe.party,
            "reference": pe.reference_no,
            "handler_log": handler.get_debug_log()[-5:],
        }
    else:
        return {"success": False, "error": "Payment creation failed", "handler_log": handler.get_debug_log()}
