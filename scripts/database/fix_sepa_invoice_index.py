#!/usr/bin/env python3
"""
Fix incomplete SEPA invoice index by dropping and recreating with all required columns
"""

import frappe
from frappe.utils import now


@frappe.whitelist()
def fix_sepa_invoice_index():
    """Fix the incomplete idx_sepa_invoice_lookup index"""
    
    print(f"\n{'='*60}")
    print("FIXING INCOMPLETE SEPA INVOICE INDEX")
    print(f"{'='*60}")
    print(f"Timestamp: {now()}")
    print(f"{'='*60}\n")
    
    try:
        # Check current index structure
        print("1. Checking current index structure...")
        current_index = frappe.db.sql("""
            SHOW INDEX FROM `tabSales Invoice` 
            WHERE Key_name = 'idx_sepa_invoice_lookup'
        """, as_dict=True)
        
        if current_index:
            print(f"   Found existing index with {len(current_index)} columns:")
            for col in current_index:
                print(f"   - Column: {col.Column_name}, Position: {col.Seq_in_index}")
        else:
            print("   ⚠️  Index not found")
        
        # Drop existing index
        print("\n2. Dropping existing incomplete index...")
        try:
            frappe.db.sql("DROP INDEX `idx_sepa_invoice_lookup` ON `tabSales Invoice`")
            print("   ✅ Index dropped successfully")
        except Exception as e:
            if "Can't DROP" in str(e):
                print("   ℹ️  Index doesn't exist, proceeding to create")
            else:
                raise
        
        # Create complete index with all columns
        print("\n3. Creating complete index with all required columns...")
        create_sql = """
            CREATE INDEX `idx_sepa_invoice_lookup` 
            ON `tabSales Invoice` 
            (`docstatus`, `status`, `outstanding_amount`, `posting_date`, `custom_membership_dues_schedule`)
        """
        
        frappe.db.sql(create_sql)
        print("   ✅ Index created with all 5 columns")
        
        # Verify new index
        print("\n4. Verifying new index structure...")
        new_index = frappe.db.sql("""
            SHOW INDEX FROM `tabSales Invoice` 
            WHERE Key_name = 'idx_sepa_invoice_lookup'
        """, as_dict=True)
        
        if new_index:
            print(f"   ✅ Index verified with {len(new_index)} columns:")
            expected_columns = ['docstatus', 'status', 'outstanding_amount', 'posting_date', 'custom_membership_dues_schedule']
            actual_columns = [col.Column_name for col in sorted(new_index, key=lambda x: x.Seq_in_index)]
            
            for i, col in enumerate(actual_columns):
                expected = expected_columns[i] if i < len(expected_columns) else "N/A"
                status = "✅" if col == expected else "❌"
                print(f"   {status} Position {i+1}: {col} (expected: {expected})")
            
            if actual_columns == expected_columns:
                print("\n   ✅ All columns match expected structure!")
            else:
                print("\n   ⚠️  Column order differs from expected")
        
        # Analyze query performance impact
        print("\n5. Analyzing query performance...")
        explain_sql = """
            EXPLAIN SELECT si.name, si.customer, si.outstanding_amount
            FROM `tabSales Invoice` si
            WHERE si.docstatus = 1 
            AND si.status IN ('Unpaid', 'Overdue')
            AND si.outstanding_amount > 0
            AND si.posting_date <= CURDATE()
            ORDER BY si.posting_date
            LIMIT 100
        """
        
        explain_result = frappe.db.sql(explain_sql, as_dict=True)
        if explain_result:
            for row in explain_result:
                key_used = row.get('key', row.get('Key', 'None'))
                print(f"   Query using index: {key_used}")
                print(f"   Rows examined: {row.get('rows', row.get('Rows', 'Unknown'))}")
                if key_used == 'idx_sepa_invoice_lookup':
                    print("   ✅ New index is being used!")
        
        # Commit changes
        frappe.db.commit()
        
        print(f"\n{'='*60}")
        print("INDEX FIX COMPLETED SUCCESSFULLY")
        print(f"{'='*60}")
        
        return {
            "success": True,
            "message": "SEPA invoice index fixed successfully",
            "columns_added": len(new_index),
            "index_name": "idx_sepa_invoice_lookup"
        }
        
    except Exception as e:
        frappe.db.rollback()
        error_msg = f"Error fixing index: {str(e)}"
        print(f"\n❌ {error_msg}")
        frappe.log_error(error_msg, "SEPA Index Fix")
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to fix SEPA invoice index"
        }


if __name__ == "__main__":
    # Run the fix
    result = fix_sepa_invoice_index()
    print(f"\nResult: {result}")