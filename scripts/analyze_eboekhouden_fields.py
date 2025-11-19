#!/usr/bin/env python3
import json
import subprocess

# Read the current file
with open('/home/frappe/frappe-bench/apps/verenigingen/verenigingen/fixtures/custom_field.json', 'r') as f:
    current = json.load(f)

# Get existing fields from git
result = subprocess.run(['git', 'show', 'HEAD~1:verenigingen/fixtures/custom_field.json'], 
                       capture_output=True, text=True, cwd='/home/frappe/frappe-bench/apps/verenigingen')
previous = json.loads(result.stdout)

# Extract E-Boekhouden fields
def get_eb_fields(data):
    fields = {}
    for field in data:
        if 'eboekhouden' in field.get('fieldname', ''):
            key = f"{field['dt']}-{field['fieldname']}"
            fields[key] = field
    return fields

previous_fields = get_eb_fields(previous)
current_fields = get_eb_fields(current)

# Find new and existing
new_fields = set(current_fields.keys()) - set(previous_fields.keys())
existing_fields = set(previous_fields.keys())
all_current = set(current_fields.keys())

print("=== Previously Existing E-Boekhouden Fields ===")
for key in sorted(existing_fields):
    print(f"  {key}")

print(f"\nTotal existing: {len(existing_fields)}")

print("\n=== New E-Boekhouden Fields Added ===")
for key in sorted(new_fields):
    print(f"  {key}")

print(f"\nTotal new: {len(new_fields)}")

# Check for duplicates in current file
print("\n=== Checking for Duplicates in Current File ===")
field_counts = {}
for field in current:
    if 'eboekhouden' in field.get('fieldname', ''):
        key = f"{field['dt']}-{field['fieldname']}"
        field_counts[key] = field_counts.get(key, 0) + 1

duplicates = {k: v for k, v in field_counts.items() if v > 1}
if duplicates:
    print("DUPLICATES FOUND:")
    for key, count in duplicates.items():
        print(f"  {key}: appears {count} times")
else:
    print("No duplicates found")