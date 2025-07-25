"""
Setup script for testing enhanced payment processing.
"""

import frappe
from frappe import _


@frappe.whitelist()
def setup_payment_test_data():
    """
    Set up test data for enhanced payment processing.

    Creates:
    1. Ledger mapping for bank account
    2. Test supplier
    3. Test purchase invoices
    """
    company = frappe.db.get_single_value("Global Defaults", "default_company")
    results = {"setup_complete": False, "steps": []}

    # Step 1: Check/create bank account
    triodos = frappe.db.get_value("Account", {"account_number": "10440", "company": company}, "name")

    if triodos:
        results["steps"].append(f"✓ Found Triodos account: {triodos}")
    else:
        # Try any bank account
        bank_account = frappe.db.get_value(
            "Account", {"account_type": "Bank", "company": company, "is_group": 0}, "name"
        )
        if bank_account:
            triodos = bank_account
            results["steps"].append(f"✓ Using bank account: {bank_account}")
        else:
            results["steps"].append("✗ No bank account found")
            return results

    # Step 2: Create ledger mapping for 13201869
    if not frappe.db.exists("E-Boekhouden Ledger Mapping", {"ledger_id": 13201869}):
        mapping = frappe.new_doc("E-Boekhouden Ledger Mapping")
        mapping.ledger_id = 13201869
        mapping.ledger_code = "10440"
        mapping.ledger_name = "Triodos Bank (Test)"
        mapping.erpnext_account = triodos
        mapping.save()
        results["steps"].append("✓ Created ledger mapping 13201869 -> Triodos")
    else:
        results["steps"].append("✓ Ledger mapping already exists")

    # Step 3: Create test supplier
    if not frappe.db.exists("Supplier", "TEST-PAYMENT-SUPP"):
        supplier = frappe.new_doc("Supplier")
        supplier.supplier_name = "Test Payment Supplier"
        supplier.supplier_group = frappe.db.get_value("Supplier Group", {}, "name")
        supplier.save()
        results["steps"].append("✓ Created test supplier")
    else:
        results["steps"].append("✓ Test supplier already exists")

    # Step 4: Create test invoices
    item = frappe.db.get_value("Item", {"is_stock_item": 0}, "name")
    if not item:
        # Create service item
        item = frappe.new_doc("Item")
        item.item_code = "TEST-SERVICE"
        item.item_name = "Test Service"
        item.item_group = frappe.db.get_value("Item Group", {}, "name")
        item.is_stock_item = 0
        item.save()
        item = item.name
        results["steps"].append("✓ Created test item")

    # Create two test invoices
    invoices = []
    for i, amount in enumerate([60.50, 61.29], 1):
        inv_name = f"TEST-PI-{i:03d}"
        if not frappe.db.exists("Purchase Invoice", {"name": ["like", f"%{inv_name}%"]}):
            pi = frappe.new_doc("Purchase Invoice")
            pi.supplier = "TEST-PAYMENT-SUPP"
            pi.company = company
            pi.posting_date = "2024-12-01"
            pi.append("items", {"item_code": item, "qty": 1, "rate": amount})
            pi.save()
            pi.submit()
            invoices.append(pi.name)
            results["steps"].append(f"✓ Created invoice {pi.name} for {amount}")
        else:
            existing = frappe.db.get_value("Purchase Invoice", {"name": ["like", f"%{inv_name}%"]}, "name")
            invoices.append(existing)
            results["steps"].append(f"✓ Invoice {existing} already exists")

    results["setup_complete"] = True
    results["test_data"] = {
        "supplier": "TEST-PAYMENT-SUPP",
        "invoices": invoices,
        "bank_account": triodos,
        "ledger_id": 13201869,
    }

    return results


@frappe.whitelist()
def run_payment_test():
    """
    Run the enhanced payment test with prepared data.
    """
    from verenigingen.e_boekhouden.utils.payment_processing.payment_entry_handler import PaymentEntryHandler

    # First setup test data
    setup_result = setup_payment_test_data()
    if not setup_result["setup_complete"]:
        return {"success": False, "error": "Test data setup failed", "setup": setup_result}

    test_data = setup_result["test_data"]
    company = frappe.db.get_single_value("Global Defaults", "default_company")

    # Create test mutation
    mutation = {
        "id": 5473,
        "type": 4,  # Supplier payment
        "date": "2024-12-10",
        "amount": 121.79,
        "ledgerId": 13201869,  # Triodos
        "relationId": test_data["supplier"],
        "invoiceNumber": ",".join(test_data["invoices"]),
        "description": "Test enhanced payment with multiple invoices",
        "rows": [{"ledgerId": 13201853, "amount": -60.50}, {"ledgerId": 13201853, "amount": -61.29}],
    }

    # Process payment
    handler = PaymentEntryHandler(company)
    payment_name = handler.process_payment_mutation(mutation)

    if payment_name:
        pe = frappe.get_doc("Payment Entry", payment_name)

        # Check improvements
        improvements = []
        issues = []

        # Check bank account
        if test_data["bank_account"] in pe.paid_from:
            improvements.append(f"✓ Correctly used bank account: {pe.paid_from}")
        elif "Kas" in pe.paid_from:
            issues.append(f"✗ Still using hardcoded Kas: {pe.paid_from}")
        else:
            improvements.append(f"? Using different bank: {pe.paid_from}")

        # Check multi-invoice handling
        if len(pe.references) > 0:
            improvements.append(f"✓ Created {len(pe.references)} payment references")
            for ref in pe.references:
                improvements.append(f"  - {ref.reference_name}: {ref.allocated_amount}")
        else:
            issues.append("✗ No payment references created")

        # Check invoice parsing
        parsed_invoices = handler._parse_invoice_numbers(mutation["invoiceNumber"])
        if len(parsed_invoices) == 2:
            improvements.append(f"✓ Correctly parsed {len(parsed_invoices)} invoices")

        return {
            "success": True,
            "payment_entry": payment_name,
            "amount": pe.paid_amount,
            "bank_account": pe.paid_from,
            "party": pe.party,
            "reference": pe.reference_no,
            "improvements": improvements,
            "issues": issues,
            "debug_log": handler.get_debug_log()[-20:],  # Last 20 entries
        }
    else:
        return {"success": False, "error": "Payment creation failed", "debug_log": handler.get_debug_log()}


@frappe.whitelist()
def cleanup_test_data():
    """Clean up test data created for payment testing."""
    # Clean up test payments
    test_payments = frappe.db.sql(
        """
        SELECT name FROM `tabPayment Entry`
        WHERE party = 'TEST-PAYMENT-SUPP'
        OR eboekhouden_mutation_nr = '5473'
    """,
        pluck="name",
    )

    for payment in test_payments:
        doc = frappe.get_doc("Payment Entry", payment)
        if doc.docstatus == 1:
            doc.cancel()
        doc.delete()

    # Clean up test invoices
    test_invoices = frappe.db.sql(
        """
        SELECT name FROM `tabPurchase Invoice`
        WHERE supplier = 'TEST-PAYMENT-SUPP'
    """,
        pluck="name",
    )

    for invoice in test_invoices:
        doc = frappe.get_doc("Purchase Invoice", invoice)
        if doc.docstatus == 1:
            doc.cancel()
        doc.delete()

    return {"cleaned": {"payments": len(test_payments), "invoices": len(test_invoices)}}
