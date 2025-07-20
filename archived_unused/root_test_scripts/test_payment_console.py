# Commands to run in bench console

from verenigingen.utils.eboekhouden.payment_processing import PaymentEntryHandler

# Test mutation data (multi-invoice supplier payment)
mutation = {
    "id": 5473,
    "type": 4,  # Supplier payment
    "date": "2024-12-10",
    "amount": 121.79,
    "ledgerId": 13201869,  # Should map to Triodos
    "relationId": "TEST-ENHANCED-SUPP",
    "invoiceNumber": "TEST-PI-001,TEST-PI-002",
    "description": "Test enhanced payment with multiple invoices",
    "rows": [{"ledgerId": 13201853, "amount": -60.50}, {"ledgerId": 13201853, "amount": -61.29}],
}

company = frappe.db.get_single_value("Global Defaults", "default_company")

# Create test supplier if needed
if not frappe.db.exists("Supplier", "TEST-ENHANCED-SUPP"):
    supplier = frappe.new_doc("Supplier")
    supplier.supplier_name = "Test Enhanced Supplier"
    supplier.supplier_group = frappe.db.get_value("Supplier Group", {}, "name")
    supplier.save()
    print("Created test supplier")

# Test the handler
handler = PaymentEntryHandler(company)
print(f"Initialized handler for company: {company}")

# Parse invoice numbers
invoices = handler._parse_invoice_numbers(mutation["invoiceNumber"])
print(f"Parsed invoices: {invoices}")

# Check bank account determination
bank_account = handler._determine_bank_account(mutation["ledgerId"], "Pay")
print(f"Determined bank account: {bank_account}")

# Process the payment
payment_name = handler.process_payment_mutation(mutation)
print(f"Payment created: {payment_name}")

if payment_name:
    pe = frappe.get_doc("Payment Entry", payment_name)
    print(f"\nPayment Details:")
    print(f"  Type: {pe.payment_type}")
    print(f"  Amount: {pe.paid_amount}")
    print(f"  Bank Account: {pe.paid_from}")
    print(f"  Party: {pe.party}")
    print(f"  Reference: {pe.reference_no}")

    if "Kas" not in pe.paid_from:
        print("\n✓ SUCCESS: Payment uses correct bank account (not hardcoded Kas)")
    else:
        print("\n✗ ISSUE: Payment still using Kas account")

# Show debug log
print("\nDebug Log:")
for entry in handler.get_debug_log()[-10:]:
    print(f"  {entry}")
