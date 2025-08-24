#!/usr/bin/env python3
import json

# Read the current file
with open('/home/frappe/frappe-bench/apps/verenigingen/verenigingen/fixtures/custom_field.json', 'r') as f:
    current = json.load(f)

# Track which fields we've seen
seen_fields = set()
cleaned_fields = []

# Fields to keep (legitimate new additions for Journal Entry)
new_fields_to_keep = {
    "Journal Entry-eboekhouden_invoice_number",
    "Journal Entry-custom_eboekhouden_main_ledger_id", 
    "Journal Entry-eboekhouden_mutation_type",
    "Journal Entry-eboekhouden_relation_code"
}

for field in current:
    # Check if it's an E-Boekhouden field
    if 'eboekhouden' in field.get('fieldname', ''):
        key = f"{field['dt']}-{field['fieldname']}"
        
        # Keep if:
        # 1. We haven't seen it before (first occurrence)
        # 2. OR it's one of the new fields we want to keep AND we haven't seen it
        if key not in seen_fields:
            cleaned_fields.append(field)
            seen_fields.add(key)
        else:
            # Skip duplicate
            print(f"Removing duplicate: {key}")
    else:
        # Not an E-Boekhouden field, keep it
        cleaned_fields.append(field)

# Write the cleaned data
with open('/home/frappe/frappe-bench/apps/verenigingen/verenigingen/fixtures/custom_field.json', 'w') as f:
    json.dump(cleaned_fields, f, indent=1)

print(f"\nCleaned file saved. Removed {len(current) - len(cleaned_fields)} duplicate entries.")
print(f"Total fields: {len(current)} -> {len(cleaned_fields)}")