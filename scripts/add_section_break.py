#!/usr/bin/env python3
import json

# Read the current file
with open('/home/frappe/frappe-bench/apps/verenigingen/verenigingen/fixtures/custom_field.json', 'r') as f:
    fields = json.load(f)

# Create the section break field for Journal Entry
section_break = {
    "allow_in_quick_entry": 0,
    "allow_on_submit": 0,
    "bold": 0,
    "collapsible": 1,
    "collapsible_depends_on": None,
    "columns": 0,
    "default": None,
    "depends_on": None,
    "description": None,
    "docstatus": 0,
    "doctype": "Custom Field",
    "dt": "Journal Entry",
    "fetch_from": None,
    "fetch_if_empty": 0,
    "fieldname": "eboekhouden_section",
    "fieldtype": "Section Break",
    "hidden": 0,
    "hide_border": 0,
    "hide_days": 0,
    "hide_seconds": 0,
    "ignore_user_permissions": 0,
    "ignore_xss_filter": 0,
    "in_global_search": 0,
    "in_list_view": 0,
    "in_preview": 0,
    "in_standard_filter": 0,
    "insert_after": "amended_from",
    "is_system_generated": 0,
    "is_virtual": 0,
    "label": "E-Boekhouden Integration",
    "length": 0,
    "link_filters": None,
    "mandatory_depends_on": None,
    "module": "E-Boekhouden",
    "name": "Journal Entry-eboekhouden_section",
    "no_copy": 0,
    "non_negative": 0,
    "options": None,
    "permlevel": 0,
    "placeholder": None,
    "precision": "",
    "print_hide": 0,
    "print_hide_if_no_value": 0,
    "print_width": None,
    "read_only": 0,
    "read_only_depends_on": None,
    "report_hide": 0,
    "reqd": 0,
    "search_index": 0,
    "show_dashboard": 0,
    "sort_options": 0,
    "translatable": 0,
    "unique": 0,
    "width": None
}

# Check if section break already exists
section_exists = False
for field in fields:
    if field.get('dt') == 'Journal Entry' and field.get('fieldname') == 'eboekhouden_section':
        section_exists = True
        print("Section break already exists for Journal Entry E-Boekhouden fields")
        break

if not section_exists:
    # Find the position to insert (before first Journal Entry eboekhouden field)
    insert_position = None
    for i, field in enumerate(fields):
        if field.get('dt') == 'Journal Entry' and 'eboekhouden' in field.get('fieldname', ''):
            # Found the first E-Boekhouden field for Journal Entry
            insert_position = i
            break
    
    if insert_position is not None:
        # Insert the section break
        fields.insert(insert_position, section_break)
        
        # Update the first E-Boekhouden field to insert after the section
        fields[insert_position + 1]['insert_after'] = 'eboekhouden_section'
        
        print(f"Added section break at position {insert_position}")
        print("Updated first E-Boekhouden field to insert after section break")
        
        # Write the updated data
        with open('/home/frappe/frappe-bench/apps/verenigingen/verenigingen/fixtures/custom_field.json', 'w') as f:
            json.dump(fields, f, indent=1)
        
        print("File updated successfully")
    else:
        print("Could not find Journal Entry E-Boekhouden fields")
else:
    print("No changes needed")