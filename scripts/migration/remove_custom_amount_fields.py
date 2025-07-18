#!/usr/bin/env python3
"""
Script to remove custom amount fields from Membership DocType
These fields are no longer needed as we're using Membership Dues Schedule
"""

import json

def remove_custom_amount_fields():
    """Remove custom amount fields from Membership DocType"""
    
    # Fields to remove
    fields_to_remove = [
        "custom_amount_section",
        "uses_custom_amount", 
        "custom_amount",
        "amount_reason",
        "column_break_custom",
        "effective_amount"
    ]
    
    # Load the DocType
    doctype_path = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/membership/membership.json"
    
    try:
        with open(doctype_path, 'r') as f:
            doctype_data = json.load(f)
        
        print(f"Original field count: {len(doctype_data['fields'])}")
        
        # Remove fields from field_order
        original_field_order = doctype_data['field_order'][:]
        for field in fields_to_remove:
            if field in doctype_data['field_order']:
                doctype_data['field_order'].remove(field)
                print(f"✓ Removed {field} from field_order")
        
        # Remove fields from fields array
        original_fields = doctype_data['fields'][:]
        doctype_data['fields'] = [
            field for field in doctype_data['fields'] 
            if field['fieldname'] not in fields_to_remove
        ]
        
        removed_fields = []
        for field in original_fields:
            if field['fieldname'] in fields_to_remove:
                removed_fields.append(field['fieldname'])
        
        print(f"✓ Removed {len(removed_fields)} fields from fields array: {removed_fields}")
        print(f"New field count: {len(doctype_data['fields'])}")
        
        # Write back the modified DocType
        with open(doctype_path, 'w') as f:
            json.dump(doctype_data, f, indent=1)
        
        print(f"✓ Updated {doctype_path}")
        
        return {
            "success": True,
            "removed_fields": removed_fields,
            "original_count": len(original_fields),
            "new_count": len(doctype_data['fields'])
        }
        
    except Exception as e:
        print(f"✗ Error: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }

def update_membership_python_file():
    """Update the membership.py file to remove custom amount references"""
    
    python_file_path = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/membership/membership.py"
    
    try:
        with open(python_file_path, 'r') as f:
            content = f.read()
        
        # Find and comment out custom amount related code
        lines = content.split('\n')
        updated_lines = []
        
        for line in lines:
            # Comment out lines that reference custom amount fields
            if any(field in line for field in ['uses_custom_amount', 'custom_amount', 'amount_reason', 'effective_amount']):
                if not line.strip().startswith('#'):
                    updated_lines.append(f"# DEPRECATED: {line}")
                    print(f"✓ Commented out: {line.strip()}")
                else:
                    updated_lines.append(line)
            else:
                updated_lines.append(line)
        
        # Write back the updated content
        with open(python_file_path, 'w') as f:
            f.write('\n'.join(updated_lines))
        
        print(f"✓ Updated {python_file_path}")
        
        return True
        
    except Exception as e:
        print(f"✗ Error updating Python file: {str(e)}")
        return False

if __name__ == "__main__":
    print("Removing custom amount fields from Membership DocType...")
    
    # Remove fields from JSON
    result = remove_custom_amount_fields()
    
    if result["success"]:
        print(f"\n✅ Successfully removed {len(result['removed_fields'])} fields")
        print(f"   Fields removed: {result['removed_fields']}")
        print(f"   Field count: {result['original_count']} → {result['new_count']}")
        
        # Update Python file
        if update_membership_python_file():
            print("✅ Python file updated successfully")
        else:
            print("⚠️  Python file update failed")
        
        print("\n🔄 Next steps:")
        print("1. Run: bench migrate")
        print("2. Run: bench restart")
        print("3. Test the system to ensure everything works")
        
    else:
        print(f"\n❌ Failed to remove fields: {result['error']}")