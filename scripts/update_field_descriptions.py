#!/usr/bin/env python3
import json

# Read the current file
with open('/home/frappe/frappe-bench/apps/verenigingen/verenigingen/fixtures/custom_field.json', 'r') as f:
    fields = json.load(f)

# Descriptions to add
descriptions = {
    "Journal Entry-eboekhouden_relation_code": "E-Boekhouden relation code for linking with customer/supplier",
    "Journal Entry-eboekhouden_invoice_number": "Original invoice number from E-Boekhouden system",
    "Journal Entry-custom_eboekhouden_main_ledger_id": "E-Boekhouden main ledger account identifier",
    "Customer-eboekhouden_relation_code": "Unique E-Boekhouden relation code for this customer",
    "Supplier-eboekhouden_relation_code": "Unique E-Boekhouden relation code for this supplier",
    "Sales Invoice-eboekhouden_invoice_number": "E-Boekhouden invoice number for tracking",
    "Sales Invoice-eboekhouden_mutation_nr": "E-Boekhouden mutation number for this transaction",
    "Purchase Invoice-eboekhouden_invoice_number": "E-Boekhouden invoice number for tracking",
    "Purchase Invoice-eboekhouden_mutation_nr": "E-Boekhouden mutation number for this transaction",
    "Payment Entry-eboekhouden_mutation_nr": "E-Boekhouden mutation number for this payment"
}

# Update descriptions
updated_count = 0
for field in fields:
    field_key = f"{field.get('dt')}-{field.get('fieldname')}"
    if field_key in descriptions and not field.get('description'):
        field['description'] = descriptions[field_key]
        updated_count += 1
        print(f"Added description for: {field_key}")

# Write the updated data
with open('/home/frappe/frappe-bench/apps/verenigingen/verenigingen/fixtures/custom_field.json', 'w') as f:
    json.dump(fields, f, indent=1)

print(f"\nUpdated {updated_count} field descriptions")