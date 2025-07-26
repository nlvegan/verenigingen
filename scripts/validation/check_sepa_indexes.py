"""
Check SEPA Database Indexes Validation Script
"""

import frappe

@frappe.whitelist()
def check_sepa_indexes():
    """Check if SEPA database indexes were created"""
    
    print("\n" + "="*60)
    print("SEPA DATABASE INDEX VALIDATION")
    print("="*60 + "\n")
    
    indexes_to_check = [
        {
            "table": "tabSales Invoice",
            "name": "idx_sepa_invoice_lookup",
            "expected_columns": ["docstatus", "status", "outstanding_amount", "posting_date", "custom_membership_dues_schedule"]
        },
        {
            "table": "tabSEPA Mandate",
            "name": "idx_sepa_mandate_member_status",
            "expected_columns": ["member", "status", "iban", "mandate_id"]
        },
        {
            "table": "tabDirect Debit Batch Invoice",
            "name": "idx_direct_debit_batch_invoice",
            "expected_columns": ["invoice", "parent"]
        },
        {
            "table": "tabMembership Dues Schedule",
            "name": "idx_membership_dues_schedule_member_freq",
            "expected_columns": ["member", "status", "billing_frequency", "next_billing_period_start_date", "next_billing_period_end_date"]
        },
        {
            "table": "tabSEPA Mandate",
            "name": "idx_sepa_mandate_status_dates",
            "expected_columns": ["status", "sign_date", "expiry_date", "creation"]
        },
        {
            "table": "tabSales Invoice",
            "name": "idx_sales_invoice_payment_method",
            "expected_columns": ["status", "outstanding_amount", "custom_membership_dues_schedule"]
        },
        {
            "table": "tabDirect Debit Batch",
            "name": "idx_direct_debit_batch_status",
            "expected_columns": ["docstatus", "status", "batch_date"]
        }
    ]
    
    results = {
        "found": [],
        "missing": [],
        "incomplete": []
    }
    
    for index_info in indexes_to_check:
        table = index_info["table"]
        index_name = index_info["name"]
        expected_columns = index_info["expected_columns"]
        
        try:
            # Get index information
            index_data = frappe.db.sql(f"""
                SHOW INDEX FROM `{table}` 
                WHERE Key_name = %s
            """, (index_name,), as_dict=True)
            
            if not index_data:
                results["missing"].append({
                    "table": table,
                    "index": index_name,
                    "expected_columns": expected_columns
                })
                print(f"❌ MISSING: {index_name} on {table}")
            else:
                # Check if all expected columns are in the index
                indexed_columns = [row.Column_name for row in index_data]
                
                if len(indexed_columns) != len(expected_columns):
                    results["incomplete"].append({
                        "table": table,
                        "index": index_name,
                        "expected": expected_columns,
                        "actual": indexed_columns
                    })
                    print(f"⚠️  INCOMPLETE: {index_name} on {table}")
                    print(f"   Expected: {expected_columns}")
                    print(f"   Found: {indexed_columns}")
                else:
                    results["found"].append({
                        "table": table,
                        "index": index_name,
                        "columns": indexed_columns
                    })
                    print(f"✅ FOUND: {index_name} on {table} with columns: {indexed_columns}")
                    
        except Exception as e:
            print(f"❌ ERROR checking {index_name} on {table}: {str(e)}")
    
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"✅ Found: {len(results['found'])} indexes")
    print(f"❌ Missing: {len(results['missing'])} indexes")
    print(f"⚠️  Incomplete: {len(results['incomplete'])} indexes")
    print(f"📊 Total expected: {len(indexes_to_check)} indexes")
    
    # Detailed missing report
    if results["missing"]:
        print("\nMISSING INDEXES (need to be created):")
        for missing in results["missing"]:
            print(f"  - {missing['index']} on {missing['table']}")
            print(f"    Expected columns: {missing['expected_columns']}")
    
    # Check performance impact
    print("\n" + "="*60)
    print("PERFORMANCE IMPACT CHECK")
    print("="*60)
    
    # Check a sample query that should benefit from indexes
    try:
        # Query that should use idx_sepa_invoice_lookup
        query_plan = frappe.db.sql("""
            EXPLAIN SELECT name, customer, outstanding_amount, currency, due_date, custom_membership_dues_schedule 
            FROM `tabSales Invoice`
            WHERE docstatus = 1 
            AND status IN ('Unpaid', 'Overdue')
            AND custom_membership_dues_schedule IS NOT NULL
            LIMIT 10
        """, as_dict=True)
        
        print("\nSample query execution plan:")
        for row in query_plan:
            print(f"  Table: {row.get('table', 'N/A')}, Type: {row.get('type', 'N/A')}, "
                  f"Possible Keys: {row.get('possible_keys', 'None')}, Key Used: {row.get('key', 'None')}")
            
    except Exception as e:
        print(f"Could not check query plan: {str(e)}")
    
    return results


if __name__ == "__main__":
    # This will only work when executed through bench
    print("Please run this script through bench:")
    print("bench --site dev.veganisme.net execute verenigingen.scripts.validation.check_sepa_indexes.check_sepa_indexes")